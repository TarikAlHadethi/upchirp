"""Test vectors for Abdullah's fixed-point range FFT (handoff after step 2).

Input samples come from the simulator and are quantized like an ADC would
(`adc_bits`, two's complement). The window is quantized to Q1.(window_bits-1).
The expected output is the float64 range FFT of exactly those quantized inputs
and window, so the comparison measures only the FPGA's arithmetic.

SQNR compares the FPGA output with the expected output after fitting one complex
gain, because a fixed-point FFT scales its output by a power of two (and may
rotate it) depending on its scaling schedule.

Files written (per frame, receive channel 0):
    input_i.mem, input_q.mem   one hex word per line, chirp by chirp ($readmemh)
    window.mem                 one hex word per line
    input_iq.npy               int16 [n_chirps, n_samples, 2]
    window.npy                 int16 [n_samples]
    expected_fft.npy           complex128 [n_chirps, n_samples], natural order
    vectors.json               the settings above, so files explain themselves
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class VectorConfig:
    adc_bits: int = 12
    window_bits: int = 16
    n_samples: int = 256
    complex_input: bool = True  # False: real ADC samples only (I), Q all zero
    bit_reversed_output: bool = False


def quantize(x: npt.NDArray[np.floating[Any]], bits: int) -> npt.NDArray[np.int16]:
    """Round to signed `bits`-bit integers, full scale = 1.0 (saturating)."""
    top = 2 ** (bits - 1) - 1
    q = np.clip(np.round(x * top), -top - 1, top)
    out: npt.NDArray[np.int16] = q.astype(np.int16)
    return out


def make_vectors(cube: npt.NDArray[np.complexfloating[Any, Any]], cfg: VectorConfig
                 ) -> dict[str, npt.NDArray[Any]]:
    """cube: one receive channel, [n_chirps, n_samples] complex. Scaled to the ADC range."""
    peak = float(np.max(np.abs(np.r_[cube.real.ravel(), cube.imag.ravel()]))) or 1.0
    scaled = cube / peak * 0.9  # leave headroom below full scale
    i = quantize(scaled.real, cfg.adc_bits)
    q = quantize(scaled.imag, cfg.adc_bits) if cfg.complex_input else np.zeros_like(i)
    window = quantize(np.hanning(cfg.n_samples), cfg.window_bits)
    x = (i.astype(np.float64) + 1j * q.astype(np.float64)) * window.astype(np.float64)
    expected = np.fft.fft(x, axis=-1)
    if cfg.bit_reversed_output:
        bits = int(np.log2(cfg.n_samples))
        order = [int(f"{k:0{bits}b}"[::-1], 2) for k in range(cfg.n_samples)]
        expected = expected[:, order]
    return {"input_iq": np.stack([i, q], axis=-1), "window": window, "expected_fft": expected}


def sqnr_db(expected: npt.NDArray[np.complexfloating[Any, Any]],
            measured: npt.NDArray[np.complexfloating[Any, Any]]) -> float:
    """Signal to quantization noise ratio of `measured` against `expected`, in dB.

    Fits one complex gain first, so a power-of-two output scale does not count as error."""
    e = expected.ravel()
    m = measured.ravel().astype(np.complex128)
    gain = np.vdot(m, e) / np.vdot(m, m)
    noise = e - gain * m
    return float(10 * np.log10(np.sum(np.abs(e) ** 2) / np.sum(np.abs(noise) ** 2)))


def write(out_dir: Path, vectors: dict[str, npt.NDArray[Any]], cfg: VectorConfig,
          source: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    width = 4  # hex digits per 16-bit word
    iq = vectors["input_iq"]
    for name, data in (("input_i", iq[..., 0]), ("input_q", iq[..., 1]),
                       ("window", vectors["window"])):
        words = (data.ravel().astype(np.int32) & 0xFFFF)
        (out_dir / f"{name}.mem").write_text("\n".join(f"{w:0{width}x}" for w in words) + "\n")
    np.save(out_dir / "input_iq.npy", iq)
    np.save(out_dir / "window.npy", vectors["window"])
    np.save(out_dir / "expected_fft.npy", vectors["expected_fft"])
    (out_dir / "vectors.json").write_text(json.dumps(
        {**asdict(cfg), "n_chirps": int(iq.shape[0]), "source": source,
         "word_format": "16-bit two's complement, hex, one per line, chirp by chirp"}, indent=2))
