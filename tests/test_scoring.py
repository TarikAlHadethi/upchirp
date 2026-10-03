"""The scorers must notice when the pipeline is wrong, not just report good numbers."""

import dataclasses

from upchirp.config import ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackState
from upchirp.scoring import score_detections, score_tracks, truth_xy
from upchirp.sim.engine import TruthRow

CHIRP = ChirpConfig()


def _truth(frame: int, tid: str, r: float, v: float = 0.0, az: float = 0.0) -> TruthRow:
    return TruthRow(session_id="t", frame_index=frame, timestamp_ns=frame, target_id=tid,
                    label="person", x_m=0, y_m=r, z_m=0, range_m=r, radial_velocity_mps=v,
                    azimuth_deg=az, rcs_m2=1, in_view=True)


def _det_from(t: TruthRow) -> Detection:
    return Detection(session_id="t", frame_index=t.frame_index, timestamp_ns=t.timestamp_ns,
                     range_m=t.range_m, radial_velocity_mps=t.radial_velocity_mps,
                     azimuth_deg=t.azimuth_deg, snr_db=30, range_bin=0, doppler_bin=0)


def _track_from(t: TruthRow, track_id: int) -> TrackState:
    x, y = truth_xy(t)
    return TrackState(session_id="t", frame_index=t.frame_index, timestamp_ns=0,
                      track_id=track_id, confirmed=True, x_m=x, y_m=y, vx_mps=0, vy_mps=0,
                      range_m=t.range_m, azimuth_deg=t.azimuth_deg, radial_velocity_mps=0,
                      speed_mps=0, hits=5, misses=0)


TRUTH = [_truth(f, tid, r) for f in range(10) for tid, r in (("a", 20.0), ("b", 40.0))]


def test_perfect_detections() -> None:
    s = score_detections([_det_from(t) for t in TRUTH], TRUTH, CHIRP)
    assert s.per_label["person"].pd == 1.0
    assert s.false_alarms == 0
    assert s.range_rmse_m == 0.0


def test_range_bias_is_caught() -> None:
    biased = [dataclasses.replace(_det_from(t), range_m=t.range_m + 3.0) for t in TRUTH]
    s = score_detections(biased, TRUTH, CHIRP)
    assert s.per_label["person"].pd == 0.0
    assert s.false_alarms == len(TRUTH)


def test_extra_detection_is_a_false_alarm() -> None:
    dets = [_det_from(t) for t in TRUTH] + [_det_from(_truth(0, "ghost", 70.0))]
    assert score_detections(dets, TRUTH, CHIRP).false_alarms == 1


def test_perfect_tracks() -> None:
    tracks = [_track_from(t, 1 if t.target_id == "a" else 2) for t in TRUTH]
    s = score_tracks(tracks, TRUTH)
    assert s.id_switches == 0 and s.false_track_frames == 0
    assert all(t.coverage == 1.0 for t in s.per_target.values())


def test_id_swap_is_caught() -> None:
    tracks = [_track_from(t, (1 if t.target_id == "a" else 2) if t.frame_index < 5
                          else (2 if t.target_id == "a" else 1)) for t in TRUTH]
    assert score_tracks(tracks, TRUTH).id_switches == 2


def test_tentative_tracks_are_ignored_and_strays_count() -> None:
    tracks = [dataclasses.replace(_track_from(t, 1), confirmed=False) for t in TRUTH]
    tracks.append(_track_from(_truth(3, "ghost", 70.0), 9))
    s = score_tracks(tracks, TRUTH)
    assert all(t.coverage == 0.0 for t in s.per_target.values())
    assert s.false_track_frames == 1
