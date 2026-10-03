"""The realistic simulator (fading, clutter, wobble) and the clutter map that copes with it."""

import numpy as np
import pytest

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detector
from upchirp.sim.engine import Simulator, fluctuation
from upchirp.sim.scene import Clutter, Scene, Target

WALL = Clutter(id="wall", position_m=(-10.0, 40.0, 0.0), rcs_m2=50.0)
TREE = Clutter(id="tree", position_m=(8.0, 30.0, 0.0), rcs_m2=3.0, spread_mps=0.15)


def _detections(scene: Scene, clutter_map: bool = True, seed: int = 0) -> list[int]:
    """Number of detections in each frame after the clutter map's warm-up."""
    det = Detector(ChirpConfig(), ArrayConfig()) if clutter_map else Detector(
        ChirpConfig(), ArrayConfig(), clutter_map=None)
    counts = []
    for i, (frame, _) in enumerate(Simulator(scene, "t", 0, seed=seed).run()):
        found = det.detect(frame)
        if i >= 20:
            counts.append(len(found))
    return counts


@pytest.mark.parametrize("swerling", [1, 3])
def test_fluctuation_has_mean_one(swerling: int) -> None:
    rng = np.random.default_rng(0)
    draws = [fluctuation(swerling, rng) for _ in range(20_000)]
    assert np.mean(draws) == pytest.approx(1.0, abs=0.03)
    assert np.std(draws) > 0.5  # it really fluctuates


def test_wobble_moves_and_velocity_matches() -> None:
    t = Target(id="d", label="drone_like", position_m=(0, 30, 10), rcs_m2=0.01,
               wobble_m=(0.4, 0.0, 0.0), wobble_period_s=2.0)
    xs = t.position_at(np.linspace(0, 2, 50))[:, 0]
    assert xs.max() == pytest.approx(0.4, abs=0.01) and xs.min() == pytest.approx(-0.4, abs=0.01)
    dt = 1e-4
    numeric = (t.position_at(0.3 + dt) - t.position_at(0.3)) / dt
    assert t.velocity_at(0.3) == pytest.approx(numeric, abs=1e-3)


def test_walls_vanish_with_the_clutter_map() -> None:
    scene = Scene(name="wall", duration_s=4.0, frame_period_s=0.1, targets=(), clutter=(WALL,))
    assert sum(_detections(scene, clutter_map=False)) > 0  # without it the wall is seen
    assert sum(_detections(scene)) == 0


def test_trees_do_not_make_detections() -> None:
    scene = Scene(name="tree", duration_s=6.0, frame_period_s=0.1, targets=(), clutter=(TREE,))
    counts = _detections(scene)
    assert sum(counts) <= 1, counts


def test_hovering_drone_is_still_seen() -> None:
    drone = Target(id="d", label="drone_like", position_m=(-5.0, 35.0, 10.0), rcs_m2=0.01,
                   swerling=1, start_s=2.0, wobble_m=(0.4, 0.3, 0.2), wobble_period_s=3.0)
    scene = Scene(name="hover", duration_s=8.0, frame_period_s=0.1, targets=(drone,),
                  clutter=(WALL, TREE))
    counts = _detections(scene)
    assert np.mean([c > 0 for c in counts]) > 0.9


def test_micro_doppler_spreads_the_echo() -> None:
    from upchirp.dsp.rdmap import range_bin_of, range_doppler

    def spread(target: Target) -> int:
        scene = Scene(name="md", duration_s=0.1, frame_period_s=0.1, targets=(target,))
        frame, _ = next(Simulator(scene, "t", 0).run())
        col = (np.abs(range_doppler(frame.cube())) ** 2).sum(0)[:, range_bin_of(ChirpConfig(), 30)]
        return int((10 * np.log10(col / col.max()) > -30).sum())

    for label, vel in (("person", (0.0, -1.3, 0.0)), ("car", (0.0, -7.0, 0.0)),
                       ("drone_like", (0.0, 0.0, 0.0))):
        plain = Target(id="t", label=label, position_m=(0, 30, 0), velocity_mps=vel, rcs_m2=1.0)
        moving = plain.model_copy(update={"micro_doppler": True})
        assert spread(moving) >= spread(plain) + 5, label

    # wheels and limbs moving across the line of sight add almost no Doppler
    for label, speed in (("person", 1.3), ("car", 7.0)):
        across, toward = (Target(id="t", label=label, position_m=(0, 30, 0), velocity_mps=v,
                                 rcs_m2=1.0, micro_doppler=True)
                          for v in ((speed, 0.0, 0.0), (0.0, -speed, 0.0)))
        assert spread(across) < spread(toward), label
