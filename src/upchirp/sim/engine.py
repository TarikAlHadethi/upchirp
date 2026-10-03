"""FMCW signal simulator with ground truth.

Each target adds a dechirped beat tone to every receive channel:

    s[k, m, n] = A * exp(j*2*pi*(f0*tau_m + S*tau_m*t_n)) * exp(j*2*pi*d*u*k)

tau_m = 2*R/c is the round trip delay at the start of chirp m, t_n is fast
time within the chirp, S is the chirp slope, d is the antenna spacing in
wavelengths and u = x/R is the direction cosine along the array.

The f0*tau term changes from chirp to chirp and gives Doppler. The S*tau term
gives the range tone. Positive radial velocity means moving away.

Amplitude falls as 1/R^2 from a reference of 1 at 10 m for a 1 m^2 target.
Targets beyond the maximum range are dropped, as an IF filter would do.

Swerling fluctuation scales each target's power by a fresh random draw every
frame. Clutter adds still scatterers and, for trees, a few sub-scatterers with
small random radial speeds drawn each frame. Fluctuation and clutter use their
own random stream, so the noise for a given seed does not change.
"""

import zlib
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from upchirp.config import SPEED_OF_LIGHT_MPS, ArrayConfig, ChirpConfig
from upchirp.frame import Frame
from upchirp.sim.micro_doppler import Part, car_body, car_parts, drone_parts, person_parts
from upchirp.sim.scene import Scene, Target

REFERENCE_RANGE_M = 10.0
FOLIAGE_SCATTERERS = 6


def moving_parts(target: Target, t: npt.NDArray[np.float64], vel: npt.NDArray[np.float64],
                 rng: np.random.Generator) -> list[Part]:
    """The target's micro-Doppler parts for these chirp times. Fixed per target (phases,
    rotor speeds) comes from its id, so a scene looks the same on every run."""
    own = np.random.default_rng(zlib.crc32(target.id.encode()))
    speed = float(np.linalg.norm(vel))
    along = aspect(target.position_at(float(t[0])), vel)
    if target.label == "person":
        return person_parts(t, speed, own.uniform(0, 2 * np.pi), along)
    if target.label == "car":
        body = car_extent(target, t, vel) if target.extended else []
        return body + car_parts(t, speed, rng, along)
    return drone_parts(t, own)


def aspect(pos: npt.NDArray[np.float64], vel: npt.NDArray[np.float64]) -> float:
    """|cos| of the angle between the direction of travel and the line of sight:
    1 coming straight at the radar or going away, 0 crossing the view."""
    speed = float(np.linalg.norm(vel))
    if speed < 1e-9:
        return 0.0
    return abs(float(vel @ pos)) / (speed * float(np.linalg.norm(pos)))


CAR_LENGTH_M, CAR_WIDTH_M = 4.5, 1.8


def range_extent(target: Target, pos: npt.NDArray[np.float64],
                 vel: npt.NDArray[np.float64]) -> float:
    """How deep in range the target's body looks to the radar: 0 for a point target, else
    a car's length and width projected on the line of sight."""
    if not (target.extended and target.micro_doppler and target.label == "car"):
        return 0.0
    los = pos / np.linalg.norm(pos)
    speed = float(np.linalg.norm(vel))
    heading = vel / speed if speed > 0.1 else np.array([1.0, 0.0, 0.0])
    along = abs(float(heading @ los))
    return float(CAR_LENGTH_M * along + CAR_WIDTH_M * np.sqrt(max(0.0, 1 - along**2)))


def car_extent(target: Target, t: npt.NDArray[np.float64],
               vel: npt.NDArray[np.float64]) -> list[Part]:
    """Spots along the car's body, spread over its length and width as seen by the radar."""
    extent = range_extent(target, target.position_at(float(t[0])), vel)
    return [Part(np.full(t.shape, p.offsets_m[0]), p.rcs_fraction) for p in car_body(extent)]


def fluctuation(swerling: int, rng: np.random.Generator) -> float:
    """Power multiplier with mean 1 for one frame."""
    if swerling == 1:
        return float(rng.exponential(1.0))
    if swerling == 3:
        return float(rng.gamma(2.0, 0.5))
    return 1.0


@dataclass(frozen=True)
class TruthRow:
    """Where one target really was at the start of one frame."""

    session_id: str
    frame_index: int
    timestamp_ns: int
    target_id: str
    label: str
    x_m: float
    y_m: float
    z_m: float
    range_m: float
    radial_velocity_mps: float
    azimuth_deg: float
    rcs_m2: float
    in_view: bool
    # Depth of the body in range as the radar sees it (0 for a point target): a detection
    # anywhere on it is on target (decision 0013)
    extent_m: float = 0.0


