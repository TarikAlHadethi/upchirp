"""Chaos test for recordings on disk and the agent's read queries over them.

Rules:
- a session id exists once; recording to it again is refused and changes nothing
- frames read back equal the frames written, and the manifest counts them
- "latest" is the session created last
- a session name with path parts is refused; a resolved session sits directly in sessions/
- replaying a session twice gives the same detections and tracks as once
- every confirmed track is in exactly one object of the answer
- label counts add up to the number of objects; filters only return a subset
- `closest` is the smallest closest range among the objects returned
"""

import random
import tempfile
from pathlib import Path
from typing import Any

import pytest
from chaos_support import Step, check, seeds

from upchirp.agent import data
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackState
from upchirp.frame import Frame
from upchirp.recording import (
    DETECTIONS_FILE,
    FRAMES_FILE,
    TRACKS_FILE,
    read_frames,
    read_manifest,
    read_rows,
    record_simulation,
    resolve_session,
    sessions_dir,
    write_rows,
)
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import default_scene

NAMES = ("a", "b", "c")
ODD_NAMES = ("..", "../a", "a/..", "a/b", "", ".", "nope", "a\\..\\b", "/", "sessions")
START_NS = 1_000
FRAMES: dict[str, list[Frame]] = {}


def _sim(name: str) -> Simulator:
    scene = default_scene().model_copy(update={"duration_s": 0.2})
    return Simulator(scene, session_id=name, start_ns=START_NS, seed=3)


def _frames(name: str) -> list[Frame]:
    if name not in FRAMES:
        FRAMES[name] = [f for f, _ in _sim(name).run()]
    return FRAMES[name]


def _states(name: str, seed: int) -> list[TrackState]:
    """Made-up tracker output: a few tracks over some minutes, some never confirmed."""
    rng = random.Random(seed)
    rows = []
    for track_id in range(1, rng.randrange(1, 7)):
        t = rng.uniform(0, 300)
        x, y = rng.uniform(-30, 30), rng.uniform(2, 60)
        vx, vy = rng.uniform(-3, 3), rng.uniform(-3, 3)
        label = rng.choice(["person", "car", "drone_like", "unknown"])
        for i in range(rng.randrange(1, 25)):
            x, y, t = x + vx * 0.1, max(y + vy * 0.1, 0.5), t + 0.1
            rows.append(TrackState(
                session_id=name, frame_index=int(t * 10), timestamp_ns=START_NS + int(t * 1e9),
                track_id=track_id, confirmed=i >= rng.choice([0, 2, 99]), x_m=x, y_m=y,
                vx_mps=vx, vy_mps=vy, range_m=(x * x + y * y) ** 0.5, azimuth_deg=0.0,
                radial_velocity_mps=0.0, speed_mps=(vx * vx + vy * vy) ** 0.5, hits=i + 1,
                misses=0, label=label if i > 2 else "unknown",
                rcs_dbsm=rng.choice([float("nan"), -12.0, 0.5])))
    return rows


