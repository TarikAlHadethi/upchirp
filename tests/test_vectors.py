from pathlib import Path

import numpy as np
import pytest

from upchirp.dsp.vectors import VectorConfig, make_vectors, quantize, sqnr_db, write


def _cube() -> np.ndarray:
    rng = np.random.default_rng(0)
    n = np.arange(256)
    tone = np.exp(2j * np.pi * 37.3 * n / 256)
    noise = rng.normal(size=(4, 256)) + 1j * rng.normal(size=(4, 256))
    return np.tile(tone, (4, 1)) + 0.01 * noise


def test_quantize_saturates() -> None:
    q = quantize(np.array([-2.0, -1.0, 0.0, 1.0, 2.0]), 12)
    assert list(q) == [-2048, -2047, 0, 2047, 2047]


def test_sqnr_ignores_scale_and_sees_noise() -> None:
    v = make_vectors(_cube(), VectorConfig())
    exp = v["expected_fft"]
    assert sqnr_db(exp, exp / 512) > 250  # a pure power-of-two scale is not an error
    rng = np.random.default_rng(1)
    rms = np.sqrt(np.mean(np.abs(exp) ** 2))
    noise = (rng.normal(size=exp.shape) + 1j * rng.normal(size=exp.shape)) / np.sqrt(2)
    assert sqnr_db(exp, exp + noise * rms * 1e-3) == pytest.approx(60, abs=0.5)  # 1e-3 = 60 dB


def test_quantized_fft_sqnr_grows_with_bits() -> None:
    v = make_vectors(_cube(), VectorConfig(adc_bits=16))
    exp = v["expected_fft"]
    coarse = np.round(exp / 2**8) * 2**8  # stand-in for an FPGA rounding its output
    fine = np.round(exp / 2**2) * 2**2
    assert sqnr_db(exp, fine) > sqnr_db(exp, coarse)


@pytest.mark.parametrize("bit_reversed", [False, True])
def test_files_written(tmp_path: Path, bit_reversed: bool) -> None:
    cfg = VectorConfig(bit_reversed_output=bit_reversed)
    v = make_vectors(_cube(), cfg)
    write(tmp_path, v, cfg, {"test": True})
    words = (tmp_path / "input_i.mem").read_text().split()
    assert len(words) == 4 * 256 and all(len(w) == 4 for w in words)
    assert np.load(tmp_path / "expected_fft.npy").shape == (4, 256)
    natural = make_vectors(_cube(), VectorConfig())["expected_fft"]
    if bit_reversed:
        order = [int(f"{k:08b}"[::-1], 2) for k in range(256)]
        np.testing.assert_array_equal(v["expected_fft"], natural[:, order])
    else:
        assert int(np.argmax(np.abs(natural[0]))) == 37
