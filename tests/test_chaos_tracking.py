"""Chaos test for the tracker and the labels, through the real Pipeline with a scripted
detector (the DSP in front of it has its own tests and evals).

Rules (sweep-notes/rules.md, K1 to K8):
- track ids are unique in a frame and never used again
- a confirmed track never goes back to unconfirmed
- one detection belongs to at most one track, one track takes at most one detection
- every number in a track state is finite, whatever the timestamps do
- misses stay under the limit, hits are at least 1
- tracks never outnumber the tracks before plus this frame's detections
- labels come from the known set; drone_like needs 10 detections, the others 3
- label history is kept only for tracks that still exist
"""

import dataclasses
import math
import random

import pytest
from chaos_support import Step, check, seeds

from upchirp.classify.rules import RuleConfig
from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.detect import Detection
from upchirp.dsp.tracker import TrackerConfig, TrackState
from upchirp.frame import Frame
from upchirp.pipeline import Pipeline

TINY = ChirpConfig(id="tiny", n_chirps=2, n_samples=8)
LABELS = {"person", "car", "drone_like", "unknown"}
EMPTY = bytes(1 * TINY.n_chirps * TINY.n_samples * 8)


class _ScriptedDetector:
    """Stands in for the Detector: hands back the detections the step asks for."""

    last_power = None

    def __init__(self) -> None:
        self.next: list[Detection] = []

    def detect(self, frame: Frame) -> list[Detection]:
        return self.next


class TrackingWorld:
    def __init__(self) -> None:
        self.pipeline = Pipeline(TINY, ArrayConfig(n_rx=1), labeler_kind="rules")
        self.detector = _ScriptedDetector()
        self.pipeline.detector = self.detector  # type: ignore[assignment]
        self.now_ns = 1_000_000_000
        self.index = 0
        self.tracks: list[TrackState] = []
        self.n_before = 0
        self.n_detections = 0
        self.ever_seen: set[int] = set()
        self.confirmed: set[int] = set()
        self.problems: list[str] = []

    def apply(self, step: Step) -> None:
        dt_ms, rows = step[1]
        self.now_ns += dt_ms * 1_000_000
        self.detector.next = [
            Detection("s", self.index, self.now_ns, range_m=r, radial_velocity_mps=v,
                      azimuth_deg=az, snr_db=snr, range_bin=0, doppler_bin=0)
            for r, az, v, snr in rows]
        frame = Frame(source="sim", session_id="s", frame_index=self.index,
                      timestamp_ns=self.now_ns, chirp_config_id=TINY.id, n_rx=1,
                      n_chirps=TINY.n_chirps, n_samples=TINY.n_samples, stage="raw", data=EMPTY)
        self.index += 1
        self.n_before, self.n_detections = len(self.tracks), len(rows)
        before = {t.track_id for t in self.tracks}
        self.tracks = self.pipeline.process(frame).tracks
        ids = {t.track_id for t in self.tracks}
        if (ids - before) & self.ever_seen:
            self.problems.append("a track id was used again")
        if any(i <= max(self.ever_seen, default=0) for i in ids - before):
            self.problems.append("a new track id is not higher than every earlier one")
        self.ever_seen |= ids
        if any(not t.confirmed for t in self.tracks if t.track_id in self.confirmed):
            self.problems.append("a confirmed track went back to unconfirmed")
        self.confirmed = {t.track_id for t in self.tracks if t.confirmed}

    def broken(self) -> list[str]:
        out = list(self.problems)
        cfg: TrackerConfig = self.pipeline.tracker.cfg
        rules: RuleConfig = self.pipeline.labeler.cfg
        ids = [t.track_id for t in self.tracks]
        if len(ids) != len(set(ids)):
            out.append("two tracks share an id")
        taken = self.pipeline.tracker.associations
        if len({id(d) for d in taken.values()}) != len(taken):
            out.append("one detection belongs to two tracks")
        if not set(taken) <= set(ids):
            out.append("a detection belongs to a track that does not exist")
        if len(ids) > self.n_before + self.n_detections:
            out.append("more tracks than the tracks before plus the detections")
        for t in self.tracks:
            numbers = [v for k, v in dataclasses.asdict(t).items()
                       if isinstance(v, float) and k != "rcs_dbsm"]
            if not all(math.isfinite(v) for v in numbers):
                out.append(f"track {t.track_id} has a number that is not finite")
            limit = cfg.max_misses if t.confirmed else cfg.tentative_misses
            if t.misses >= limit or t.hits < 1:
                out.append(f"track {t.track_id} has hits {t.hits}, misses {t.misses}")
            if t.label not in LABELS:
                out.append(f"track {t.track_id} has label {t.label!r}")
            seen = len(self.pipeline.labeler._history.get(t.track_id, ()))
            need = rules.min_detections_drone if t.label == "drone_like" else rules.min_detections
            if t.label != "unknown" and seen < need:
                out.append(f"track {t.track_id} is {t.label} after {seen} detections")
        if not set(self.pipeline.labeler._history) <= set(ids):
            out.append("label history is kept for a track that no longer exists")
        return out


def _steps(seed: int, n: int = 60) -> list[Step]:
    """A few objects that move, appear and vanish, with clutter, the same echo twice, an echo
    at the radar itself, and a clock that sometimes stands still, jumps or runs back."""
    rng = random.Random(seed)
    objects: list[list[float]] = []  # range, azimuth, radial speed, snr
    steps: list[Step] = []
    for _ in range(n):
        if len(objects) < 4 and rng.random() < 0.3:
            objects.append([rng.uniform(3, 60), rng.uniform(-50, 50), rng.uniform(-8, 8),
                            rng.uniform(60, 110)])
        if objects and rng.random() < 0.08:
            objects.pop(rng.randrange(len(objects)))
        dt_ms = rng.choice([100] * 12 + [0, 0, -100, -5_000, 1, 30_000, 3_600_000])
        rows: list[tuple[float, float, float, float]] = []
        for o in objects:
            o[0] = min(max(o[0] + o[2] * min(max(dt_ms, 0), 1000) / 1000, 0.0), 75.0)
            if rng.random() < 0.85:
                rows.append((max(o[0] + rng.gauss(0, 0.2), 0.0), o[1] + rng.gauss(0, 1.0),
                             o[2] + rng.gauss(0, 0.2), o[3] + rng.gauss(0, 3)))
        for _ in range(rng.choice([0, 0, 0, 1, 2])):
            rows.append((rng.uniform(0, 70), rng.uniform(-60, 60), rng.uniform(-10, 10),
                         rng.uniform(13, 40)))
        if rows and rng.random() < 0.1:
            rows.append(rows[rng.randrange(len(rows))])  # the same echo twice
        if rng.random() < 0.05:
            rows.append((0.0, 0.0, 0.0, 30.0))
        rng.shuffle(rows)
        steps.append(("frame", (dt_ms, [tuple(round(x, 3) for x in row) for row in rows])))
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_tracker_and_labels_keep_their_rules_under_chaos(seed: int) -> None:
    check(TrackingWorld, _steps(seed), seed)


def test_saved_sequence_history_of_a_dropped_track_is_forgotten() -> None:
    # Found by the chaos test: one echo starts a track, two empty frames end it, and its
    # label history stayed for the rest of the run.
    check(TrackingWorld, [
        ("frame", (100, [(20.0, 0.0, 0.0, 30.0)])),
        ("frame", (100, [])),
        ("frame", (100, [])),
    ])
