"""Session recordings on disk.

Layout under the data directory:

    sessions/<session_id>/session.json         manifest: scene, seed, configs
    sessions/<session_id>/frames.parquet       one row per Frame, Frame fields as columns
    sessions/<session_id>/ground_truth.parquet one row per target per frame (sim only)
    sessions/<session_id>/detections.parquet   pipeline output, rewritten on each replay
    sessions/<session_id>/tracks.parquet       pipeline output, rewritten on each replay

`meta` is stored as a JSON string column, because Parquet maps need one value type.
"""

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, get_type_hints

import pyarrow as pa
import pyarrow.parquet as pq

from upchirp.frame import Frame
from upchirp.sim.engine import Simulator, TruthRow

FRAMES_FILE = "frames.parquet"
TRUTH_FILE = "ground_truth.parquet"
DETECTIONS_FILE = "detections.parquet"
TRACKS_FILE = "tracks.parquet"
MANIFEST_FILE = "session.json"
ROWS_PER_GROUP = 16

FRAME_SCHEMA = pa.schema([
    ("schema_version", pa.int32()),
    ("source", pa.string()),
    ("session_id", pa.string()),
    ("frame_index", pa.int64()),
    ("timestamp_ns", pa.int64()),
    ("chirp_config_id", pa.string()),
    ("n_rx", pa.int32()),
    ("n_chirps", pa.int32()),
    ("n_samples", pa.int32()),
    ("stage", pa.string()),
    ("data", pa.binary()),
    ("meta", pa.string()),
])

_ARROW_TYPES = {int: pa.int64(), float: pa.float64(), str: pa.string(), bool: pa.bool_()}


def schema_for(cls: type) -> pa.Schema:
    """Arrow schema for a dataclass with int, float, str and bool fields."""
    hints = get_type_hints(cls)
    return pa.schema([(f.name, _ARROW_TYPES[hints[f.name]]) for f in fields(cls)])


TRUTH_SCHEMA = schema_for(TruthRow)


def write_rows(path: Path, rows: Iterable[Any], cls: type) -> None:
    """Write dataclass rows (TruthRow, Detection, TrackState) to Parquet."""
    pq.write_table(pa.Table.from_pylist([asdict(r) for r in rows], schema=schema_for(cls)), path)


def read_rows[T](path: Path, cls: type[T]) -> list[T]:
    return [cls(**row) for row in pq.read_table(path).to_pylist()]


def sessions_dir(data_dir: Path) -> Path:
    return data_dir / "sessions"


def _frames_to_table(frames: list[Frame]) -> pa.Table:
    rows = [f.model_dump() for f in frames]
    for row in rows:
        row["meta"] = json.dumps(row["meta"])
    return pa.Table.from_pylist(rows, schema=FRAME_SCHEMA)


def write_frames(path: Path, frames: Iterable[Frame]) -> int:
    """Stream frames into a Parquet file. Returns the number written."""
    count = 0
    batch: list[Frame] = []
    with pq.ParquetWriter(path, FRAME_SCHEMA) as writer:
        for frame in frames:
            batch.append(frame)
            if len(batch) == ROWS_PER_GROUP:
                writer.write_table(_frames_to_table(batch))
                count += len(batch)
                batch = []
        if batch:
            writer.write_table(_frames_to_table(batch))
            count += len(batch)
    return count


def read_frames(path: Path) -> Iterator[Frame]:
    """Read frames back one at a time, without loading the whole file."""
    for batch in pq.ParquetFile(path).iter_batches(batch_size=ROWS_PER_GROUP):
        for row in batch.to_pylist():
            row["meta"] = json.loads(row["meta"])
            yield Frame(**row)


def record_simulation(sim: Simulator, data_dir: Path, notes: str = "") -> Path:
    """Run a simulation and save its frames, ground truth and manifest.

    `notes` is free text from the operator. It is untrusted: tools pass it to the
    agent as data, and step 5 evals plant instructions in it."""
    session_dir = sessions_dir(data_dir) / sim.session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    truth: list[TruthRow] = []

    def frames() -> Iterator[Frame]:
        for frame, rows in sim.run():
            truth.extend(rows)
            yield frame

    n_frames = write_frames(session_dir / FRAMES_FILE, frames())
    write_rows(session_dir / TRUTH_FILE, truth, TruthRow)
    manifest: dict[str, Any] = {
        "session_id": sim.session_id,
        "source": "sim",
        "created_ns": time.time_ns(),
        "start_ns": sim.start_ns,
        "n_frames": n_frames,
        "seed": sim.seed,
        "notes": notes,
        "scene": sim.scene.model_dump(),
        "chirp_config": sim.chirp.model_dump(),
        "array_config": sim.array.model_dump(),
    }
    (session_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2))
    return session_dir


def record_frames(frames: Iterable[Frame], data_dir: Path, session_id: str, source: str,
                  start_ns: int, chirp: Any, array: Any, notes: str = "",
                  extra: dict[str, Any] | None = None) -> Path:
    """Save frames from any source as a session (no ground truth), e.g. a real recording."""
    session_dir = sessions_dir(data_dir) / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    n_frames = write_frames(session_dir / FRAMES_FILE, frames)
    manifest = {
        "session_id": session_id, "source": source, "created_ns": time.time_ns(),
        "start_ns": start_ns, "n_frames": n_frames, "notes": notes,
        "chirp_config": chirp.model_dump(), "array_config": array.model_dump(), **(extra or {}),
    }
    (session_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2))
    return session_dir


def read_manifest(session_dir: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads((session_dir / MANIFEST_FILE).read_text())
    return manifest


def read_ground_truth(session_dir: Path) -> list[TruthRow]:
    return read_rows(session_dir / TRUTH_FILE, TruthRow)


def has_ground_truth(session_dir: Path) -> bool:
    return (session_dir / TRUTH_FILE).exists()


def resolve_session(data_dir: Path, session: str) -> Path:
    """Find a session directory by id, or the newest one for 'latest'."""
    root = sessions_dir(data_dir)
    if session != "latest":
        # a plain folder name only: no paths, and no server paths in the error
        if Path(session).name != session or session in ("", ".", ".."):
            raise FileNotFoundError(f"no session '{session}'")
        path = root / session
        if not (path / MANIFEST_FILE).exists():
            raise FileNotFoundError(f"no session '{session}'")
        return path
    candidates = [p.parent for p in root.glob(f"*/{MANIFEST_FILE}")]
    if not candidates:
        raise FileNotFoundError("no sessions yet; run 'upchirp sim' first")
    return max(candidates, key=lambda p: read_manifest(p)["created_ns"])
