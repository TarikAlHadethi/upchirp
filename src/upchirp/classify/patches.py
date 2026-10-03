"""Range-Doppler patches for the classifier: RAD-DAR loading, conversion to our grid, and
cutting patches from our own power maps.

RAD-DAR (Roldan et al. 2020, Table 3): 8.75 GHz FMCW, 0.878 m per range cell,
0.34 km/h (0.0944 m/s) per Doppler cell. Each sample is an 11 x 61 matrix of power
in dBm, cut around a detection: about 9.7 m and +-10 km/h centred on the target.

Our radar: about 1.0 m per range cell and 0.41 m/s per Doppler cell. Converting in
metres and metres per second (not in Hz) makes the carrier frequency irrelevant.
The Doppler axis is rebinned by integrating power over our wider cells, which is
what our coarser Doppler FFT would have measured; the range axis is interpolated.

Every patch is normalised the same way: dB relative to its own peak, clipped at
-FLOOR_DB. Absolute levels differ between radars (power, gain, range), so only the
shape is kept.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp.config import ChirpConfig

RADDAR_RANGE_M = 0.878
RADDAR_VELOCITY_MPS = 0.34 / 3.6
RADDAR_SHAPE = (11, 61)
CLASSES = ("person", "car", "drone_like")
RADDAR_FOLDERS = {"People": "person", "Cars": "car", "Drones": "drone_like"}
FLOOR_DB = 40.0
PATCH_RANGE_CELLS = 11

Array = npt.NDArray[np.float32]


@dataclass(frozen=True)
class Sample:
    patch: Array          # dB, as recorded
    label: int            # index into CLASSES
    recording: str        # e.g. "Cars/13-13": samples from one recording are near-copies


def iter_raddar(root: Path) -> Iterator[Sample]:
    for folder, label in RADDAR_FOLDERS.items():
        for path in sorted((root / folder).glob("*/*.csv")):
            patch = np.loadtxt(path, delimiter=",", dtype=np.float32)
            if patch.shape != RADDAR_SHAPE:
                continue
            yield Sample(patch, CLASSES.index(label), f"{folder}/{path.parent.name}")


def load_raddar(root: Path, cache: Path | None = None
                ) -> tuple[Array, npt.NDArray[np.int64], npt.NDArray[np.str_]]:
    """(patches [n, 11, 61] in dB, labels [n], recording ids [n]). Cached as .npz."""
    if cache is not None and cache.exists():
        z = np.load(cache)
        return z["x"], z["y"], z["rec"]
    samples = list(iter_raddar(root))
    x = np.stack([s.patch for s in samples])
    y = np.array([s.label for s in samples], dtype=np.int64)
    rec = np.array([s.recording for s in samples])
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, x=x, y=y, rec=rec)
    return x, y, rec


def normalise(db: npt.NDArray[Any]) -> Array:
    """dB relative to the patch's own peak, clipped to [-FLOOR_DB, 0], scaled to [0, 1]."""
    rel = db - db.max(axis=(-2, -1), keepdims=True)
    out: Array = ((np.clip(rel, -FLOOR_DB, 0) + FLOOR_DB) / FLOOR_DB).astype(np.float32)
    return out


def our_doppler_cells(chirp: ChirpConfig) -> int:
    """Doppler cells our radar has across RAD-DAR's +-10 km/h window (odd, target centred)."""
    span = RADDAR_SHAPE[1] * RADDAR_VELOCITY_MPS
    n = int(round(span / chirp.velocity_bin_mps))
    return n if n % 2 else n + 1


def convert_to_grid(db: npt.NDArray[Any], chirp: ChirpConfig) -> Array:
    """RAD-DAR patches [n, 11, 61] dB -> our grid [n, 11, D] dB (D from our Doppler cell)."""
    power = 10 ** (db.astype(np.float64) / 10)
    n_d = our_doppler_cells(chirp)
    # Doppler: integrate power over our wider cells (cumulative sum, sampled at our edges)
    src_edges = (np.arange(RADDAR_SHAPE[1] + 1) - RADDAR_SHAPE[1] / 2) * RADDAR_VELOCITY_MPS
    dst_edges = (np.arange(n_d + 1) - n_d / 2) * chirp.velocity_bin_mps
    cum = np.concatenate([np.zeros(power.shape[:-1] + (1,)), np.cumsum(power, axis=-1)], -1)
    cum_at = np.stack([np.interp(dst_edges, src_edges, c) for c in cum.reshape(-1, cum.shape[-1])])
    binned = np.diff(cum_at, axis=-1).reshape(power.shape[:-1] + (n_d,))
    binned = np.maximum(binned, 1e-30)
    # Range: interpolate from RAD-DAR's cell centres to ours, both centred on the target
    src_r = (np.arange(RADDAR_SHAPE[0]) - RADDAR_SHAPE[0] // 2) * RADDAR_RANGE_M
    dst_r = (np.arange(PATCH_RANGE_CELLS) - PATCH_RANGE_CELLS // 2) * chirp.range_bin_m
    swapped = np.moveaxis(binned, -2, -1)  # [n, D, 11]
    flat = swapped.reshape(-1, RADDAR_SHAPE[0])
    resampled = np.stack([np.interp(dst_r, src_r, row) for row in flat])
    out = np.moveaxis(resampled.reshape(swapped.shape[:-1] + (PATCH_RANGE_CELLS,)), -1, -2)
    db_out: Array = (10 * np.log10(out)).astype(np.float32)
    return db_out


def cut_patch(power: npt.NDArray[Any], doppler_bin: int, range_bin: int, n_doppler: int
              ) -> Array:
    """Patch from one of our power maps [n_doppler_total, n_range], centred on a detection,
    11 range cells by n_doppler Doppler cells, in dB. Doppler wraps; range edges repeat."""
    total_d, total_r = power.shape
    d_idx = (np.arange(n_doppler) - n_doppler // 2 + doppler_bin) % total_d
    r_idx = np.clip(np.arange(PATCH_RANGE_CELLS) - PATCH_RANGE_CELLS // 2 + range_bin,
                    0, total_r - 1)
    patch = power[np.ix_(d_idx, r_idx)].T  # [range, doppler], like RAD-DAR
    db: Array = (10 * np.log10(np.maximum(patch, 1e-30))).astype(np.float32)
    return db
