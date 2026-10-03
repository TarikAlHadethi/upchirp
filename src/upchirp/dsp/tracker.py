"""Textbook multi-target tracker: 2D constant-velocity Kalman filters with
global nearest neighbour association.

State per track is [x, y, vx, vy] in the radar plane (x along the array,
y = range * cos(azimuth)). Each detection gives a position measurement
converted from range and azimuth. Radial velocity is not filtered on, but
it is used when associating, which keeps targets apart when they pass close.

A track is confirmed after `confirm_hits` hits. A tentative track is dropped
after `tentative_misses` misses in a row, a confirmed one after `max_misses`.
"""

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy.optimize import linear_sum_assignment

from upchirp.dsp.detect import Detection

Array = npt.NDArray[np.float64]
H = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])


@dataclass(frozen=True)
class TrackerConfig:
    accel_std_mps2: float = 2.0  # process noise: unmodelled acceleration
    range_std_m: float = 0.3
    azimuth_std_deg: float = 1.5
    radial_velocity_std_mps: float = 0.3
    initial_tangential_std_mps: float = 3.0
    gate_chi2: float = 14.2  # 3 degrees of freedom, about 99.7%
    # Leftover echoes at nearly a track's range and angle are its moving parts, not a new
    # object. Judged in range and angle: weak part echoes have poor angles, so a distance
    # in x and y would let them through.
    same_object_range_m: float = 1.5
    same_object_azimuth_deg: float = 15.0
    duplicate_mps: float = 1.0
    confirm_hits: int = 3
    tentative_misses: int = 2
    max_misses: int = 5


@dataclass(frozen=True)
class TrackState:
    session_id: str
    frame_index: int
    timestamp_ns: int
    track_id: int
    confirmed: bool
    x_m: float
    y_m: float
    vx_mps: float
    vy_mps: float
    range_m: float
    azimuth_deg: float
    radial_velocity_mps: float
    speed_mps: float
    hits: int
    misses: int
    label: str = "unknown"  # filled in by the pipeline's labeler
    rcs_dbsm: float = float("nan")


@dataclass
class _Track:
    id: int
    x: Array
    P: Array
    hits: int = 1
    misses: int = 0
    confirmed: bool = False

    def radial(self) -> tuple[float, Array]:
        """Predicted radial velocity and its gradient with respect to velocity."""
        pos = self.x[:2]
        u = pos / max(float(np.linalg.norm(pos)), 1e-6)
        return float(u @ self.x[2:]), u


def _measurement_cov(det: Detection, cfg: TrackerConfig) -> Array:
    az = np.radians(det.azimuth_deg)
    r = det.range_m
    jac = np.array([[np.sin(az), r * np.cos(az)], [np.cos(az), -r * np.sin(az)]])
    polar = np.diag([cfg.range_std_m**2, np.radians(cfg.azimuth_std_deg) ** 2])
    cov: Array = jac @ polar @ jac.T
    return cov


