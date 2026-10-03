import numpy as np
import pytest

from upchirp.config import ChirpConfig
from upchirp.dsp.cfar import CfarConfig, detect_peaks, os_cfar_alpha, threshold
from upchirp.dsp.detect import Detector
from upchirp.dsp.rdmap import range_doppler
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import Scene, Target


def _frames(targets: tuple[Target, ...], n: int = 1, seed: int = 0) -> Simulator:
    scene = Scene(name="t", duration_s=0.1 * n, frame_period_s=0.1, targets=targets)
    return Simulator(scene, session_id="t", start_ns=0, seed=seed)


def test_alpha_matches_formula() -> None:
    n, k, pfa = 40, 30, 1e-3
    a = os_cfar_alpha(n, k, pfa)
    i = np.arange(k)
    assert np.prod((n - i) / (n - i + a)) == pytest.approx(pfa, rel=1e-6)


def test_noise_false_alarm_rate_below_design() -> None:
    cfg = CfarConfig(pfa=1e-3)
    above = cells = 0
    for frame, _ in _frames((), n=20, seed=7).run():
        power = (np.abs(range_doppler(frame.cube())) ** 2).sum(axis=0)
        mask = power > threshold(power, cfg)
        above += int(mask[:, cfg.min_range_bin :].sum())
        cells += mask[:, cfg.min_range_bin :].size
    assert above / cells <= cfg.pfa


def test_weak_target_beside_strong_one_is_not_masked() -> None:
    # Same Doppler bin, 6 range bins apart, about 45 dB weaker.
    strong = Target(id="car", label="car", position_m=(0.0, 30.0, 0.0), rcs_m2=10.0)
    weak = Target(id="drone", label="drone_like", position_m=(0.0, 36.0, 0.0), rcs_m2=0.001)
    frame, _ = next(_frames((strong, weak)).run())
    power = (np.abs(range_doppler(frame.cube())) ** 2).sum(axis=0)
    ranges = {r for _, r in detect_peaks(power, CfarConfig())}
    assert {30, 36} <= ranges


def test_detection_accuracy() -> None:
    chirp = ChirpConfig()
    rad = np.radians(25.0)
    target = Target(id="a", label="person", rcs_m2=1.0, velocity_mps=(0.0, 0.0, 0.0),
                    position_m=(33.3 * np.sin(rad), 33.3 * np.cos(rad), 0.0))
    sim = _frames((target,))
    frame, _ = next(sim.run())
    (det,) = Detector(chirp, sim.array, clutter_map=None).detect(frame)
    assert det.range_m == pytest.approx(33.3, abs=0.2)
    assert det.radial_velocity_mps == pytest.approx(0.0, abs=0.1)
    assert det.azimuth_deg == pytest.approx(25.0, abs=1.0)
    assert det.snr_db > 30


def test_threshold_at_peaks_matches_the_full_map() -> None:
    from upchirp.dsp.cfar import _threshold_at

    rng = np.random.default_rng(3)
    power = rng.exponential(1.0, (64, 256)) * (1 + 5 * rng.random((64, 256)))
    power[rng.integers(0, 64, 30), rng.integers(0, 256, 30)] *= 1e3
    cells = np.argwhere(np.ones(power.shape, dtype=bool))
    fast = _threshold_at(power, CfarConfig(), cells).reshape(power.shape)
    assert np.allclose(fast, threshold(power, CfarConfig()))
