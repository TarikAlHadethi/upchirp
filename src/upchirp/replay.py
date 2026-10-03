"""Run a recorded session through the pipeline and save its detections and tracks."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackState
from upchirp.pipeline import FrameResult, Pipeline
from upchirp.recording import DETECTIONS_FILE, TRACKS_FILE, read_manifest, write_rows
from upchirp.sources.replay import ReplaySource


def process_session(
    session_dir: Path,
    realtime: bool = False,
    on_frame: Callable[[FrameResult], None] | None = None,
) -> dict[str, Any]:
    manifest = read_manifest(session_dir)
    pipeline = Pipeline(
        ChirpConfig(**manifest["chirp_config"]), ArrayConfig(**manifest["array_config"])
    )
    detections: list[Detection] = []
    tracks: list[TrackState] = []
    started = time.monotonic()
    for result in pipeline.run(ReplaySource(session_dir, realtime=realtime).frames()):
        detections += result.detections
        tracks += result.tracks
        if on_frame is not None:
            on_frame(result)
    elapsed = time.monotonic() - started
    write_rows(session_dir / DETECTIONS_FILE, detections, Detection)
    write_rows(session_dir / TRACKS_FILE, tracks, TrackState)
    return {
        "session_id": manifest["session_id"],
        "frames": manifest["n_frames"],
        "detections": len(detections),
        "confirmed_tracks": len({t.track_id for t in tracks if t.confirmed}),
        "seconds": round(elapsed, 2),
    }
