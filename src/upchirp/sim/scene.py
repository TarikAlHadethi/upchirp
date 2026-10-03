"""Scenes: targets in front of the radar, plus the clutter around them.

Coordinates: the radar sits at the origin and faces +y. x points right,
z points up. Units are metres, seconds and square metres.

Targets move in straight lines, optionally with a sinusoidal wobble (a hovering
drone bobs). Their echo strength can fluctuate from frame to frame following the
Swerling models: 0 steady, 1 and 3 fluctuating (exponential and chi-square with
4 degrees of freedom in power, mean 1). Clutter is everything that is not a
target: walls and posts (still) and trees (leaves moving, so a small Doppler spread).
"""

from typing import Literal, Self

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Literal["person", "car", "drone_like"]
Vec3 = tuple[float, float, float]


class Target(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: Label
    position_m: Vec3
    velocity_mps: Vec3 = (0.0, 0.0, 0.0)
    rcs_m2: float = Field(gt=0)
    start_s: float = 0.0
    end_s: float | None = None
    swerling: Literal[0, 1, 3] = 0
    wobble_m: Vec3 = (0.0, 0.0, 0.0)  # amplitude of a sinusoidal wobble per axis
    wobble_period_s: float = Field(default=4.0, gt=0)
    micro_doppler: bool = False  # limbs, wheels or rotors (sim/micro_doppler.py)
    # body spread over its real size (a car's 4.5 m): on for the car driving away in the
    # crossing scene and for classifier patches; off for the default scene's car, whose
    # body hides the drone flying low over it (decisions 0012 and 0013)
    extended: bool = False

    def active(self, t: float) -> bool:
        return t >= self.start_s and (self.end_s is None or t < self.end_s)

    def position_at(self, t: npt.ArrayLike) -> npt.NDArray[np.float64]:
        """Position at scene time t. Returns shape t.shape + (3,)."""
        dt = np.asarray(t, dtype=np.float64)[..., None] - self.start_s
        phase = 2 * np.pi * dt / self.wobble_period_s
        pos: npt.NDArray[np.float64] = (
            np.asarray(self.position_m) + dt * np.asarray(self.velocity_mps)
            + np.sin(phase) * np.asarray(self.wobble_m)
        )
        return pos

    def velocity_at(self, t: float) -> npt.NDArray[np.float64]:
        w = 2 * np.pi / self.wobble_period_s
        vel: npt.NDArray[np.float64] = np.asarray(self.velocity_mps) + w * np.cos(
            w * (t - self.start_s)) * np.asarray(self.wobble_m)
        return vel


class Clutter(BaseModel):
    """A fixed scatterer. spread_mps > 0 models moving parts, such as leaves in wind."""

    model_config = ConfigDict(frozen=True)

    id: str
    position_m: Vec3
    rcs_m2: float = Field(gt=0)
    spread_mps: float = Field(default=0.0, ge=0)


class Scene(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    duration_s: float = Field(gt=0)
    frame_period_s: float = Field(gt=0)
    noise_std: float = Field(default=0.01, ge=0)
    targets: tuple[Target, ...]
    clutter: tuple[Clutter, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [t.id for t in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("target ids must be unique")
        return self

    @property
    def n_frames(self) -> int:
        return int(round(self.duration_s / self.frame_period_s))


# A courtyard: building walls, a lamp post, two trees whose leaves move, and the ground
# just in front of the radar. Shared by the scenes below.
COURTYARD_CLUTTER = (
    Clutter(id="building", position_m=(20.0, 70.0, 0.0), rcs_m2=50.0),
    Clutter(id="wall", position_m=(-25.0, 45.0, 0.0), rcs_m2=30.0),
    Clutter(id="lamp-post", position_m=(3.0, 12.0, 0.0), rcs_m2=2.0),
    Clutter(id="tree-1", position_m=(-12.0, 30.0, 0.0), rcs_m2=3.0, spread_mps=0.15),
    Clutter(id="tree-2", position_m=(18.0, 55.0, 0.0), rcs_m2=3.0, spread_mps=0.15),
    Clutter(id="ground", position_m=(0.0, 5.0, -1.5), rcs_m2=1.0),
)
QUIET_START_S = 2.0  # empty courtyard first, so the clutter map can learn it


def default_scene() -> Scene:
    """Two people walking, a car crossing, and a drone-like target closing in, in a courtyard."""
    t0 = QUIET_START_S
    return Scene(
        name="default",
        duration_s=10.0 + t0,
        frame_period_s=0.1,
        clutter=COURTYARD_CLUTTER,
        targets=(
            Target(id="person-1", label="person", position_m=(-5.0, 15.0, 0.0),
                   velocity_mps=(1.2, 0.3, 0.0), rcs_m2=1.0, swerling=1, start_s=t0,
                   micro_doppler=True),
            Target(id="person-2", label="person", position_m=(6.0, 25.0, 0.0),
                   velocity_mps=(-0.5, -1.0, 0.0), rcs_m2=1.0, swerling=1, start_s=t0,
                   micro_doppler=True),
            Target(id="car-1", label="car", position_m=(-30.0, 50.0, 0.0),
                   velocity_mps=(8.0, 0.0, 0.0), rcs_m2=10.0, swerling=3, start_s=t0,
                   micro_doppler=True),
            Target(id="drone-1", label="drone_like", position_m=(10.0, 60.0, 20.0),
                   velocity_mps=(-2.0, -4.0, 0.0), rcs_m2=0.01, swerling=1, start_s=t0,
                   micro_doppler=True),
        ),
    )


def crossing_scene() -> Scene:
    """Harder case: two people cross paths, a drone-like target hovers, a car drives away.

    The people pass within 3 m of each other, moving across the radar's view. The
    hovering target bobs by tens of centimetres, as real hovering drones do.
    """
    t0 = QUIET_START_S
    return Scene(
        name="crossing",
        duration_s=12.0 + t0,
        frame_period_s=0.1,
        clutter=COURTYARD_CLUTTER,
        targets=(
            Target(id="person-a", label="person", position_m=(-8.0, 19.0, 0.0),
                   velocity_mps=(1.4, 0.0, 0.0), rcs_m2=1.0, swerling=1, start_s=t0,
                   micro_doppler=True),
            Target(id="person-b", label="person", position_m=(8.0, 22.0, 0.0),
                   velocity_mps=(-1.4, 0.0, 0.0), rcs_m2=1.0, swerling=1, start_s=t0,
                   micro_doppler=True),
            Target(id="drone-hover", label="drone_like", position_m=(-12.0, 40.0, 15.0),
                   rcs_m2=0.01, swerling=1, start_s=t0, micro_doppler=True,
                   wobble_m=(0.4, 0.3, 0.2), wobble_period_s=3.0),
            Target(id="car-away", label="car", position_m=(5.0, 25.0, 0.0),
                   velocity_mps=(1.0, 7.0, 0.0), rcs_m2=10.0, swerling=3, start_s=t0 + 2.0,
                   micro_doppler=True, extended=True),
        ),
    )


def tree_hide_scene() -> Scene:
    """Known limitation (decision 0010): a drone hovering 1.7 m beyond a tree with moving
    leaves, at nearly zero speed. Two receive channels cannot pull it out of the tree."""
    t0 = QUIET_START_S
    return Scene(
        name="tree-hide",
        duration_s=8.0 + t0,
        frame_period_s=0.1,
        clutter=(Clutter(id="tree", position_m=(15.0, 40.0, 0.0), rcs_m2=3.0, spread_mps=0.15),),
        targets=(
            Target(id="drone-hidden", label="drone_like", position_m=(-12.0, 40.0, 15.0),
                   rcs_m2=0.01, swerling=1, start_s=t0,
                   wobble_m=(0.4, 0.3, 0.2), wobble_period_s=3.0),
        ),
    )


def courtyard_scene(minutes: float = 15.0, seed: int = 7) -> Scene:
    """A long, busy courtyard for the live demo and long-run evals: people walking through
    about every 45 s, cars on the road behind about every 75 s, and four drone-like
    targets (two crossing, two hovering for a while). The schedule comes from `seed`, so
    the scene and its ground truth are the same every time.

    Long enough that "the last 10 minutes" means something; it is simulated live, frame
    by frame, so nothing has to be stored. Hovering drones are kept 10 m or more from trees
    and walls: a drone hovering beside clutter is a known limit with its own scene, and
    people do not walk through tree trunks.
    """
    # one random stream per kind of target, so changing one never reshuffles the others
    rng = np.random.default_rng([seed, 1])
    t0, end = QUIET_START_S, minutes * 60.0
    targets: list[Target] = []

    t, n = t0 + 3.0, 0
    while t < end - 30:
        n += 1
        speed = float(rng.uniform(1.1, 1.6))
        trees = [c.position_m for c in COURTYARD_CLUTTER if c.spread_mps > 0]
        if rng.random() < 0.7:  # across the view, not through a tree trunk
            y = float(rng.uniform(14, 40))
            while any(abs(y - ty) < 2.0 for _, ty, _ in trees):
                y = float(rng.uniform(14, 40))
            side = min(18.0, 0.9 * y)
            sign = 1.0 if rng.random() < 0.5 else -1.0
            start, vel, dur = (-sign * side, y, 0.0), (sign * speed, 0.0, 0.0), 2 * side / speed
        else:  # towards the radar or away from it
            x = float(rng.uniform(-8, 8))
            while any(abs(x - tx) < 2.0 and 12 <= ty <= 42 for tx, ty, _ in trees):
                x = float(rng.uniform(-8, 8))
            toward = rng.random() < 0.5
            start = (x, 42.0 if toward else 12.0, 0.0)
            vel, dur = (0.0, -speed if toward else speed, 0.0), 30 / speed
        targets.append(Target(id=f"person-{n}", label="person", position_m=start,
                              velocity_mps=vel, rcs_m2=1.0, swerling=1, start_s=t,
                              end_s=min(t + dur, end), micro_doppler=True))
        t += float(rng.uniform(30, 60))

    car_rng = np.random.default_rng([seed, 2])
    t, n = t0 + 20.0, 0
    while t < end - 20:
        n += 1
        speed = float(car_rng.uniform(6, 10))
        sign = 1.0 if car_rng.random() < 0.5 else -1.0
        targets.append(Target(id=f"car-{n}", label="car",
                              position_m=(-sign * 45.0, float(car_rng.uniform(52, 62)), 0.0),
                              velocity_mps=(sign * speed, 0.0, 0.0), rcs_m2=10.0, swerling=3,
                              start_s=t, end_s=min(t + 90 / speed, end), micro_doppler=True,
                              extended=True))
        t += float(car_rng.uniform(50, 100))

    drone_rng = np.random.default_rng([seed, 3])
    for n, minute in enumerate((1.5, 5.0, 9.0, 12.5), start=1):
        t = minute * 60
        if t >= end - 30:
            break
        alt = float(drone_rng.uniform(12, 25))
        if n % 2:  # crossing high over the courtyard
            sign = 1.0 if drone_rng.random() < 0.5 else -1.0
            targets.append(Target(
                id=f"drone-{n}", label="drone_like", position_m=(-sign * 35.0, 75.0, alt),
                velocity_mps=(sign * 2.5, -2.0, 0.0), rcs_m2=0.01, swerling=1, start_s=t,
                end_s=t + 24.0, micro_doppler=True))
        else:  # hovering for a minute, bobbing; not beside a tree or wall (that limit is
            # the tree-hide scene's, decision 0010: here it would hide the drone for the minute)
            while True:
                x, y = float(drone_rng.uniform(-15, 15)), float(drone_rng.uniform(35, 60))
                if all(np.hypot(x - c.position_m[0], y - c.position_m[1]) > 10
                       for c in COURTYARD_CLUTTER):
                    break
            targets.append(Target(
                id=f"drone-{n}", label="drone_like", position_m=(x, y, alt),
                rcs_m2=0.01, swerling=1, start_s=t, end_s=t + 60.0, micro_doppler=True,
                wobble_m=(0.4, 0.3, 0.2), wobble_period_s=3.0))

    return Scene(name="courtyard", duration_s=end, frame_period_s=0.1,
                 clutter=COURTYARD_CLUTTER, targets=tuple(targets))


SCENES = {"default": default_scene, "crossing": crossing_scene, "tree-hide": tree_hide_scene,
          "courtyard": courtyard_scene}


def get_scene(name: str) -> Scene:
    try:
        return SCENES[name]()
    except KeyError:
        known = ", ".join(sorted(SCENES))
        raise ValueError(f"unknown scene '{name}'; known scenes: {known}") from None
