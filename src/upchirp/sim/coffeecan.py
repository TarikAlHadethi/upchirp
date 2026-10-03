"""Write synthetic coffee-can recordings (stereo WAV) to test the sound card source
before real ones exist. Left: beat signal of point targets during each up-sweep.
Right: the sync square wave, high during the up-sweep.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from upchirp.config import SPEED_OF_LIGHT_MPS
from upchirp.sources.soundcard import CoffeeCanConfig


@dataclass(frozen=True)
class CanTarget:
    range_m: float
    velocity_mps: float = 0.0
    amplitude: float = 0.2


def write_recording(path: Path, targets: list[CanTarget], seconds: float = 6.0,
                    fs: int = 48_000, config: CoffeeCanConfig | None = None,
                    noise: float = 0.01, seed: int = 0) -> None:
    cfg = config or CoffeeCanConfig()
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * fs)) / fs
    period = 2 * cfg.sweep_s
    phase_in_period = np.mod(t, period)
    up = phase_in_period < cfg.sweep_s
    slope = cfg.bandwidth_hz / cfg.sweep_s
    beat = rng.normal(0, noise, t.size)
    for tgt in targets:
        r = tgt.range_m + tgt.velocity_mps * t
        tau = 2 * r / SPEED_OF_LIGHT_MPS
        tone = np.cos(2 * np.pi * (slope * tau * phase_in_period + cfg.f_start_hz * tau))
        beat += np.where(up, tgt.amplitude * tone, 0.0)
    sync = np.where(up, 0.5, -0.5)
    stereo = np.stack([beat, sync], axis=1)
    wavfile.write(path, fs, (np.clip(stereo, -1, 1) * 32767).astype(np.int16))
