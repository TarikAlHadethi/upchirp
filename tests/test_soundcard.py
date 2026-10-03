"""Coffee-can sound card source, tested on synthetic recordings."""

from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile
from typer.testing import CliRunner

from upchirp.cli import app
from upchirp.config import ArrayConfig
from upchirp.dsp.detect import Detector
from upchirp.recording import read_manifest, resolve_session
from upchirp.replay import process_session
from upchirp.sim.coffeecan import CanTarget, write_recording
from upchirp.sources.soundcard import SoundcardSource, sweep_starts


def test_sweep_starts_finds_rising_edges() -> None:
    sync = np.tile(np.r_[np.ones(10), -np.ones(10)], 5)
    assert sweep_starts(sync, 8) == [20, 40, 60, 80]  # the first sweep has no rising edge


def test_reflectors_at_the_right_range(tmp_path: Path) -> None:
    path = tmp_path / "can.wav"
    write_recording(path, [CanTarget(15.0), CanTarget(32.0, amplitude=0.08)], seconds=2.0)
    src = SoundcardSource(path, "can", 0)
    frames = list(src.frames())
    assert len(frames) == 3 and frames[0].n_rx == 1 and frames[0].source == "soundcard"
    assert frames[1].timestamp_ns > frames[0].timestamp_ns
    det = Detector(src.chirp, ArrayConfig(n_rx=1), clutter_map=None)
    strongest = sorted(det.detect(frames[0]), key=lambda d: -d.snr_db)[:2]
    assert sorted(round(d.range_m) for d in strongest) == [15, 32]
    assert all(d.azimuth_deg == 0.0 for d in strongest)


def test_mono_recording_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mono.wav"
    wavfile.write(path, 48_000, np.zeros(4800, dtype=np.int16))
    with pytest.raises(ValueError, match="stereo"):
        SoundcardSource(path, "x", 0)


def test_import_wav_then_replay(tmp_path: Path) -> None:
    path = tmp_path / "walk.wav"
    write_recording(path, [CanTarget(10.0, velocity_mps=0.5)], seconds=4.0)
    result = CliRunner().invoke(app, ["import-wav", str(path), "--data-dir", str(tmp_path),
                                      "--notes", "test walk"])
    assert result.exit_code == 0, result.output
    session_dir = resolve_session(tmp_path, "latest")
    assert read_manifest(session_dir)["source"] == "soundcard"
    summary = process_session(session_dir)
    assert summary["frames"] == 6
