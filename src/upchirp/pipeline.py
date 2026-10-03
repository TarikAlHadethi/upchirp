"""Frames in, detections and tracks out. The same code runs on every frame source."""

import dataclasses
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from upchirp.classify.rules import RuleLabeler
from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.cfar import CfarConfig
from upchirp.dsp.detect import Detection, Detector
from upchirp.dsp.tracker import Tracker, TrackerConfig, TrackState
from upchirp.frame import Frame


@dataclass
class FrameResult:
    frame: Frame
    detections: list[Detection]
    tracks: list[TrackState]


@dataclass
class Pipeline:
    chirp: ChirpConfig
    array: ArrayConfig
    cfar: CfarConfig = field(default_factory=CfarConfig)
    tracker_cfg: TrackerConfig = field(default_factory=TrackerConfig)
    # "rules" (RCS rules, decision 0006) or "onnx" (the step 9 classifier, decision 0011)
    labeler_kind: str = field(default_factory=lambda: os.environ.get("UPCHIRP_LABELER", "rules"))

    def __post_init__(self) -> None:
        self.detector = Detector(self.chirp, self.array, self.cfar)
        self.tracker = Tracker(self.tracker_cfg)
        self.labeler = RuleLabeler()  # also gives each track its RCS estimate
        self.classifier: Any = None
        if self.labeler_kind == "onnx":
            from upchirp.classify.onnx_labeler import OnnxLabeler

            self.classifier = OnnxLabeler()

    def process(self, frame: Frame) -> FrameResult:
        if frame.chirp_config_id != self.chirp.id:
            raise ValueError(
                f"frame uses chirp config '{frame.chirp_config_id}', pipeline has '{self.chirp.id}'"
            )
        detections = self.detector.detect(frame)
        self.tracker.step(detections, frame.timestamp_ns)
        for track_id, det in self.tracker.associations.items():
            self.labeler.observe(track_id, det)
        if self.classifier is not None and self.detector.last_power is not None:
            self.classifier.observe_frame(self.detector.last_power, self.tracker.associations)
        tracks = []
        for state in self.tracker.states(frame.session_id, frame.frame_index):
            label, rcs = self.labeler.label(state.track_id)
            if self.classifier is not None:
                label, _ = self.classifier.label(state.track_id)
            tracks.append(dataclasses.replace(state, label=label, rcs_dbsm=rcs))
        return FrameResult(frame, detections, tracks)

    def run(self, frames: Iterable[Frame]) -> Iterator[FrameResult]:
        for frame in frames:
            yield self.process(frame)
