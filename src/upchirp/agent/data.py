"""Read-side queries the agent's tools are built on.

With UPCHIRP_DATABASE_URL set they read the live database (runs written by the
stream services); without it they read a session's Parquet files.
Times in answers are seconds from the start of the session, plus UTC clock time.
"Last N minutes" is measured back from the newest frame in the session, so a
replayed recording behaves the same as live data.
"""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from upchirp import store
from upchirp.dsp.tracker import TrackState
from upchirp.recording import (
    MANIFEST_FILE,
    TRACKS_FILE,
    read_manifest,
    read_rows,
    resolve_session,
    sessions_dir,
)

LABELS = ("person", "car", "drone_like", "unknown")


def _clock(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _r(x: float, nd: int = 2) -> float | None:
    return None if x != x else round(float(x), nd)  # NaN becomes None in JSON


def list_sessions(data_dir: Path) -> list[dict[str, Any]]:
    if store.database_url():
        with store.connect() as conn:
            return [{
                "session_id": r["run_id"],
                "recording": r["session_id"],
                "source": r["source"],
                "started": r["first_ts"].strftime("%Y-%m-%d %H:%M:%S UTC"),
                "frames": r["frames"],
                "duration_s": round((r["last_ts"] - r["first_ts"]).total_seconds(), 1),
                "processed": True,
            } for r in store.list_runs(conn)]
    out = []
    for path in sorted(sessions_dir(data_dir).glob(f"*/{MANIFEST_FILE}")):
        m = read_manifest(path.parent)
        scene = m.get("scene", {})
        out.append({
            "session_id": m["session_id"],
            "source": m["source"],
            "scene": scene.get("name"),
            "started": _clock(m["start_ns"]),
            "frames": m["n_frames"],
            "duration_s": scene.get("duration_s"),
            "processed": (path.parent / TRACKS_FILE).exists(),
            "operator_notes": m.get("notes", ""),
        })
    return out


def load_tracks(data_dir: Path, session: str) -> tuple[str, int, list[TrackState]]:
    """(session or run id, start time in ns, confirmed track states)."""
    if store.database_url():
        with store.connect() as conn:
            run = store.resolve_run(conn, session)
            states = store.load_track_states(conn, run["run_id"])
        return run["run_id"], int(run["first_ts"].timestamp() * 1e9), states
    session_dir = resolve_session(data_dir, session)
    tracks_path = session_dir / TRACKS_FILE
    if not tracks_path.exists():
        raise FileNotFoundError(
            f"session {session_dir.name} has not been processed yet; replay it first"
        )
    manifest = read_manifest(session_dir)
    states = [t for t in read_rows(tracks_path, TrackState) if t.confirmed]
    return manifest["session_id"], manifest["start_ns"], states


def _track_label(states: list[TrackState]) -> str:
    known = [s.label for s in states if s.label != "unknown"]
    return Counter(known).most_common(1)[0][0] if known else "unknown"


STITCH_GAP_S = 3.0
STITCH_OVERLAP_S = 0.5  # a new piece often starts just before the old one is dropped
STITCH_DISTANCE_M = 6.0


def stitch(by_track: dict[int, list[TrackState]]) -> dict[int, list[int]]:
    """Join track pieces that are one object: a track that starts within STITCH_GAP_S after
    (or STITCH_OVERLAP_S before) another of the same label ends, where that one was
    heading (within STITCH_DISTANCE_M of its position carried forward at its last
    velocity). The tracker can break a track
    when two objects share a range and angle, such as a drone flying over a car
    (decision 0012). Returns {object id (its first track id): [track ids]}."""
    pieces = sorted(by_track.items(), key=lambda kv: kv[1][0].timestamp_ns)
    labels = {tid: _track_label(hist) for tid, hist in pieces}
    objects: dict[int, list[int]] = {}
    tail: dict[int, TrackState] = {}  # object id -> its newest state
    for tid, hist in pieces:
        first = hist[0]
        best, best_d = None, STITCH_DISTANCE_M
        for oid, last in tail.items():
            gap = (first.timestamp_ns - last.timestamp_ns) / 1e9
            in_time = -STITCH_OVERLAP_S <= gap <= STITCH_GAP_S
            if not in_time or labels[objects[oid][0]] != labels[tid]:
                continue
            px, py = last.x_m + last.vx_mps * gap, last.y_m + last.vy_mps * gap
            d = float(np.hypot(first.x_m - px, first.y_m - py))
            if d <= best_d:
                best, best_d = oid, d
        oid = best if best is not None else tid
        objects.setdefault(oid, []).append(tid)
        if hist[-1].timestamp_ns >= tail.get(oid, hist[-1]).timestamp_ns:
            tail[oid] = hist[-1]
    return objects


def track_summaries(
    data_dir: Path,
    session: str = "latest",
    label: str | None = None,
    last_minutes: float | None = None,
) -> dict[str, Any]:
    """One summary per object (stitched track pieces), optionally filtered by label and
    time window."""
    if label is not None and label not in LABELS:
        raise ValueError(f"label must be one of {', '.join(LABELS)}")
    session_id, start_ns, states = load_tracks(data_dir, session)
    end_ns = max((s.timestamp_ns for s in states), default=start_ns)
    from_ns = start_ns if last_minutes is None else max(start_ns, end_ns - last_minutes * 60e9)

    by_track: dict[int, list[TrackState]] = {}
    for s in states:
        by_track.setdefault(s.track_id, []).append(s)

    tracks = []
    for track_id, piece_ids in sorted(stitch(by_track).items()):
        hist = sorted((s for tid in piece_ids for s in by_track[tid]),
                      key=lambda s: s.timestamp_ns)
        track_label = _track_label(hist)
        if label is not None and track_label != label:
            continue
        window = [s for s in hist if s.timestamp_ns >= from_ns]
        if not window:
            continue
        closest = min(window, key=lambda s: s.range_m)
        speeds = np.array([s.speed_mps for s in window])
        tracks.append({
            "track_id": track_id,
            "track_pieces": piece_ids,
            "label": track_label,
            "first_seen_s_after_start": _r((window[0].timestamp_ns - start_ns) / 1e9, 1),
            "last_seen_s_after_start": _r((window[-1].timestamp_ns - start_ns) / 1e9, 1),
            "closest_range_m": _r(closest.range_m),
            "closest_at_s_after_start": _r((closest.timestamp_ns - start_ns) / 1e9, 1),
            "closest_azimuth_deg": _r(closest.azimuth_deg, 1),
            "mean_speed_mps": _r(float(speeds.mean())),
            "max_speed_mps": _r(float(speeds.max())),
            "rcs_dbsm": _r(float(np.nanmedian([s.rcs_dbsm for s in window]))),
        })
    return {
        "session_id": session_id,
        "window": {
            "from_s": _r((from_ns - start_ns) / 1e9, 1),
            "to_s": _r((end_ns - start_ns) / 1e9, 1),
            "to_clock": _clock(end_ns),
        },
        "label_filter": label,
        "track_count": len(tracks),
        "tracks": tracks,
    }


def session_summary(data_dir: Path, session: str = "latest") -> dict[str, Any]:
    """Counts by label and the closest approach of each label."""
    summary = track_summaries(data_dir, session)
    by_label: dict[str, dict[str, Any]] = {}
    for t in summary["tracks"]:
        entry = by_label.setdefault(t["label"], {"tracks": 0, "closest_range_m": None})
        entry["tracks"] += 1
        if entry["closest_range_m"] is None or t["closest_range_m"] < entry["closest_range_m"]:
            entry["closest_range_m"] = t["closest_range_m"]
    return {
        "session_id": summary["session_id"],
        "duration_s": summary["window"]["to_s"],
        "ended": summary["window"]["to_clock"],
        "total_tracks": summary["track_count"],
        "by_label": by_label,
    }


def search_docs(docs_dir: Path, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Semantic search (pgvector) when the database has an index, else keyword search."""
    if store.database_url():
        from upchirp import rag

        try:
            with store.connect() as conn:
                row = conn.execute("SELECT count(*) AS n FROM doc_chunks").fetchone()
                if row and row["n"]:
                    return rag.search(conn, query, limit)
        except Exception:  # no index or no embedding model: fall back to keywords
            pass
    words = [w.lower() for w in query.split() if len(w) > 2]
    hits: list[tuple[int, str, str]] = []
    for path in sorted(docs_dir.rglob("*.md")):
        for para in path.read_text(encoding="utf-8").split("\n\n"):
            score = sum(para.lower().count(w) for w in words)
            if score:
                hits.append((score, path.relative_to(docs_dir).as_posix(), para.strip()[:800]))
    hits.sort(key=lambda h: -h[0])
    return [{"doc": doc, "text": text} for _, doc, text in hits[:limit]]
