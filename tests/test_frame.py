from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from upchirp.frame import Frame
from upchirp.recording import read_frames, write_frames

FIELDS = dict(
    source="sim", session_id="s1", frame_index=3, timestamp_ns=123,
    chirp_config_id="default-v0", stage="raw",
)


def _cube(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.normal(size=(2, 4, 8)) + 1j * rng.normal(size=(2, 4, 8))).astype(np.complex64)


def test_cube_round_trip() -> None:
    cube = _cube()
    frame = Frame.from_cube(cube, **FIELDS)
    assert (frame.n_rx, frame.n_chirps, frame.n_samples) == (2, 4, 8)
    np.testing.assert_array_equal(frame.cube(), cube)


def test_rejects_wrong_data_size() -> None:
    with pytest.raises(ValidationError, match="expected"):
        Frame(n_rx=2, n_chirps=4, n_samples=8, data=b"\x00" * 10, **FIELDS)


def test_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        Frame.from_cube(_cube(), **{**FIELDS, "source": "radio"})


def test_parquet_round_trip(tmp_path: Path) -> None:
    frames = [
        Frame.from_cube(_cube(i), **{**FIELDS, "frame_index": i, "meta": {"note": i}})
        for i in range(40)
    ]
    path = tmp_path / "frames.parquet"
    assert write_frames(path, frames) == 40
    assert list(read_frames(path)) == frames
