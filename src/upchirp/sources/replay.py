"""Replay a recorded session. Frames come out with source='replay'.

The original source stays in the session manifest, not in the frames.
"""

import time
from collections.abc import Iterator
from pathlib import Path

from upchirp.frame import Frame
from upchirp.recording import FRAMES_FILE, read_frames


class ReplaySource:
    def __init__(self, session_dir: Path, realtime: bool = False) -> None:
        self.session_dir = session_dir
        self.realtime = realtime

    def frames(self) -> Iterator[Frame]:
        wall_start = time.monotonic()
        first_ns: int | None = None
        for frame in read_frames(self.session_dir / FRAMES_FILE):
            if self.realtime:
                first_ns = frame.timestamp_ns if first_ns is None else first_ns
                due = (frame.timestamp_ns - first_ns) / 1e9
                delay = due - (time.monotonic() - wall_start)
                if delay > 0:
                    time.sleep(delay)
            yield frame.model_copy(update={"source": "replay"})
