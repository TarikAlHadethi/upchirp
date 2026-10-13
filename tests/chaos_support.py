"""Shared parts of the chaos tests (tests/test_chaos_*.py).

A chaos test acts like many careless users. It builds a random list of steps from a seed,
applies them one by one to a small "world" around one part of the app, and after every step
asks the world which always-true rules are broken (the rules are listed per test file).

A step is a name and plain arguments, so a failing run can be printed and pasted back as a
regression test. When a run fails it is first shrunk to the fewest steps that still fail.

    UPCHIRP_CHAOS_SEQUENCES   how many seeds each test runs (default 5: the fast set, a few
                              seconds; CI runs many more)
"""

import os
from collections.abc import Callable, Sequence
from typing import Any, Protocol

Step = tuple[str, tuple[Any, ...]]


class World(Protocol):
    def apply(self, step: Step) -> None:
        """Do one step. Refusals the app is meant to give are caught here, not raised."""

    def broken(self) -> list[str]:
        """Every rule that does not hold right now, in plain words. Empty means all hold."""


def seeds() -> list[int]:
    return list(range(int(os.environ.get("UPCHIRP_CHAOS_SEQUENCES", "5"))))


def first_failure(make_world: Callable[[], World], steps: Sequence[Step]) -> list[str]:
    """Run the steps on a fresh world. Returns the broken rules at the first step that
    breaks any (a step that raises counts as one), or an empty list."""
    world = make_world()
    for i, step in enumerate(steps):
        try:
            world.apply(step)
            broken = world.broken()
        except Exception as e:  # an unexpected error is itself a broken rule; it is reported
            broken = [f"step raised {type(e).__name__}: {e}"]
        if broken:
            return [f"after step {i} {step!r}: {b}" for b in broken]
    return []


def shrink(make_world: Callable[[], World], steps: Sequence[Step]) -> list[Step]:
    """The fewest steps found that still break a rule: drop chunks, then single steps."""
    steps = list(steps)
    chunk = max(len(steps) // 2, 1)
    while chunk >= 1:
        i = 0
        while i < len(steps):
            shorter = steps[:i] + steps[i + chunk:]
            if first_failure(make_world, shorter):
                steps = shorter
            else:
                i += chunk
        chunk //= 2
    return steps


def check(make_world: Callable[[], World], steps: Sequence[Step], seed: int | None = None) -> None:
    """Fail with the seed, the broken rules and the shortest failing steps."""
    if not first_failure(make_world, steps):
        return
    short = shrink(make_world, steps)
    lines = [f"chaos seed {seed}: a rule broke. Shortest failing steps ({len(short)}):"]
    lines += [f"    {s!r}," for s in short]
    lines += ["Broken:"] + [f"    {b}" for b in first_failure(make_world, short)]
    raise AssertionError("\n".join(lines))
