"""Cars at their real size: same-speed echoes along the body become one detection
(decision 0013), and scoring counts any point on the body as on target."""

import numpy as np

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detection, Detector
from upchirp.scoring import score_detections
from upchirp.sim.engine import Simulator, TruthRow
from upchirp.sim.scene import Scene, Target


def _det(r: float, v: float, az: float, snr: float = 40.0) -> Detection:
    return Detection(session_id="s", frame_index=0, timestamp_ns=0, range_m=r,
                     radial_velocity_mps=v, azimuth_deg=az, snr_db=snr, range_bin=int(r),
                     doppler_bin=32)


DET = Detector(ChirpConfig(), ArrayConfig())


def test_car_ends_become_one_detection() -> None:
    out = DET.clustered([_det(23.5, 7.1, 11.3, 62), _det(26.6, 7.2, 11.3, 68)])
    assert len(out) == 1 and 23.5 < out[0].range_m < 26.6


def test_too_long_for_one_car_stays_two() -> None:
    assert len(DET.clustered([_det(20.0, 7.0, 5.0), _det(27.0, 7.0, 5.0)])) == 2


def test_far_apart_needs_nearly_the_same_angle() -> None:
    assert len(DET.clustered([_det(20.0, 7.0, 5.0), _det(23.0, 7.0, 9.0)])) == 2


def test_people_crossing_at_near_zero_speed_stay_apart() -> None:  # crossing scene, frame 75
    assert len(DET.clustered([_det(19.2, 0.0, 0.7, 75), _det(22.0, 0.02, 0.8, 60)])) == 2


def test_limbs_at_other_speeds_stay_apart() -> None:
    assert len(DET.clustered([_det(20.0, 1.3, 5.0), _det(20.3, 2.6, 5.0)])) == 2


def _truth(extent: float) -> TruthRow:
    return TruthRow(session_id="s", frame_index=0, timestamp_ns=0, target_id="car",
                    label="car", x_m=0.0, y_m=30.0, z_m=0.0, range_m=30.0,
                    radial_velocity_mps=7.0, azimuth_deg=0.0, rcs_m2=10.0, in_view=True,
                    extent_m=extent)


def test_a_detection_on_the_body_is_on_target() -> None:
    chirp = ChirpConfig()
    dets = [_det(32.0, 7.0, 0.0)]  # the car's far end, 2 m behind its centre
    point = score_detections(dets, [_truth(0.0)], chirp)
    sized = score_detections(dets, [_truth(4.5)], chirp)
    assert point.false_alarms == 1  # as a point, the far end is off target
    assert sized.per_label["car"].n_detected == 1 and sized.range_rmse_m == 0.0


def test_truth_carries_the_body_depth() -> None:
    car = Target(id="car", label="car", position_m=(0.0, 30.0, 0.0),
                 velocity_mps=(0.0, 7.0, 0.0), rcs_m2=10.0, micro_doppler=True, extended=True)
    scene = Scene(name="car", duration_s=0.1, frame_period_s=0.1, targets=(car,))
    _, truth = next(Simulator(scene, "t", 0).run())
    assert np.isclose(truth[0].extent_m, 4.5)  # driving straight away: its full length
    point = scene.model_copy(update={"targets": (car.model_copy(update={"extended": False}),)})
    assert next(Simulator(point, "t", 0).run())[1][0].extent_m == 0.0


def test_car_seen_side_on_is_one_detection() -> None:
    # crossing the view: about 2 m deep, at nearly zero radial speed
    assert len(DET.clustered([_det(49.6, 0.3, 4.1, 60), _det(51.4, 0.4, 4.0, 55)])) == 1
