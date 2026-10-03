"""Score detections and tracks against simulated ground truth.

Detections are matched to in-view targets frame by frame (Hungarian, within
two range bins and two velocity bins). Confirmed tracks are matched to targets
by position in the radar plane, within `gate_m`.

Ground truth is taken at the start of each frame, while a detection averages
over the frame's chirps (64 ms), so fast targets show a small bias. The gates
and the eval thresholds allow for it.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from upchirp.config import ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackState
from upchirp.sim.engine import TruthRow

GATE_BINS = 2.0
PART_AZIMUTH_DEG = 20.0  # part echoes are weak, so their angle is poor
# A detection more than this far off in angle is not that target's echo, even at the right
# range and speed (a car's tyre contact patch, at 0 m/s, beside a hovering drone).
MATCH_AZIMUTH_DEG = 15.0


def _rmse(errors: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(errors)))) if errors else float("nan")


def _by_frame[T: (Detection, TrackState, TruthRow)](rows: Iterable[T]) -> dict[int, list[T]]:
    out: dict[int, list[T]] = defaultdict(list)
    for row in rows:
        out[row.frame_index].append(row)
    return out


@dataclass
class LabelDetectionScore:
    n_truth: int = 0
    n_detected: int = 0

    @property
    def pd(self) -> float:
        return self.n_detected / self.n_truth if self.n_truth else float("nan")


@dataclass
class DetectionScore:
    n_frames: int
    false_alarms: int
    per_label: dict[str, LabelDetectionScore]
    part_echoes: int  # at a target's range and angle but another speed: limbs, wheels, rotors
    range_rmse_m: float
    velocity_rmse_mps: float
    azimuth_rmse_deg: float

    @property
    def false_alarms_per_frame(self) -> float:
        return self.false_alarms / self.n_frames if self.n_frames else float("nan")


def _off_body(range_m: float, t: TruthRow) -> float:
    """Range error of a detection: from the nearest point of the target's body, which is
    its centre for a point target."""
    d = range_m - t.range_m
    return float(np.sign(d) * max(0.0, abs(d) - t.extent_m / 2))


def score_detections(
    detections: Iterable[Detection], truth: Iterable[TruthRow], chirp: ChirpConfig
) -> DetectionScore:
    dets, gt = _by_frame(detections), _by_frame(truth)
    per_label: dict[str, LabelDetectionScore] = defaultdict(LabelDetectionScore)
    errs: dict[str, list[float]] = {"r": [], "v": [], "az": []}
    false_alarms = part_echoes = 0
    for frame_index, rows in gt.items():
        targets = [t for t in rows if t.in_view]
        found = dets.get(frame_index, [])
        for t in targets:
            per_label[t.label].n_truth += 1
        matched = set()
        if targets and found:
            dr = np.array([[_off_body(d.range_m, t) / chirp.range_bin_m for d in found]
                           for t in targets])
            dv = np.array([[(d.radial_velocity_mps - t.radial_velocity_mps)
                            / chirp.velocity_bin_mps for d in found] for t in targets])
            da = np.array([[d.azimuth_deg - t.azimuth_deg for d in found] for t in targets])
            inside = ((np.abs(dr) <= GATE_BINS) & (np.abs(dv) <= GATE_BINS)
                      & (np.abs(da) <= MATCH_AZIMUTH_DEG))
            cost = np.where(inside, dr**2 + dv**2, 1e9)
            for i, j in zip(*linear_sum_assignment(cost), strict=True):
                if inside[i, j]:
                    t, d = targets[i], found[j]
                    per_label[t.label].n_detected += 1
                    matched.add(j)
                    errs["r"].append(_off_body(d.range_m, t))
                    errs["v"].append(d.radial_velocity_mps - t.radial_velocity_mps)
                    errs["az"].append(d.azimuth_deg - t.azimuth_deg)
        for j, d in enumerate(found):
            if j in matched:
                continue
            if any(abs(_off_body(d.range_m, t)) <= 1.5 * chirp.range_bin_m
                   and abs(d.azimuth_deg - t.azimuth_deg) <= PART_AZIMUTH_DEG for t in targets):
                part_echoes += 1
            else:
                false_alarms += 1
    return DetectionScore(
        n_frames=len(gt), false_alarms=false_alarms, per_label=dict(per_label),
        part_echoes=part_echoes,
        range_rmse_m=_rmse(errs["r"]), velocity_rmse_mps=_rmse(errs["v"]),
        azimuth_rmse_deg=_rmse(errs["az"]),
    )


@dataclass
class TargetTrackScore:
    target_id: str
    label: str
    n_frames: int = 0
    n_tracked: int = 0
    id_switches: int = 0
    n_label_correct: int = 0
    n_labelled: int = 0  # tracked frames whose track had a label (not "unknown")
    track_ids: set[int] = field(default_factory=set)
    errors_m: list[float] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.n_tracked / self.n_frames if self.n_frames else float("nan")

    @property
    def position_rmse_m(self) -> float:
        return _rmse(self.errors_m)

    @property
    def label_accuracy(self) -> float:
        """Of the tracked frames whose track had a label, the share where it was right."""
        return self.n_label_correct / self.n_labelled if self.n_labelled else float("nan")

    @property
    def labelled_share(self) -> float:
        """Share of tracked frames with a label. A new track says "unknown" until it is
        sure (a drone-like label needs 1 s of echoes): holding back is not a wrong label."""
        return self.n_labelled / self.n_tracked if self.n_tracked else float("nan")


@dataclass
class TrackScore:
    n_frames: int
    false_track_frames: int
    per_target: dict[str, TargetTrackScore]

    @property
    def false_tracks_per_frame(self) -> float:
        return self.false_track_frames / self.n_frames if self.n_frames else float("nan")

    @property
    def id_switches(self) -> int:
        return sum(t.id_switches for t in self.per_target.values())


def truth_xy(t: TruthRow) -> tuple[float, float]:
    """Truth in the radar plane, the same coordinates the tracker uses."""
    az = np.radians(t.azimuth_deg)
    return float(t.range_m * np.sin(az)), float(t.range_m * np.cos(az))


def score_tracks(
    tracks: Iterable[TrackState], truth: Iterable[TruthRow], gate_m: float = 3.0
) -> TrackScore:
    trk = _by_frame(s for s in tracks if s.confirmed)
    gt = _by_frame(truth)
    per_target: dict[str, TargetTrackScore] = {}
    last_id: dict[str, int] = {}
    false_frames = 0
    for frame_index in sorted(gt):
        targets = [t for t in gt[frame_index] if t.in_view]
        states = trk.get(frame_index, [])
        for t in targets:
            per_target.setdefault(t.target_id, TargetTrackScore(t.target_id, t.label)).n_frames += 1
        matched = set()
        if targets and states:
            dist = np.array([[np.hypot(s.x_m - truth_xy(t)[0], s.y_m - truth_xy(t)[1])
                              for s in states] for t in targets])
            # a long body moves the track's point along it, so the gate grows with it
            gate = np.array([[gate_m + t.extent_m / 2] for t in targets])
            for i, j in zip(*linear_sum_assignment(np.where(dist <= gate, dist, 1e9)),
                            strict=True):
                if dist[i, j] <= gate[i, 0]:
                    t, s = targets[i], states[j]
                    score = per_target[t.target_id]
                    score.n_tracked += 1
                    score.n_label_correct += s.label == t.label
                    score.n_labelled += s.label != "unknown"
                    score.errors_m.append(float(dist[i, j]))
                    score.track_ids.add(s.track_id)
                    if t.target_id in last_id and last_id[t.target_id] != s.track_id:
                        score.id_switches += 1
                    last_id[t.target_id] = s.track_id
                    matched.add(j)
        false_frames += len(states) - len(matched)
    return TrackScore(n_frames=len(gt), false_track_frames=false_frames, per_target=per_target)


def format_report(det: DetectionScore, trk: TrackScore) -> str:
    lines = [
        f"Detections ({det.n_frames} frames)",
        *(f"  {label:<11} found {s.n_detected}/{s.n_truth} ({s.pd:.1%})"
          for label, s in sorted(det.per_label.items())),
        f"  false alarms per frame  {det.false_alarms_per_frame:.3f} "
        f"(plus {det.part_echoes / max(det.n_frames, 1):.2f} echoes per frame from moving parts)",
        f"  error (RMS)             range {det.range_rmse_m:.2f} m, "
        f"velocity {det.velocity_rmse_mps:.2f} m/s, azimuth {det.azimuth_rmse_deg:.2f} deg",
        "Tracks",
        *(f"  {t.target_id:<12} {t.label:<11} tracked {t.coverage:.1%} of frames, "
          f"track ids {sorted(t.track_ids)}, position error {t.position_rmse_m:.2f} m, "
          f"label right {t.label_accuracy:.1%} of {t.labelled_share:.0%} labelled"
          for t in trk.per_target.values()),
        f"  id switches             {trk.id_switches}",
        f"  false tracks per frame  {trk.false_tracks_per_frame:.3f}",
    ]
    return "\n".join(lines)
