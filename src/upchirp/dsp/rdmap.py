"""Range-Doppler map: the reference FFTs that step 2 builds CFAR and tracking on."""

from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp.config import ChirpConfig


def range_fft(cube: npt.NDArray[np.complexfloating[Any, Any]]) -> npt.NDArray[np.complex128]:
    """Hann window and FFT over the samples of each chirp. This is the FPGA's job on hardware.

    It is also the reference Abdullah's fixed-point FFT is compared against (SQNR).
    """
    n_samples = cube.shape[-1]
    out: npt.NDArray[np.complex128] = np.fft.fft(cube * np.hanning(n_samples), axis=-1).astype(
        np.complex128, copy=False
    )
    return out


def doppler_fft(range_cube: npt.NDArray[Any]) -> npt.NDArray[np.complex128]:
    """Hann-windowed Doppler FFT over chirps, zero velocity at the centre."""
    n_chirps = range_cube.shape[1]
    dop = np.fft.fft(range_cube * np.hanning(n_chirps)[:, None], axis=1)
    out: npt.NDArray[np.complex128] = np.fft.fftshift(dop, axes=1)
    return out


def range_doppler(
    cube: npt.NDArray[np.complexfloating[Any, Any]], stage: str = "raw",
    remove_static: bool = False,
) -> npt.NDArray[np.complex128]:
    """Range FFT (unless the frame is already at stage 'range'), then Hann-windowed Doppler FFT.

    Input is a [n_rx, n_chirps, n_samples] cube. Output has the same shape,
    with zero velocity moved to the centre of the Doppler axis.

    remove_static subtracts each range bin's mean over the frame's chirps first, the
    simplest static clutter removal. It also erases targets moving across the view
    and leaves ghosts of slow targets at zero speed, so the detector uses a clutter
    map instead (dsp/clutter.py); this stays for comparison.
    """
    rng: npt.NDArray[Any] = range_fft(cube) if stage == "raw" else cube
    if remove_static:
        rng = rng - rng.mean(axis=1, keepdims=True)
    n_chirps = cube.shape[1]
    dop = np.fft.fft(rng * np.hanning(n_chirps)[:, None], axis=1)
    out: npt.NDArray[np.complex128] = np.fft.fftshift(dop, axes=1)
    return out


def range_of_bin(chirp: ChirpConfig, range_bin: int) -> float:
    return range_bin * chirp.range_bin_m


def velocity_of_bin(chirp: ChirpConfig, doppler_bin: int) -> float:
    return (doppler_bin - chirp.n_chirps // 2) * chirp.velocity_bin_mps


def range_bin_of(chirp: ChirpConfig, range_m: float) -> int:
    return round(range_m / chirp.range_bin_m)


def doppler_bin_of(chirp: ChirpConfig, velocity_mps: float) -> int:
    return round(velocity_mps / chirp.velocity_bin_mps) + chirp.n_chirps // 2


def azimuth_deg(
    rd: npt.NDArray[np.complexfloating[Any, Any]],
    doppler_bin: int,
    range_bin: int,
    spacing_wavelengths: float = 0.5,
) -> float:
    """Angle from the phase step between the first two receive channels (0 with one)."""
    if rd.shape[0] < 2:
        return 0.0
    cell = rd[:, doppler_bin, range_bin]
    dphi = float(np.angle(cell[1] * np.conj(cell[0])))
    u = np.clip(dphi / (2 * np.pi * spacing_wavelengths), -1.0, 1.0)
    return float(np.degrees(np.arcsin(u)))
