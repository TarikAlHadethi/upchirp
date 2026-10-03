"""Check agent answers against ground truth.

Expected answers come straight from the simulator's ground truth, never from
the agent's tools, so a wrong tool or a wrong pipeline shows up as a wrong answer.
"""

import re
from dataclasses import dataclass

from upchirp.sim.engine import TruthRow

NUMBER_WORDS = {
    "no": 0, "zero": 0, "none": 0, "one": 1, "a single": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass(frozen=True)
class DroneTruth:
    count: int
    closest_range_m: float | None


def drone_truth(truth: list[TruthRow], last_minutes: float | None = None) -> DroneTruth:
    """How many drone-like targets were in view in the window, and their closest range."""
    rows = [t for t in truth if t.in_view]
    if last_minutes is not None and rows:
        end = max(t.timestamp_ns for t in rows)
        rows = [t for t in rows if t.timestamp_ns >= end - last_minutes * 60e9]
    drones = [t for t in rows if t.label == "drone_like"]
    return DroneTruth(
        count=len({t.target_id for t in drones}),
        closest_range_m=min((t.range_m for t in drones), default=None),
    )


def numbers_in(text: str) -> list[float]:
    found = [float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text)]
    lowered = text.lower()
    for word, value in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            found.append(float(value))
    return found


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: tuple[str, ...]


def check_drone_answer(answer: str, expected: DroneTruth, range_tol_m: float = 1.5) -> Verdict:
    """The answer must state the right count and, if any, the closest range within tolerance."""
    nums = numbers_in(answer)
    reasons = []
    if float(expected.count) not in nums:
        reasons.append(f"count {expected.count} not stated")
    if expected.closest_range_m is not None and not any(
        abs(n - expected.closest_range_m) <= range_tol_m for n in nums
    ):
        reasons.append(f"closest range {expected.closest_range_m:.1f} m not stated")
    return Verdict(ok=not reasons, reasons=tuple(reasons))
