"""Eval: 15 minutes of the busy courtyard (the scene the live demo plays), decision 0014.

The short scenes check precision; this checks what the demo's headline question needs over
a long run: the agent's tools must count the right number of drone-like objects in it.
Gates are set just below the worst of three layouts measured on 3 October 2026, so a
regression fails the build. People crossing the view at a tree's range are hidden for a
while (same range and Doppler cell as the tree, decision 0014), which is why the people
gates are looser here than in the short scenes.
"""

from collections import Counter
from typing import Any

import pytest

from upchirp.agent.data import _track_label, stitch
from upchirp.dsp.tracker import TrackState
from upchirp.pipeline import Pipeline
from upchirp.scoring import DetectionScore, TrackScore, score_detections, score_tracks
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import courtyard_scene

MIN_PD = {"person": 0.80, "car": 0.97, "drone_like": 0.85}
MAX_FALSE_ALARMS_PER_FRAME = 0.1
MAX_FALSE_TRACKS_PER_FRAME = 0.03
MAX_ID_SWITCHES = 15  # over 15 minutes; worst layout measured 12
# objects after stitching, as a share of the true count (people break up at tree range)
MAX_OBJECTS_PER_TRUE = {"person": 1.4, "car": 1.3}


@pytest.fixture(scope="module")
def run() -> tuple[DetectionScore, TrackScore, dict[str, int], dict[str, int]]:
    scene = courtyard_scene()
    sim = Simulator(scene, session_id="eval-courtyard", start_ns=0, seed=0)
    pipeline = Pipeline(sim.chirp, sim.array)
    detections: list[Any] = []
    tracks: list[TrackState] = []
    truth: list[Any] = []
    for frame, rows in sim.run():
        result = pipeline.process(frame)
        detections += result.detections
        tracks += result.tracks
        truth += rows
    by_track: dict[int, list[TrackState]] = {}
    for s in tracks:
        if s.confirmed:
            by_track.setdefault(s.track_id, []).append(s)
    objects = Counter(_track_label(sorted((s for tid in ids for s in by_track[tid]),
                                          key=lambda s: s.timestamp_ns))
                      for ids in stitch(by_track).values())
    true_objects = Counter(t.label for t in scene.targets)
    return (score_detections(detections, truth, sim.chirp), score_tracks(tracks, truth),
            dict(objects), dict(true_objects))


def test_drone_like_objects_counted_right(run: Any) -> None:
    """The demo's headline question: how many drone-like targets came by."""
    _, _, objects, truth = run
    print("\nobjects after stitching:", objects, "truth:", truth)
    assert objects.get("drone_like", 0) == truth["drone_like"]


def test_long_run_gates(run: Any) -> None:
    det, trk, objects, truth = run
    for label, s in det.per_label.items():
        assert s.pd >= MIN_PD[label], (label, s.pd)
    assert det.false_alarms_per_frame <= MAX_FALSE_ALARMS_PER_FRAME
    assert trk.false_tracks_per_frame <= MAX_FALSE_TRACKS_PER_FRAME
    assert trk.id_switches <= MAX_ID_SWITCHES
    for label, ratio in MAX_OBJECTS_PER_TRUE.items():
        assert truth[label] <= objects.get(label, 0) * 1.25, (label, objects, truth)  # few lost
        assert objects.get(label, 0) <= ratio * truth[label], (label, objects, truth)
