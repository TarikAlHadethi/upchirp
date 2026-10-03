"""Eval: the reference DSP and tracker, scored against ground truth.

Runs both scenes with two noise seeds through the full pipeline. Every number
below is a regression gate: if a change makes any of them worse than the
threshold, the build fails.

The last eval plants a fault (azimuth sign flipped in the detector) and checks
that these same gates catch it.
"""

import dataclasses

import pytest

from upchirp.dsp.detect import Detection, Detector
from upchirp.frame import Frame
from upchirp.pipeline import Pipeline
from upchirp.scoring import (
    DetectionScore,
    TrackScore,
    format_report,
    score_detections,
    score_tracks,
)
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import Scene, get_scene

# Four seeds per scene: on 3 October 2026 all gates held on seeds 0 to 11 of both scenes.
CASES = [(scene, seed) for scene in ("default", "crossing") for seed in (0, 1, 2, 3)]

MIN_PD = {"person": 0.97, "car": 0.97,
          # spinning rotors spread echo over every speed at the drone's range, raising
          # the background it must beat; measured 93 to 98% over seeds (decision 0012)
          "drone_like": 0.90}
MAX_FALSE_ALARMS_PER_FRAME = 0.1
MAX_RANGE_RMSE_M = 0.3
MAX_VELOCITY_RMSE_MPS = 0.15
# rotor echoes share the drone body's cell and disturb its angle (decision 0012)
MAX_AZIMUTH_RMSE_DEG = 1.5
MIN_TRACK_COVERAGE = 0.95
# The default scene's drone flies over the car: same range and angle for a moment, which
# a two-channel radar with no elevation cannot separate (decision 0012). Up to 2 per run.
MAX_ID_SWITCHES = 2
MAX_FALSE_TRACKS_PER_FRAME = 0.05
MAX_TRACK_POSITION_RMSE_M = {"person": 0.5, "car": 0.5, "drone_like": 1.25}
MIN_LABEL_ACCURACY = 0.95  # of the frames with a label
MIN_LABELLED_SHARE = 0.8  # labels wait for evidence: 1 s for drone-like (decision 0014)


def run(scene: str | Scene, seed: int, pipeline_cls: type[Pipeline] = Pipeline
        ) -> tuple[DetectionScore, TrackScore]:
    sc = get_scene(scene) if isinstance(scene, str) else scene
    sim = Simulator(sc, session_id=f"eval-{sc.name}", start_ns=0, seed=seed)
    pipeline = pipeline_cls(sim.chirp, sim.array)
    detections, tracks, truth = [], [], []
    for frame, rows in sim.run():
        result = pipeline.process(frame)
        detections += result.detections
        tracks += result.tracks
        truth += rows
    return score_detections(detections, truth, sim.chirp), score_tracks(tracks, truth)


def failures(det: DetectionScore, trk: TrackScore) -> list[str]:
    out = []
    for label, s in det.per_label.items():
        if s.pd < MIN_PD[label]:
            out.append(f"{label} detection rate {s.pd:.3f} < {MIN_PD[label]}")
    checks = [
        (det.false_alarms_per_frame, MAX_FALSE_ALARMS_PER_FRAME, "false alarms per frame"),
        (det.range_rmse_m, MAX_RANGE_RMSE_M, "range RMSE"),
        (det.velocity_rmse_mps, MAX_VELOCITY_RMSE_MPS, "velocity RMSE"),
        (det.azimuth_rmse_deg, MAX_AZIMUTH_RMSE_DEG, "azimuth RMSE"),
        (trk.id_switches, MAX_ID_SWITCHES, "id switches"),
        (trk.false_tracks_per_frame, MAX_FALSE_TRACKS_PER_FRAME, "false tracks per frame"),
    ]
    out += [f"{name} {value:.3f} > {limit}" for value, limit, name in checks if value > limit]
    for t in trk.per_target.values():
        if t.coverage < MIN_TRACK_COVERAGE:
            out.append(f"{t.target_id} tracked {t.coverage:.3f} < {MIN_TRACK_COVERAGE}")
        if t.position_rmse_m > MAX_TRACK_POSITION_RMSE_M[t.label]:
            out.append(f"{t.target_id} position RMSE {t.position_rmse_m:.3f}")
        if t.label_accuracy < MIN_LABEL_ACCURACY:
            out.append(f"{t.target_id} label right {t.label_accuracy:.3f} < {MIN_LABEL_ACCURACY}")
        if t.labelled_share < MIN_LABELLED_SHARE:
            out.append(f"{t.target_id} labelled {t.labelled_share:.3f} < {MIN_LABELLED_SHARE}")
    return out


@pytest.mark.parametrize(("scene", "seed"), CASES)
def test_pipeline_meets_targets(scene: str, seed: int) -> None:
    det, trk = run(scene, seed)
    print(f"\n{scene} seed {seed}\n{format_report(det, trk)}")
    assert set(det.per_label) == {"person", "car", "drone_like"}
    assert failures(det, trk) == []


@pytest.mark.xfail(strict=True, reason="known limitation, decision 0010: a hovering drone "
                   "at a tree's range and speed is lost; if this passes, update the docs")
def test_drone_hidden_by_tree_is_found() -> None:
    det, trk = run("tree-hide", 0)
    print("\ntree-hide\n" + format_report(det, trk))
    assert trk.per_target["drone-hidden"].coverage >= MIN_TRACK_COVERAGE


@pytest.mark.xfail(strict=True, reason="known limitation, decision 0013: at its real size "
                   "the car's body hides the drone flying low over it; if this passes, update "
                   "the docs and make the default scene's car real size")
def test_drone_over_a_real_size_car_is_found() -> None:
    base = get_scene("default")
    sized = base.model_copy(update={"targets": tuple(
        t.model_copy(update={"extended": t.label == "car"}) for t in base.targets)})
    det, trk = run(sized, 0)
    print("\ndefault scene, real-size car\n" + format_report(det, trk))
    assert failures(det, trk) == []


class _FlippedAzimuthDetector(Detector):
    def detect(self, frame: Frame) -> list[Detection]:
        return [dataclasses.replace(d, azimuth_deg=-d.azimuth_deg) for d in super().detect(frame)]


class _FaultyPipeline(Pipeline):
    def __post_init__(self) -> None:
        super().__post_init__()
        self.detector = _FlippedAzimuthDetector(self.chirp, self.array, self.cfar)


def test_planted_fault_is_caught() -> None:
    det, trk = run("crossing", 0, _FaultyPipeline)
    found = failures(det, trk)
    print("\nplanted fault caught by:", *found, sep="\n  ")
    assert found, "a flipped azimuth sign passed every gate"