class SessionsWorld:
    root: Path

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(dir=self.root))
        self.order: list[str] = []  # sessions, oldest first
        self.states: dict[str, list[TrackState]] = {}  # confirmed states of processed sessions
        self.problems: list[str] = []

    def _snapshot(self) -> list[tuple[str, int, int]]:
        return sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in self.dir.rglob("*") if p.is_file())

    def apply(self, step: Step) -> None:
        name, args = step
        session = NAMES[args[0] % len(NAMES)] if name != "resolve" else ""
        if name == "record":
            before = self._snapshot()
            try:
                path = record_simulation(_sim(session), self.dir)
            except FileExistsError:
                if session not in self.order or self._snapshot() != before:
                    self.problems.append("recording was refused wrongly, or changed files")
                return
            if session in self.order:
                self.problems.append(f"session {session} was recorded twice")
            self.order.append(session)
            back = list(read_frames(path / FRAMES_FILE))
            if back != _frames(session) or read_manifest(path)["n_frames"] != len(back):
                self.problems.append("frames read back differ from the frames recorded")
        elif name == "replay":
            if session not in self.order:
                self._expect_missing(lambda: resolve_session(self.dir, session))
                return
            path = resolve_session(self.dir, session)
            process_session(path)
            first = (repr(read_rows(path / DETECTIONS_FILE, Detection)),
                     repr(read_rows(path / TRACKS_FILE, TrackState)))
            process_session(path)
            again = (repr(read_rows(path / DETECTIONS_FILE, Detection)),
                     repr(read_rows(path / TRACKS_FILE, TrackState)))
            if first != again:
                self.problems.append("replaying twice gave different results")
            self.states[session] = [s for s in read_rows(path / TRACKS_FILE, TrackState)
                                    if s.confirmed]
        elif name == "tracks":
            if session in self.order:
                rows = _states(session, args[1])
                write_rows(sessions_dir(self.dir) / session / TRACKS_FILE, rows, TrackState)
                self.states[session] = [s for s in rows if s.confirmed]
        elif name == "resolve":
            odd = ODD_NAMES[args[0] % len(ODD_NAMES)]
            try:
                path = resolve_session(self.dir, odd)
                self.problems.append(f"session name {odd!r} resolved to {path.name!r}")
            except FileNotFoundError as e:
                if str(self.dir) in str(e):
                    self.problems.append("the refusal names a server path")
        elif name == "latest":
            if not self.order:
                self._expect_missing(lambda: resolve_session(self.dir, "latest"))
            elif (found := resolve_session(self.dir, "latest")).name != self.order[-1]:
                self.problems.append(f"latest is {found.name}, the newest is {self.order[-1]}")
            elif found.parent != sessions_dir(self.dir):
                self.problems.append("latest is not directly inside sessions/")
        else:
            self._query(session, args[1], args[2])

    def _expect_missing(self, call: Any) -> None:
        try:
            call()
            self.problems.append("something that does not exist was found")
        except FileNotFoundError:
            pass

    def _query(self, session: str, label_index: int, minutes: float) -> None:
        if session not in self.states:
            self._expect_missing(lambda: data.track_summaries(self.dir, session))
            return
        confirmed = self.states[session]
        everything = data.track_summaries(self.dir, session)
        pieces = [p for t in everything["tracks"] for p in t["track_pieces"]]
        if sorted(pieces) != sorted({s.track_id for s in confirmed}):
            self.problems.append("confirmed tracks and the pieces in the answer differ")
        summary = data.session_summary(self.dir, session)
        counts = sum(entry["tracks"] for entry in summary["by_label"].values())
        if not counts == summary["total_tracks"] == everything["track_count"] == len(
                everything["tracks"]):
            self.problems.append("label counts do not add up to the number of objects")
        label = (*data.LABELS, None)[label_index % 5]
        part = data.track_summaries(self.dir, session, label, minutes or None)
        ids = {t["track_id"] for t in everything["tracks"]}
        if not {t["track_id"] for t in part["tracks"]} <= ids:
            self.problems.append("a filter returned an object the full list does not have")
        if label is not None and any(t["label"] != label for t in part["tracks"]):
            self.problems.append("a label filter returned another label")
        by_label = sum(data.track_summaries(self.dir, session, lab)["track_count"]
                       for lab in data.LABELS)
        if by_label != everything["track_count"]:
            self.problems.append("the label filters together do not cover every object once")
        for answer in (everything, part):
            ranges = [t["closest_range_m"] for t in answer["tracks"]]
            closest = answer["closest"]
            if (closest is None) != (not ranges) or (ranges and closest["closest_range_m"]
                                                     != min(ranges)):
                self.problems.append("closest is not the smallest closest range")
        for t in everything["tracks"]:
            own = min(s.range_m for s in confirmed if s.track_id in t["track_pieces"])
            if t["closest_range_m"] != round(own, 2):
                self.problems.append(f"object {t['track_id']} closest range is wrong")

    def broken(self) -> list[str]:
        out = list(self.problems)
        listed = sorted(s["session_id"] for s in data.list_sessions(self.dir))
        if listed != sorted(self.order):
            out.append(f"sessions listed {listed}, recorded {sorted(self.order)}")
        return out


def _steps(seed: int, n: int = 30) -> list[Step]:
    rng = random.Random(seed)
    steps: list[Step] = []
    for _ in range(n):
        kind = rng.choice(["record", "record", "replay", "tracks", "tracks", "resolve",
                           "latest", "query", "query", "query", "query"])
        steps.append((kind, (rng.randrange(10), rng.randrange(10_000),
                             rng.choice([0, 0, 0.01, 1, 3, 10]))))
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_recordings_and_queries_keep_their_rules_under_chaos(
        seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    SessionsWorld.root = tmp_path
    check(SessionsWorld, _steps(seed), seed)
