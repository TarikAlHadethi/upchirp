import numpy as np
import pytest

from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import Tracker, TrackerConfig

DT_NS = 100_000_000


def _det(frame: int, x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> Detection:
    r = float(np.hypot(x, y))
    return Detection(
        session_id="t", frame_index=frame, timestamp_ns=frame * DT_NS, range_m=r,
        radial_velocity_mps=(x * vx + y * vy) / r, azimuth_deg=float(np.degrees(np.arctan2(x, y))),
        snr_db=30.0, range_bin=round(r), doppler_bin=32,
    )


def _run(frames: list[list[Detection]]) -> Tracker:
    tracker = Tracker()
    for i, dets in enumerate(frames):
        tracker.step(dets, i * DT_NS)
    return tracker


def test_straight_line_gives_one_confirmed_track() -> None:
    vx, vy = 3.0, -2.0
    frames = [[_det(i, -10 + vx * 0.1 * i, 40 + vy * 0.1 * i, vx, vy)] for i in range(30)]
    tracker = _run(frames)
    (state,) = tracker.states("t", 29)
    assert state.confirmed and state.track_id == 1
    assert state.vx_mps == pytest.approx(vx, abs=0.2)
    assert state.vy_mps == pytest.approx(vy, abs=0.2)


def test_confirmation_needs_three_hits() -> None:
    tracker = Tracker()
    for i in range(TrackerConfig().confirm_hits):
        tracker.step([_det(i, 0.0, 20.0)], i * DT_NS)
        (state,) = tracker.states("t", i)
        assert state.confirmed == (i + 1 >= TrackerConfig().confirm_hits)


def test_single_false_alarm_never_confirms() -> None:
    tracker = _run([[_det(0, 5.0, 30.0)], [], [], []])
    assert tracker.states("t", 3) == []


def test_confirmed_track_coasts_then_drops() -> None:
    cfg = TrackerConfig()
    frames: list[list[Detection]] = [[_det(i, 0.0, 20.0)] for i in range(5)]
    tracker = _run(frames + [[] for _ in range(cfg.max_misses - 1)])
    assert len(tracker.states("t", 0)) == 1
    tracker.step([], (5 + cfg.max_misses) * DT_NS)
    assert tracker.states("t", 0) == []


def test_two_targets_keep_their_ids_when_close() -> None:
    # Pass within 3 m of each other, moving in opposite directions.
    frames = []
    for i in range(60):
        t = 0.1 * i
        a = _det(i, -4 + 1.4 * t, 20.0, 1.4, 0.0)
        b = _det(i, 4 - 1.4 * t, 23.0, -1.4, 0.0)
        frames.append([a, b])
    tracker = _run(frames)
    states = sorted(tracker.states("t", 59), key=lambda s: s.track_id)
    assert [s.track_id for s in states] == [1, 2]
    assert states[0].vx_mps > 0 > states[1].vx_mps


def _det_at(frame: int, r: float, az: float, v: float, snr: float) -> Detection:
    return Detection(session_id="t", frame_index=frame, timestamp_ns=frame * DT_NS, range_m=r,
                     radial_velocity_mps=v, azimuth_deg=az, snr_db=snr,
                     range_bin=round(r), doppler_bin=32)


def test_part_echoes_do_not_become_tracks() -> None:
    """A body plus limb echoes at the same range, other speeds and slightly off angles."""
    frames = []
    for i in range(30):
        r = 25.0 - 1.0 * 0.1 * i  # approaching at 1 m/s
        body = _det_at(i, r, 5.0, -1.0, 40.0)
        limbs = [_det_at(i, r + 0.4, 5.0 + off, -1.0 + dv, 25.0)
                 for off, dv in ((-9.0, 1.4), (7.0, -1.3), (12.0, 2.0))]
        frames.append([body, *limbs])
    tracker = _run(frames)
    states = [s for s in tracker.states("t", 29) if s.confirmed]
    assert len(states) == 1
    assert states[0].radial_velocity_mps == pytest.approx(-1.0, abs=0.3)  # the body, not a limb


def test_people_side_by_side_keep_two_tracks() -> None:
    """Two people at the same range, a few degrees apart, walking in different directions."""
    frames = []
    for i in range(40):
        t = 0.1 * i
        left = _det(i, -3 + 1.2 * t, 20.0, 1.2, 0.0)
        right = _det(i, 3 - 1.2 * t, 20.5, -1.2, 0.0)
        frames.append([left, right])
    tracker = _run(frames)
    assert len([s for s in tracker.states("t", 39) if s.confirmed]) == 2
