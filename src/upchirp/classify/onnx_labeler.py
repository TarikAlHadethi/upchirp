"""Track labels from the trained patch classifier (ONNX), as an alternative to the rules.

For every detection a track takes, cut the same patch the classifier was trained on
from the frame's power map, run the model, and average the class probabilities over
the track's last `history` detections. Off by default (UPCHIRP_LABELER=onnx turns it
on): on our simulator the classifier is no better than chance, because simulated
targets have no micro-Doppler (see docs/reports/classifier.md), so the rules stay
the default until real recordings show the classifier is better.
"""

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp.classify.patches import cut_patch, normalise
from upchirp.classify.rules import UNKNOWN
from upchirp.dsp.detect import Detection

DEFAULT_MODEL = Path(__file__).resolve().parents[3] / "models" / "classifier.onnx"


@dataclass
class OnnxLabeler:
    model_path: Path = DEFAULT_MODEL
    history: int = 20
    min_detections: int = 3
    _probs: dict[int, deque[npt.NDArray[np.float64]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        import onnxruntime as ort

        meta = json.loads(self.model_path.with_suffix(".json").read_text())
        self.classes: list[str] = meta["classes"]
        self.doppler_cells: int = meta["doppler_cells"]
        self.session = ort.InferenceSession(str(self.model_path),
                                            providers=["CPUExecutionProvider"])
        self._probs = defaultdict(lambda: deque(maxlen=self.history))

    def classify(self, patches: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
        """Class probabilities for normalised patches [n, 11, D]."""
        (logits,) = self.session.run(None, {"patch": patches.astype(np.float32)})
        z = logits - logits.max(axis=1, keepdims=True)
        p: npt.NDArray[np.float64] = np.exp(z) / np.exp(z).sum(axis=1, keepdims=True)
        return p

    def observe_frame(self, power: npt.NDArray[Any],
                      associations: dict[int, Detection]) -> None:
        if not associations:
            return
        ids = list(associations)
        patches = np.stack([cut_patch(power, associations[i].doppler_bin,
                                      associations[i].range_bin, self.doppler_cells)
                            for i in ids])
        for track_id, p in zip(ids, self.classify(normalise(patches)), strict=True):
            self._probs[track_id].append(p)

    def label(self, track_id: int) -> tuple[str, float]:
        """(label, mean probability of that label); 'unknown' until enough detections."""
        hist = self._probs.get(track_id)
        if not hist or len(hist) < self.min_detections:
            return UNKNOWN, float("nan")
        mean = np.mean(hist, axis=0)
        k = int(np.argmax(mean))
        return self.classes[k], float(mean[k])