@dataclass
class Tracker:
    cfg: TrackerConfig = field(default_factory=TrackerConfig)
    _tracks: list[_Track] = field(default_factory=list)
    _next_id: int = 1
    _last_ns: int | None = None
    # Which detection each track took in the latest step (new tracks included)
    associations: dict[int, Detection] = field(default_factory=dict)

    def _predict(self, dt: float) -> None:
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        q = self.cfg.accel_std_mps2**2
        block = np.array([[dt**4 / 4, dt**3 / 2], [dt**3 / 2, dt**2]]) * q
        Q = np.zeros((4, 4))
        Q[np.ix_([0, 2], [0, 2])] = block
        Q[np.ix_([1, 3], [1, 3])] = block
        for t in self._tracks:
            t.x = F @ t.x
            t.P = F @ t.P @ F.T + Q

    def _cost(self, t: _Track, det: Detection) -> float:
        z = np.array(det.xy)
        S = H @ t.P @ H.T + _measurement_cov(det, self.cfg)
        y = z - t.x[:2]
        d2_pos = float(y @ np.linalg.solve(S, y))
        vr, u = t.radial()
        var_vr = float(u @ t.P[2:, 2:] @ u) + self.cfg.radial_velocity_std_mps**2
        d2_vel = (det.radial_velocity_mps - vr) ** 2 / var_vr
        return d2_pos + d2_vel

    def _update(self, t: _Track, det: Detection) -> None:
        z = np.array(det.xy)
        S = H @ t.P @ H.T + _measurement_cov(det, self.cfg)
        K = t.P @ H.T @ np.linalg.inv(S)
        t.x = t.x + K @ (z - t.x[:2])
        t.P = (np.eye(4) - K @ H) @ t.P
        t.hits += 1
        t.misses = 0
        if t.hits >= self.cfg.confirm_hits:
            t.confirmed = True

    def _start(self, det: Detection) -> None:
        pos = np.array(det.xy)
        u = pos / max(float(np.linalg.norm(pos)), 1e-6)
        tangent = np.array([-u[1], u[0]])
        x = np.concatenate([pos, det.radial_velocity_mps * u])
        P = np.zeros((4, 4))
        P[:2, :2] = _measurement_cov(det, self.cfg)
        P[2:, 2:] = (self.cfg.radial_velocity_std_mps**2 * np.outer(u, u)
                     + self.cfg.initial_tangential_std_mps**2 * np.outer(tangent, tangent))
        self._tracks.append(_Track(id=self._next_id, x=x, P=P))
        self.associations[self._next_id] = det
        self._next_id += 1

    def step(self, detections: list[Detection], timestamp_ns: int) -> None:
        """Advance all tracks to this frame and fold in its detections."""
        if self._last_ns is not None:
            self._predict((timestamp_ns - self._last_ns) / 1e9)
        self._last_ns = timestamp_ns
        self.associations = {}

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        if self._tracks and detections:
            cost = np.array([[self._cost(t, d) for d in detections] for t in self._tracks])
            big = 1e9
            rows, cols = linear_sum_assignment(np.where(cost <= self.cfg.gate_chi2, cost, big))
            for i, j in zip(rows, cols, strict=True):
                if cost[i, j] <= self.cfg.gate_chi2:
                    self._update(self._tracks[i], detections[j])
                    self.associations[self._tracks[i].id] = detections[j]
                    matched_tracks.add(i)
                    matched_dets.add(j)

        survivors = []
        for i, t in enumerate(self._tracks):
            if i not in matched_tracks:
                t.misses += 1
            limit = self.cfg.max_misses if t.confirmed else self.cfg.tentative_misses
            if t.misses < limit:
                survivors.append(t)
        self._tracks = self._drop_duplicates(survivors)
        # New tracks start from the strongest leftover echo in each spot; weaker echoes
        # near it, or near an existing track, are moving parts of the same object.
        leftovers = sorted((d for j, d in enumerate(detections) if j not in matched_dets),
                           key=lambda d: -d.snr_db)
        for det in leftovers:
            if any(self._same_object(det.range_m, det.azimuth_deg, t) for t in self._tracks):
                continue
            self._start(det)

    def _drop_duplicates(self, tracks: list[_Track]) -> list[_Track]:
        """Two tracks at the same spot moving the same way are one object (a body and a
        track that grew on its moving parts): keep the one with more hits. People walking
        past each other move differently, so they are never merged."""
        kept: list[_Track] = []
        for t in sorted(tracks, key=lambda t: (-t.hits, t.id)):
            x, y = float(t.x[0]), float(t.x[1])
            r, az = float(np.hypot(x, y)), float(np.degrees(np.arctan2(x, y)))
            if not any(self._same_object(r, az, k)
                       and np.linalg.norm(t.x[2:] - k.x[2:]) < self.cfg.duplicate_mps
                       for k in kept):
                kept.append(t)
        return sorted(kept, key=lambda t: t.id)

    def _same_object(self, range_m: float, azimuth_deg: float, t: _Track) -> bool:
        x, y = float(t.x[0]), float(t.x[1])
        return (abs(range_m - float(np.hypot(x, y))) < self.cfg.same_object_range_m
                and abs(azimuth_deg - float(np.degrees(np.arctan2(x, y))))
                < self.cfg.same_object_azimuth_deg)


    def states(self, session_id: str, frame_index: int) -> list[TrackState]:
        assert self._last_ns is not None, "call step() first"
        out = []
        for t in self._tracks:
            x, y, vx, vy = (float(v) for v in t.x)
            rng = float(np.hypot(x, y))
            vr, _ = t.radial()
            out.append(TrackState(
                session_id=session_id, frame_index=frame_index, timestamp_ns=self._last_ns,
                track_id=t.id, confirmed=t.confirmed, x_m=x, y_m=y, vx_mps=vx, vy_mps=vy,
                range_m=rng, azimuth_deg=float(np.degrees(np.arctan2(x, y))),
                radial_velocity_mps=vr, speed_mps=float(np.hypot(vx, vy)),
                hits=t.hits, misses=t.misses,
            ))
        return out
