"""Clutter map: learn the still background and subtract it (a fixed-site radar's usual method).

Walls, posts and the ground give the same complex echo frame after frame, so their
mean over a frame's chirps is learned per receive channel and range bin, and
subtracted from every chirp before the Doppler FFT. Unlike subtracting each frame's
own mean, this keeps targets that move across the radar's view, or hover.

The map is the running mean of the first `warmup_frames` (the scene should be empty
then; no detections are reported while it learns), then an exponential average with
time constant `time_constant_s`, so the background can change slowly. Anything that
stays still for about that long fades into the background, as on a real radar.

It also learns the mean residual power of every range-Doppler cell (a clutter power
map). Cells that are busy even when no target is there, such as trees with moving
leaves, then need an echo `power_margin_db` above their usual level to count.
Range bins and cells with a detection nearby are not learned from, so targets (such
as a car crossing the view, which looks still for a moment) do not leave ghosts.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class ClutterMapConfig:
    warmup_frames: int = 20
    time_constant_s: float = 60.0
    frame_period_s: float = 0.1
    power_margin_db: float = 10.0


@dataclass
class ClutterMap:
    cfg: ClutterMapConfig = field(default_factory=ClutterMapConfig)
    background: npt.NDArray[np.complex128] | None = None
    power: npt.NDArray[np.float64] | None = None
    frames_seen: int = 0

    @property
    def ready(self) -> bool:
        return self.frames_seen >= self.cfg.warmup_frames

    _frame_mean: npt.NDArray[np.complex128] | None = None

    def apply(self, range_cube: npt.NDArray[Any]) -> npt.NDArray[np.complex128]:
        """Return the frame with the background removed. Call learn() after detecting.

        range_cube is [n_rx, n_chirps, n_range] after the range FFT."""
        self.frames_seen += 1
        self._frame_mean = range_cube.mean(axis=1, keepdims=True).astype(np.complex128)
        if self.background is None:
            self.background = self._frame_mean.copy()
        out: npt.NDArray[np.complex128] = range_cube - self.background
        return out

    def learn(self, power: npt.NDArray[Any], busy: npt.NDArray[np.bool_]) -> None:
        """Fold this frame into both maps, skipping cells (and their range bins) marked busy.

        busy is [n_doppler, n_range], True near this frame's detections."""
        assert self._frame_mean is not None and self.background is not None, "call apply()"
        busy_range = busy.any(axis=0)  # [n_range]
        alpha = self._alpha()
        step = np.where(busy_range, 0.0, alpha)[None, None, :]
        self.background += step * (self._frame_mean - self.background)
        self.learn_power(power, busy)

    def _alpha(self) -> float:
        if self.frames_seen <= self.cfg.warmup_frames:
            return 1.0 / self.frames_seen
        return self.cfg.frame_period_s / self.cfg.time_constant_s

    def floor(self) -> npt.NDArray[np.float64] | None:
        """Minimum power to count as a detection in each cell, once the map is ready."""
        if not self.ready or self.power is None:
            return None
        out: npt.NDArray[np.float64] = self.power * 10 ** (self.cfg.power_margin_db / 10)
        return out

    def learn_power(self, power: npt.NDArray[Any], busy: npt.NDArray[np.bool_]) -> None:
        """Fold this frame's residual power into the map, skipping cells marked busy."""
        if self.power is None:
            self.power = power.astype(np.float64)
            return
        alpha = self._alpha()
        update = np.where(busy, 0.0, alpha)
        self.power += update * (power - self.power)