class Simulator:
    def __init__(
        self,
        scene: Scene,
        session_id: str,
        start_ns: int,
        chirp: ChirpConfig | None = None,
        array: ArrayConfig | None = None,
        seed: int = 0,
    ) -> None:
        self.scene = scene
        self.session_id = session_id
        self.start_ns = start_ns
        self.chirp = chirp or ChirpConfig()
        self.array = array or ArrayConfig()
        self.seed = seed
        if self.chirp.frame_duration_s > scene.frame_period_s:
            raise ValueError("frame period is shorter than one frame of chirps")

    def run(self) -> Iterator[tuple[Frame, list[TruthRow]]]:
        """Yield each frame with the ground truth for every target in the scene."""
        rng = np.random.default_rng(self.seed)
        world = np.random.default_rng([self.seed, 1])  # fluctuation and clutter
        c = self.chirp
        shape = (self.array.n_rx, c.n_chirps, c.n_samples)
        fast_time = np.arange(c.n_samples) / c.sample_rate_hz
        chirp_starts = np.arange(c.n_chirps) * c.chirp_duration_s
        rx_index = np.arange(self.array.n_rx)

        def add_return(cube: npt.NDArray[np.complex128], ranges: npt.NDArray[np.float64],
                       u: float, amplitude: float, phase0: float = 0.0) -> None:
            """Add one point scatterer: its range at each chirp start, direction, amplitude."""
            tau = 2 * ranges / SPEED_OF_LIGHT_MPS
            phase = c.f_start_hz * tau[:, None] + c.slope_hz_per_s * tau[:, None] * fast_time
            spatial = np.exp(2j * np.pi * self.array.spacing_wavelengths * u * rx_index)
            cube += (amplitude * np.exp(1j * phase0) * spatial[:, None, None]
                     * np.exp(2j * np.pi * phase)[None])

        for i in range(self.scene.n_frames):
            t0 = i * self.scene.frame_period_s
            timestamp_ns = self.start_ns + round(t0 * 1e9)
            std = self.scene.noise_std / np.sqrt(2)
            cube = rng.normal(0, std, shape) + 1j * rng.normal(0, std, shape)
            truth: list[TruthRow] = []

            for target in self.scene.targets:
                pos0 = target.position_at(t0)
                vel = target.velocity_at(t0)
                r0 = float(np.linalg.norm(pos0))
                radial_v = float(pos0 @ vel / r0)
                u = pos0[0] / r0
                in_view = (
                    target.active(t0)
                    and c.range_bin_m <= r0 < c.max_range_m
                    and abs(radial_v) < c.max_velocity_mps
                )
                truth.append(TruthRow(
                    session_id=self.session_id, frame_index=i, timestamp_ns=timestamp_ns,
                    target_id=target.id, label=target.label,
                    x_m=float(pos0[0]), y_m=float(pos0[1]), z_m=float(pos0[2]),
                    range_m=r0, radial_velocity_mps=radial_v,
                    azimuth_deg=float(np.degrees(np.arcsin(u))),
                    rcs_m2=target.rcs_m2, in_view=in_view,
                    extent_m=range_extent(target, pos0, vel),
                ))
                if not target.active(t0) or r0 >= c.max_range_m:
                    continue

                ranges = np.linalg.norm(target.position_at(t0 + chirp_starts), axis=-1)
                power = target.rcs_m2 * fluctuation(target.swerling, world)
                body_amp = np.sqrt(power) * (REFERENCE_RANGE_M / r0) ** 2
                add_return(cube, ranges, u, body_amp)
                if target.micro_doppler:
                    t_abs = np.asarray(t0 + chirp_starts, dtype=np.float64)
                    for part in moving_parts(target, t_abs, vel, world):
                        add_return(cube, ranges + part.offsets_m, u,
                                   body_amp * np.sqrt(part.rcs_fraction),
                                   world.uniform(0, 2 * np.pi))

            for item in self.scene.clutter:
                pos = np.asarray(item.position_m)
                r = float(np.linalg.norm(pos))
                if r >= c.max_range_m:
                    continue
                u = float(pos[0] / r)
                amplitude = np.sqrt(item.rcs_m2) * (REFERENCE_RANGE_M / r) ** 2
                if item.spread_mps == 0:
                    add_return(cube, np.full(c.n_chirps, r), u, amplitude)
                    continue
                for v in world.normal(0.0, item.spread_mps, FOLIAGE_SCATTERERS):
                    add_return(cube, r + v * chirp_starts, u,
                               amplitude / np.sqrt(FOLIAGE_SCATTERERS),
                               world.uniform(0, 2 * np.pi))

            frame = Frame.from_cube(
                cube,
                source="sim",
                session_id=self.session_id,
                frame_index=i,
                timestamp_ns=timestamp_ns,
                chirp_config_id=c.id,
                stage="raw",
                meta={"scene": self.scene.name},
            )
            yield frame, truth
