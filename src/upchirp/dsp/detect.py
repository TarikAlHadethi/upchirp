"""Frame to detections: range-Doppler map, CFAR, sub-bin refinement, angle."""

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from upchirp.config import ArrayConfig, ChirpConfig
from upchirp.dsp.cfar import CfarConfig, detect_peaks
from upchirp.dsp.clutter import ClutterMap
from upchirp.dsp.rdmap import azimuth_deg, doppler_fft, range_fft
from upchirp.frame import Frame


@dataclass(frozen=True)
class Detection:
    session_id: str
    frame_index: int
    timestamp_ns: int
    range_m: float
    radial_velocity_mps: float
    azimuth_deg: float
    snr_db: float
    range_bin: int
    doppler_bin: int

    @property
    def xy(self) -> tuple[float, float]:
        """Position in the radar plane: x along the array, y = range * cos(azimuth)."""
        az = np.radians(self.azimuth_deg)
        return float(self.range_m * np.sin(az)), float(self.range_m * np.cos(az))


def _parabolic_offset(left: float, mid: float, right: float) -> float:
    """Sub-bin peak offset from three log-power samples, in -0.5 to 0.5."""
    denom = left - 2 * mid + right
    if denom >= 0:
        return 0.0
    return float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5))


@dataclass
class Detector:
    chirp: ChirpConfig
    array: ArrayConfig
    cfar: CfarConfig = field(default_factory=CfarConfig)
    clutter_map: ClutterMap | None = field(default_factory=ClutterMap)
    # Echoes from one object's moving parts (limbs, wheels, rotors) share its range and
    # angle but not its speed. By default every echo is kept and the tracker picks the
    # one that fits each track (decision 0012); merge_range_bins >= 0 instead keeps only
    # the strongest of each group, which picks a blade over a fading drone body.
    merge_range_bins: int | None = None
    merge_azimuth_deg: float = 8.0
    # An extended object (a 4.5 m car) gives echoes at the same speed spread over its
    # length, often just its two ends, about 3 m apart. Same-speed echoes that fit within
    # cluster_span_m (a car length plus one range cell) become one detection at their
    # power-weighted centre: within cluster_gap_m of the group at a similar angle, or
    # further along it at nearly the same angle. Seen side on, a car is only about 2 m
    # deep (cluster_side_gap_m). It only looks longer than that when it moves along the
    # line of sight, so the long form also needs a clear radial speed: two people walking
    # across the view past each other (3 m apart in the crossing scene) line up for a
    # moment at the same near-zero speed, and stay apart. Limbs and wheels move at other
    # speeds, so they stay separate too (decisions 0012 and 0013).
    cluster: bool = True
    cluster_span_m: float = 5.5
    cluster_gap_m: float = 1.2
    cluster_side_gap_m: float = 2.5
    cluster_body_azimuth_deg: float = 2.5
    cluster_body_min_speed_mps: float = 1.0
    cluster_azimuth_deg: float = 10.0
    cluster_speed_mps: float = 0.6
    last_power: npt.NDArray[Any] | None = field(default=None, repr=False)

    def power_map(self, frame: Frame) -> tuple[npt.NDArray[np.complex128], npt.NDArray[Any]]:
        cube = frame.cube()
        rng = range_fft(cube) if frame.stage == "raw" else cube.astype(np.complex128)
        if self.clutter_map is not None:
            rng = self.clutter_map.apply(rng)
        rd = doppler_fft(rng)
        return rd, (np.abs(rd) ** 2).sum(axis=0)

    def clustered(self, detections: list[Detection]) -> list[Detection]:
        if not self.cluster or len(detections) < 2:
            return detections
        # Strongest echo first; each group takes the same-speed echoes nearest to it in
        # range, as long as the group still fits in one object's length.
        left = sorted(detections, key=lambda d: -d.snr_db)
        groups: dict[int, list[Detection]] = {}
        while left:
            seed = left.pop(0)
            members = [seed]
            moving = abs(seed.radial_velocity_mps) >= self.cluster_body_min_speed_mps
            for d in sorted(left, key=lambda d: abs(d.range_m - seed.range_m)):
                span = (max(m.range_m for m in [*members, d])
                        - min(m.range_m for m in [*members, d]))
                gap = min(abs(d.range_m - m.range_m) for m in members)
                near = gap <= self.cluster_gap_m
                if not (near or moving or span <= self.cluster_side_gap_m):
                    continue
                max_az = self.cluster_azimuth_deg if near else self.cluster_body_azimuth_deg
                if (span <= self.cluster_span_m
                        and abs(d.azimuth_deg - seed.azimuth_deg) <= max_az
                        and abs(d.radial_velocity_mps - seed.radial_velocity_mps)
                        <= self.cluster_speed_mps):
                    members.append(d)
            left = [d for d in left if not any(d is m for m in members)]
            groups[len(groups)] = members
        out = []
        for members in groups.values():
            if len(members) == 1:
                out.append(members[0])
                continue
            w = np.array([10 ** (d.snr_db / 10) for d in members])
            strongest = members[int(np.argmax(w))]
            out.append(dataclasses.replace(
                strongest,
                range_m=float(np.average([d.range_m for d in members], weights=w)),
                azimuth_deg=float(np.average([d.azimuth_deg for d in members], weights=w)),
                snr_db=float(10 * np.log10(w.sum())),
            ))
        return out

    def merge(self, detections: list[Detection]) -> list[Detection]:
        if self.merge_range_bins is None:
            return detections
        kept: list[Detection] = []
        for det in sorted(detections, key=lambda d: -d.snr_db):
            if not any(abs(det.range_bin - k.range_bin) <= self.merge_range_bins
                       and abs(det.azimuth_deg - k.azimuth_deg) <= self.merge_azimuth_deg
                       for k in kept):
                kept.append(det)
        return kept

    def detect(self, frame: Frame) -> list[Detection]:
        rd, power = self.power_map(frame)
        if self.chirp.max_range_bin is not None:
            power = power.copy()
            power[:, self.chirp.max_range_bin:] = np.median(power[:, :self.chirp.max_range_bin])
        self.last_power = power  # kept for the live view
        if self.clutter_map is not None and not self.clutter_map.ready:
            self.clutter_map.learn(power, np.zeros(power.shape, dtype=bool))
            return []  # still learning the empty scene
        log_p = 10 * np.log10(power + 1e-30)
        floor_db = float(np.median(log_p))
        n_dop, n_rng = power.shape
        out = []
        floor = self.clutter_map.floor() if self.clutter_map is not None else None
        peaks = detect_peaks(power, self.cfar, floor)
        if self.clutter_map is not None:
            busy = np.zeros(power.shape, dtype=bool)
            for d, r in peaks:
                busy[max(d - 2, 0):d + 3, max(r - 2, 0):r + 3] = True
            self.clutter_map.learn(power, busy)
        for d, r in peaks:
            dr = _parabolic_offset(*(log_p[d, i] for i in (r - 1, r, min(r + 1, n_rng - 1))))
            dd = _parabolic_offset(*(log_p[i % n_dop, r] for i in (d - 1, d, d + 1)))
            out.append(Detection(
                session_id=frame.session_id,
                frame_index=frame.frame_index,
                timestamp_ns=frame.timestamp_ns,
                range_m=(r + dr) * self.chirp.range_bin_m,
                radial_velocity_mps=(d + dd - n_dop // 2) * self.chirp.velocity_bin_mps,
                azimuth_deg=azimuth_deg(rd, d, r, self.array.spacing_wavelengths),
                snr_db=float(log_p[d, r]) - floor_db,
                range_bin=r,
                doppler_bin=d,
            ))
        return self.merge(self.clustered(out))
