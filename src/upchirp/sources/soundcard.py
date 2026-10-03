"""Sound card source: coffee-can radar recordings (step 10, Abdullah's weeks 6 to 11).

Assumes the classic MIT coffee-can wiring: the left audio channel carries the beat
signal from the mixer, the right channel a sync square wave that is high while the
VCO sweeps up. Each up-sweep becomes one chirp; `chirps_per_frame` chirps make a
Frame with one receive channel, so the rest of the pipeline runs unchanged.

The beat signal is real, so it is turned into its analytic signal (Hilbert
transform): positive beat frequencies, and so ranges, fill the lower half of the
range bins. With one channel there is no angle; detections sit on boresight.

The sweep settings (start frequency, bandwidth, sweep time) belong to the hardware.
The defaults are placeholders until Abdullah measures his VCO sweep.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.io import wavfile
from scipy.signal import hilbert

from upchirp.config import ChirpConfig
from upchirp.frame import Frame


@dataclass(frozen=True)
class CoffeeCanConfig:
    f_start_hz: float = 2.40e9
    bandwidth_hz: float = 80e6      # placeholder: set from the measured VCO sweep
    sweep_s: float = 0.020          # up-sweep time
    chirps_per_frame: int = 16
    usable_fraction: float = 0.95   # drop the end of each sweep, where the VCO settles

    def config_id(self, sample_rate_hz: float) -> str:
        """Every setting, exactly, so the processor rebuilds the same chirp config."""
        return (f"{ID_PREFIX}:f={self.f_start_hz!r},b={self.bandwidth_hz!r},s={self.sweep_s!r},"
                f"c={self.chirps_per_frame},u={self.usable_fraction!r},r={sample_rate_hz!r}")

    def chirp_config(self, sample_rate_hz: float) -> ChirpConfig:
        n_samples = int(self.sweep_s * sample_rate_hz * self.usable_fraction)
        return ChirpConfig(
            id=self.config_id(sample_rate_hz),
            f_start_hz=self.f_start_hz,
            bandwidth_hz=self.bandwidth_hz,
            chirp_duration_s=self.sweep_s,
            chirp_interval_s=2 * self.sweep_s,  # up sweep, then down sweep
            n_chirps=self.chirps_per_frame,
            n_samples=n_samples,
            sample_rate_hz=sample_rate_hz,
            max_range_bin=n_samples // 2,       # real beat signal: one-sided spectrum
        )


ID_PREFIX = "coffee-can-v1"


def config_from_id(config_id: str) -> tuple[CoffeeCanConfig, float]:
    """(config, sample rate) back from CoffeeCanConfig.config_id, exactly."""
    parts = dict(p.split("=", 1) for p in config_id.removeprefix(ID_PREFIX + ":").split(","))
    cfg = CoffeeCanConfig(f_start_hz=float(parts["f"]), bandwidth_hz=float(parts["b"]),
                          sweep_s=float(parts["s"]), chirps_per_frame=int(parts["c"]),
                          usable_fraction=float(parts["u"]))
    return cfg, float(parts["r"])


def read_wav(path: Path) -> tuple[float, npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """(sample rate, beat signal, sync signal), scaled to -1..1."""
    fs, data = wavfile.read(path)
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("expected a stereo recording: beat on the left, sync on the right")
    scale = float(np.iinfo(data.dtype).max) if np.issubdtype(data.dtype, np.integer) else 1.0
    audio = data.astype(np.float64) / scale
    return float(fs), audio[:, 0], audio[:, 1]


def sweep_starts(sync: npt.NDArray[np.float64], min_len: int) -> list[int]:
    """Sample indexes where the sync signal rises and then stays high for min_len samples."""
    high = sync > (sync.max() + sync.min()) / 2
    rises = np.flatnonzero(high[1:] & ~high[:-1]) + 1
    return [int(r) for r in rises if r + min_len <= len(high) and high[r:r + min_len].all()]


class SoundcardSource:
    def __init__(self, path: Path, session_id: str, start_ns: int,
                 config: CoffeeCanConfig | None = None) -> None:
        self.path = path
        self.session_id = session_id
        self.start_ns = start_ns
        self.config = config or CoffeeCanConfig()
        self.fs, self.beat, self.sync = read_wav(path)
        self.chirp = self.config.chirp_config(self.fs)

    def frames(self) -> Iterator[Frame]:
        n = self.chirp.n_samples
        starts = sweep_starts(self.sync, n)
        per_frame = self.config.chirps_per_frame
        for k in range(len(starts) // per_frame):
            group = starts[k * per_frame:(k + 1) * per_frame]
            chirps = np.stack([self.beat[s:s + n] for s in group])
            chirps = chirps - chirps.mean(axis=1, keepdims=True)
            analytic: npt.NDArray[Any] = hilbert(chirps, axis=1)
            yield Frame.from_cube(
                analytic[None, :, :],
                source="soundcard",
                session_id=self.session_id,
                frame_index=k,
                timestamp_ns=self.start_ns + round(group[0] / self.fs * 1e9),
                chirp_config_id=self.chirp.id,
                stage="raw",
                meta={"file": self.path.name},
            )
