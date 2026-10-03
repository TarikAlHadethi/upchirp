"""The simulated signal puts each target where the radar equations say it should be."""

import numpy as np
import pytest

from upchirp.config import ChirpConfig
from upchirp.dsp.rdmap import azimuth_deg, doppler_bin_of, range_bin_of, range_doppler
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import Scene, Target

CHIRP = ChirpConfig()


def _one_target(target: Target) -> Simulator:
    scene = Scene(name="test", duration_s=0.1, frame_period_s=0.1, targets=(target,))
    return Simulator(scene, session_id="t", start_ns=0, seed=1)


def _peak(sim: Simulator) -> tuple[np.ndarray, int, int]:
    frame, _ = next(sim.run())
    rd = range_doppler(frame.cube())
    power = (np.abs(rd) ** 2).sum(axis=0)
    d, r = np.unravel_index(int(np.argmax(power)), power.shape)
    return rd, int(d), int(r)


def test_derived_config() -> None:
    assert CHIRP.range_bin_m == pytest.approx(1.0, rel=0.01)
    assert CHIRP.max_velocity_mps == pytest.approx(13.1, rel=0.01)


@pytest.mark.parametrize("range_m", [5.0, 20.0, 47.0, 120.0])
def test_static_target_range(range_m: float) -> None:
    target = Target(id="a", label="person", position_m=(0.0, range_m, 0.0), rcs_m2=1.0)
    _, d, r = _peak(_one_target(target))
    assert r == range_bin_of(CHIRP, range_m)
    assert d == doppler_bin_of(CHIRP, 0.0)


@pytest.mark.parametrize("velocity", [-8.0, -2.0, 1.5, 6.0])
def test_radial_velocity(velocity: float) -> None:
    target = Target(id="a", label="car", position_m=(0.0, 40.0, 0.0),
                    velocity_mps=(0.0, velocity, 0.0), rcs_m2=10.0)
    _, d, r = _peak(_one_target(target))
    assert d == doppler_bin_of(CHIRP, velocity)
    assert abs(r - range_bin_of(CHIRP, 40.0)) <= 1


@pytest.mark.parametrize("angle", [-50.0, -20.0, 0.0, 10.0, 35.0])
def test_azimuth(angle: float) -> None:
    rad = np.radians(angle)
    target = Target(id="a", label="person", rcs_m2=1.0,
                    position_m=(30 * np.sin(rad), 30 * np.cos(rad), 0.0))
    rd, d, r = _peak(_one_target(target))
    assert azimuth_deg(rd, d, r) == pytest.approx(angle, abs=1.0)


def test_truth_matches_geometry() -> None:
    target = Target(id="a", label="drone_like", position_m=(3.0, 4.0, 12.0),
                    velocity_mps=(0.0, 0.0, -1.0), rcs_m2=0.01)
    _, truth = next(_one_target(target).run())
    (row,) = truth
    assert row.range_m == pytest.approx(13.0)
    assert row.radial_velocity_mps == pytest.approx(-12.0 / 13.0)
    assert row.azimuth_deg == pytest.approx(np.degrees(np.arcsin(3.0 / 13.0)))
    assert row.in_view


def test_out_of_range_target_is_dropped() -> None:
    far = Target(id="far", label="car", position_m=(0.0, 400.0, 0.0), rcs_m2=10.0)
    frame, truth = next(_one_target(far).run())
    assert not truth[0].in_view
    assert np.abs(frame.cube()).max() < 0.1


def test_same_seed_same_data() -> None:
    target = Target(id="a", label="person", position_m=(1.0, 10.0, 0.0), rcs_m2=1.0)
    a, _ = next(_one_target(target).run())
    b, _ = next(_one_target(target).run())
    assert a.data == b.data
