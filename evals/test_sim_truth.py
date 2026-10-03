"""Eval: every target in the default scene shows up where its ground truth says.

For each target in view in each frame, look in a small window around its true
range and Doppler cell. Pass when the strongest cell there is within one bin of
the truth, stands at least MIN_SNR_DB over the noise floor, and its angle is
within MAX_ANGLE_ERR_DEG of the true azimuth.

This checks geometry, so it runs the scene without clutter, with steady echoes and
without micro-Doppler (moving parts blur the peak on purpose).
Fading and clutter are covered by evals/test_detection_tracking.py.
"""

from collections import defaultdict

import numpy as np
import pytest

from upchirp.dsp.rdmap import azimuth_deg, doppler_bin_of, range_bin_of, range_doppler
from upchirp.sim.engine import Simulator, TruthRow
from upchirp.sim.scene import default_scene

MIN_SNR_DB = 15.0
MAX_ANGLE_ERR_DEG = 3.0
MIN_PASS_RATE = 0.95
SEARCH = 2


def _score(rd: np.ndarray, power: np.ndarray, floor: float, row: TruthRow, sim: Simulator) -> bool:
    chirp = sim.chirp
    d0 = doppler_bin_of(chirp, row.radial_velocity_mps)
    r0 = range_bin_of(chirp, row.range_m)
    d_lo, r_lo = max(d0 - SEARCH, 0), max(r0 - SEARCH, 0)
    window = power[d_lo : d0 + SEARCH + 1, r_lo : r0 + SEARCH + 1]
    dd, rr = np.unravel_index(int(np.argmax(window)), window.shape)
    d, r = d_lo + int(dd), r_lo + int(rr)
    snr_db = 10 * np.log10(power[d, r] / floor)
    angle_err = abs(azimuth_deg(rd, d, r, sim.array.spacing_wavelengths) - row.azimuth_deg)
    return (
        abs(d - d0) <= 1
        and abs(r - r0) <= 1
        and snr_db >= MIN_SNR_DB
        and angle_err <= MAX_ANGLE_ERR_DEG
    )


@pytest.fixture(scope="module")
def results() -> dict[str, list[bool]]:
    scene = default_scene()
    steady = tuple(t.model_copy(update={"swerling": 0, "micro_doppler": False})
                   for t in scene.targets)
    scene = scene.model_copy(update={"clutter": (), "targets": steady})
    sim = Simulator(scene, session_id="eval", start_ns=0, seed=0)
    by_label: dict[str, list[bool]] = defaultdict(list)
    for frame, truth in sim.run():
        rd = range_doppler(frame.cube())
        power = (np.abs(rd) ** 2).sum(axis=0)
        floor = float(np.median(power))
        for row in truth:
            if row.in_view:
                by_label[row.label].append(_score(rd, power, floor, row, sim))
    return by_label


def test_every_label_present(results: dict[str, list[bool]]) -> None:
    assert set(results) == {"person", "car", "drone_like"}


@pytest.mark.parametrize("label", ["person", "car", "drone_like"])
def test_target_found_at_truth(results: dict[str, list[bool]], label: str) -> None:
    passed = results[label]
    rate = sum(passed) / len(passed)
    print(f"{label}: {sum(passed)}/{len(passed)} target-frames at truth ({rate:.1%})")
    assert rate >= MIN_PASS_RATE
