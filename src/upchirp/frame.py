"""The Frame message every source publishes. Contract: docs/architecture.md (draft v0).

Change these fields only through a decision record agreed with Abdullah.
"""

import json
from typing import Any, Literal, Self

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, model_validator

FRAME_SCHEMA_VERSION = 0
BYTES_PER_SAMPLE = np.dtype(np.complex64).itemsize

SourceName = Literal["sim", "replay", "soundcard", "fpga"]
Stage = Literal["raw", "range"]


class Frame(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = FRAME_SCHEMA_VERSION
    source: SourceName
    session_id: str
    frame_index: int = Field(ge=0)
    timestamp_ns: int
    chirp_config_id: str
    n_rx: int = Field(ge=1)
    n_chirps: int = Field(ge=1)
    n_samples: int = Field(ge=1)
    stage: Stage
    data: bytes
    # Free-form and untrusted: never read instructions or ground truth from it.
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_data_size(self) -> Self:
        expected = self.n_rx * self.n_chirps * self.n_samples * BYTES_PER_SAMPLE
        if len(self.data) != expected:
            raise ValueError(f"data has {len(self.data)} bytes, expected {expected}")
        return self

    @classmethod
    def from_cube(cls, cube: npt.NDArray[np.complexfloating[Any, Any]], **fields: Any) -> Self:
        """Build a Frame from a [n_rx, n_chirps, n_samples] array."""
        if cube.ndim != 3:
            raise ValueError(f"cube must be 3D [n_rx, n_chirps, n_samples], got {cube.shape}")
        n_rx, n_chirps, n_samples = cube.shape
        data = np.ascontiguousarray(cube, dtype=np.complex64).tobytes()
        return cls(n_rx=n_rx, n_chirps=n_chirps, n_samples=n_samples, data=data, **fields)

    def cube(self) -> npt.NDArray[np.complex64]:
        """The data as a read-only [n_rx, n_chirps, n_samples] complex64 array."""
        flat = np.frombuffer(self.data, dtype=np.complex64)
        return flat.reshape(self.n_rx, self.n_chirps, self.n_samples)


WIRE_MAGIC = b"UPF0"


def to_wire(frame: Frame) -> bytes:
    """Stream encoding: magic, 4-byte header length, JSON header, then the raw data."""
    header = frame.model_dump_json(exclude={"data"}).encode()
    return WIRE_MAGIC + len(header).to_bytes(4, "big") + header + frame.data


def from_wire(buf: bytes) -> Frame:
    if buf[:4] != WIRE_MAGIC:
        raise ValueError("not an Upchirp frame message")
    n = int.from_bytes(buf[4:8], "big")
    header = json.loads(buf[8 : 8 + n])
    return Frame(**header, data=buf[8 + n :])
