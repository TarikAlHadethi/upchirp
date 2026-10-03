"""Frame sources. Every adapter yields the same Frame message (decision 0003)."""

from collections.abc import Iterator
from typing import Protocol

from upchirp.frame import Frame


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]: ...
