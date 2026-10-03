"""Rule-based track labels: a stand-in until the step 9 classifier.

Each detection gives an estimate of radar cross section (RCS):

    rcs_dbsm = snr_db + 40 * log10(range_m / 10) - RCS_CAL_DB

from the radar equation (received power falls as 1/R^4). A track's label is
decided by the median of its recent estimates: cars are large, people are
around 1 square metre, drone-like targets are small.

RCS_CAL_DB was measured on the simulator (78.2, spread under 1 dB). On real
hardware it must be measured again with a target of known RCS, such as a
corner reflector (Abdullah's characterization). The simulator also has no RCS
fluctuation, so these rules look better here than they will on real data.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from upchirp.dsp.detect import Detection

RCS_CAL_DB = 78.2
UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuleConfig:
    car_min_dbsm: float = 5.0
    drone_max_dbsm: float = -10.0
    min_detections: int = 3
    # Drone-like is the label people act on, so it needs more evidence: a person's echo
    # fluctuates (Swerling 1), and the median of only 3 estimates falls 10 dB under its
    # mean about 2.5% of the time; of 10, about once in 10,000. Until then the
    # track stays unknown (decision 0014).
    min_detections_drone: int = 10
    history: int = 20


def rcs_dbsm(det: Detection) -> float:
    return det.snr_db + 40 * float(np.log10(max(det.range_m, 1.0) / 10)) - RCS_CAL_DB


def label_for(rcs: float, cfg: RuleConfig) -> str:
    if rcs >= cfg.car_min_dbsm:
        return "car"
    if rcs <= cfg.drone_max_dbsm:
        return "drone_like"
    return "person"


@dataclass
class RuleLabeler:
    cfg: RuleConfig = field(default_factory=RuleConfig)
    _history: dict[int, deque[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._history = defaultdict(lambda: deque(maxlen=self.cfg.history))

    def observe(self, track_id: int, det: Detection) -> None:
        self._history[track_id].append(rcs_dbsm(det))

    def label(self, track_id: int) -> tuple[str, float]:
        """(label, median RCS in dBsm) for a track; 'unknown' until enough detections."""
        hist = self._history.get(track_id)
        if not hist:
            return UNKNOWN, float("nan")
        rcs = float(np.median(hist))
        if len(hist) < self.cfg.min_detections:
            return UNKNOWN, rcs
        label = label_for(rcs, self.cfg)
        if label == "drone_like" and len(hist) < self.cfg.min_detections_drone:
            return UNKNOWN, rcs
        return label, rcs
