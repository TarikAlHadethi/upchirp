"""Ordered-statistic CFAR on a range-Doppler power map.

The noise estimate for each cell is the k-th smallest of the training cells
around it (guard cells excluded). Unlike cell-averaging CFAR, one strong
neighbour cannot raise the estimate much, so a weak target next to a strong
one (the drone next to the car) is not masked.

The Doppler axis wraps around; the range axis is mirrored at its ends.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage, optimize


@dataclass(frozen=True)
class CfarConfig:
    guard: tuple[int, int] = (2, 2)  # cells each side: (doppler, range)
    train: tuple[int, int] = (4, 8)
    rank: float = 0.75  # which ordered training cell is the noise estimate
    pfa: float = 1e-4  # design false alarm rate per cell (conservative, see tests)
    peak_size: tuple[int, int] = (3, 3)  # only local maxima in this window are reported
    min_range_bin: int = 2  # skip the DC and leakage bins


def _pad(p: npt.NDArray[Any], d: int, r: int) -> npt.NDArray[Any]:
    p = np.pad(p, ((d, d), (0, 0)), mode="wrap")
    return np.pad(p, ((0, 0), (r, r)), mode="reflect")


def _crop(p: npt.NDArray[Any], d: int, r: int) -> npt.NDArray[Any]:
    return p[d : p.shape[0] - d, r : p.shape[1] - r]


def _footprint(cfg: CfarConfig) -> npt.NDArray[np.bool_]:
    (gd, gr), (td, tr) = cfg.guard, cfg.train
    fp = np.ones((2 * (gd + td) + 1, 2 * (gr + tr) + 1), dtype=bool)
    fp[td : td + 2 * gd + 1, tr : tr + 2 * gr + 1] = False
    return fp


@lru_cache(maxsize=32)
def os_cfar_alpha(n: int, k: int, pfa: float) -> float:
    """Threshold factor for OS-CFAR in exponential noise.

    Solves Pfa = prod_{i=0}^{k-1} (n - i) / (n - i + alpha).
    """
    i = np.arange(k)

    def f(a: float) -> float:
        return float(np.sum(np.log((n - i) / (n - i + a))) - np.log(pfa))

    return float(optimize.brentq(f, 1e-9, 1e12))


def threshold(power: npt.NDArray[np.floating[Any]], cfg: CfarConfig) -> npt.NDArray[np.float64]:
    """Detection threshold for every cell of a [n_doppler, n_range] power map."""
    fp = _footprint(cfg)
    n = int(fp.sum())
    k = max(1, int(cfg.rank * n))
    d, r = fp.shape[0] // 2, fp.shape[1] // 2
    noise = ndimage.rank_filter(_pad(power, d, r), rank=k - 1, footprint=fp, mode="constant")
    out: npt.NDArray[np.float64] = os_cfar_alpha(n, k, cfg.pfa) * _crop(noise, d, r)
    return out


def detect_peaks(
    power: npt.NDArray[np.floating[Any]], cfg: CfarConfig,
    floor: npt.NDArray[np.floating[Any]] | None = None,
) -> list[tuple[int, int]]:
    """(doppler_bin, range_bin) of cells over threshold that are local maxima.

    `floor` is an extra per-cell minimum, such as a clutter power map's."""
    limit = threshold(power, cfg)
    if floor is not None:
        limit = np.maximum(limit, floor)
    above = power > limit
    d, r = cfg.peak_size[0] // 2, cfg.peak_size[1] // 2
    local_max = _crop(
        ndimage.maximum_filter(_pad(power, d, r), size=cfg.peak_size, mode="constant"), d, r
    )
    peaks = above & (power == local_max)
    peaks[:, : cfg.min_range_bin] = False
    return [(int(a), int(b)) for a, b in np.argwhere(peaks)]
