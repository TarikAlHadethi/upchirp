"""Classifier data handling and ONNX labelling (training itself runs in ml/train.py)."""

from pathlib import Path

import numpy as np
import pytest

from upchirp.classify.patches import (
    CLASSES,
    RADDAR_SHAPE,
    convert_to_grid,
    cut_patch,
    normalise,
    our_doppler_cells,
)
from upchirp.config import ChirpConfig


def _raddar_like(n: int = 4, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    db = rng.normal(-120, 3, (n,) + RADDAR_SHAPE)
    db[:, 5, 30] = -60  # target in the centre
    return db.astype(np.float32)


def test_conversion_keeps_power_and_shape() -> None:
    chirp = ChirpConfig()
    db = _raddar_like()
    out = convert_to_grid(db, chirp)
    assert out.shape == (4, 11, our_doppler_cells(chirp)) == (4, 11, 15)
    p_in = (10 ** (db.astype(np.float64) / 10)).sum(axis=(1, 2))
    p_out = (10 ** (out.astype(np.float64) / 10)).sum(axis=(1, 2))
    assert p_out == pytest.approx(p_in, rel=0.1)
    assert all(np.unravel_index(o.argmax(), o.shape) == (5, 7) for o in out)  # still centred


def test_normalise_is_relative_to_peak() -> None:
    n = normalise(np.array([[[-60.0, -80.0, -200.0]]]))
    assert n.max() == 1.0 and n.min() == 0.0 and n[0, 0, 1] == pytest.approx(0.5)


def test_cut_patch_centres_and_wraps() -> None:
    power = np.ones((64, 256))
    power[0, 100] = 1e6  # Doppler bin 0: the patch must wrap around the Doppler axis
    patch = cut_patch(power, 0, 100, 15)
    assert patch.shape == (11, 15) and np.unravel_index(patch.argmax(), patch.shape) == (5, 7)


torch = pytest.importorskip("torch")
pytest.importorskip("onnxruntime")


def test_split_never_shares_a_recording() -> None:
    from upchirp.classify.model import split_by_recording

    rec = np.array([f"{c}/{i}" for c in "abc" for i in range(10) for _ in range(5)])
    y = np.array([ord(r[0]) - ord("a") for r in rec])
    s = split_by_recording(y, rec, seed=0)
    assert not set(rec[s.train]) & set(rec[s.test])
    assert not set(rec[s.val]) & set(rec[s.test])
    assert set(y[s.test]) == {0, 1, 2}  # every class is tested


def test_onnx_labeler(tmp_path: Path) -> None:
    import json

    from upchirp.classify.model import PatchCNN, to_onnx
    from upchirp.classify.onnx_labeler import OnnxLabeler
    from upchirp.dsp.detect import Detection

    torch.manual_seed(0)
    to_onnx(PatchCNN(11, 15), 11, 15, tmp_path / "m.onnx")
    (tmp_path / "m.json").write_text(json.dumps({"classes": list(CLASSES), "doppler_cells": 15}))
    lab = OnnxLabeler(model_path=tmp_path / "m.onnx", min_detections=3)
    probs = lab.classify(np.zeros((2, 11, 15), np.float32))
    assert probs.shape == (2, 3) and np.allclose(probs.sum(axis=1), 1)

    det = Detection("s", 0, 0, 20.0, 0.0, 0.0, 30.0, range_bin=20, doppler_bin=32)
    power = np.ones((64, 256))
    for _ in range(2):
        lab.observe_frame(power, {7: det})
    assert lab.label(7)[0] == "unknown"
    lab.observe_frame(power, {7: det})
    assert lab.label(7)[0] in CLASSES
