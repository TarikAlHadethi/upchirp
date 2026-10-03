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


SCENES = {"default": default_scene, "crossing": crossing_scene, "tree-hide": tree_hide_scene}


def get_scene(name: str) -> Scene:
    try:
        return SCENES[name]()
    except KeyError:
        known = ", ".join(sorted(SCENES))
        raise ValueError(f"unknown scene '{name}'; known scenes: {known}") from None
