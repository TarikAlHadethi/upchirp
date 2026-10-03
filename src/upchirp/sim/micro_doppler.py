"""Micro-Doppler: the moving parts of a target, added as extra point scatterers.

A real target is not one point. A walking person's arms and legs swing, a car's
wheels turn (the top of a tyre moves at twice the car's speed, the contact patch
not at all), and a drone's rotor blades spin. These parts spread the echo over
speed, and that spread is what a classifier recognises (decision 0011).

Each part is returned as its offset along the line of sight at each chirp time,
relative to the body, and its share of the target's radar cross section. The
models are textbook simplifications (sinusoidal limb swing, uniform tyre points,
rotating blade tips), not biomechanics.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Part:
    offsets_m: Array  # [n_chirps] extra range along the line of sight
    rcs_fraction: float


def person_parts(t: Array, speed_mps: float, phase0: float) -> list[Part]:
    """Two legs and two arms swinging at the gait rate (about 1.8 Hz at walking pace)."""
    if speed_mps < 0.2:
        return []
    gait_hz = 0.9 + 0.65 * speed_mps
    w = 2 * np.pi * gait_hz
    parts = []
    # limbs together carry about a tenth of the torso's echo (about 10 dB below it)
    for amp_ratio, rcs, phase in ((1.2, 0.035, 0.0), (1.2, 0.035, np.pi),   # legs
                                  (0.7, 0.015, np.pi), (0.7, 0.015, 0.0)):  # arms
        amp_v = amp_ratio * speed_mps  # peak speed of the limb relative to the body
        parts.append(Part(-(amp_v / w) * np.cos(w * t + phase + phase0), rcs))
    return parts


def car_body(extent_m: float) -> list[Part]:
    """A car is not a point: bright spots spread along its length as seen by the radar."""
    return [Part(np.full(1, offset), 0.4) for offset in np.linspace(-extent_m / 2,
                                                                     extent_m / 2, 5)]


def car_parts(t: Array, speed_mps: float, rng: np.random.Generator) -> list[Part]:
    """Points on the visible tyres, moving at between 0 and 2 times the car's speed."""
    if speed_mps < 0.5:
        return []
    radius = 0.32
    w = speed_mps / radius
    parts = []
    for _ in range(6):
        angle = rng.uniform(0, 2 * np.pi)
        # tread point: forward speed v(1 - cos(angle)) relative to the ground, i.e.
        # -v cos(angle) relative to the body; along the line of sight, scaled by 0.7
        parts.append(Part(0.7 * radius * np.sin(w * t + angle), 0.01))
    return parts


def drone_parts(t: Array, rng: np.random.Generator, n_rotors: int = 4) -> list[Part]:
    """Two-bladed rotors spinning at about 100 Hz; blade tips at about 12 cm."""
    parts = []
    for _ in range(n_rotors):
        rev_hz = rng.uniform(90, 110)
        phase = rng.uniform(0, 2 * np.pi)
        tilt = rng.uniform(0.3, 0.9)  # how much of the blade's motion is along the line of sight
        for blade in (0.0, np.pi):
            parts.append(Part(0.12 * tilt * np.sin(2 * np.pi * rev_hz * t + phase + blade), 0.15))
    return parts
