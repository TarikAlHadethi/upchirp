"""Chaos tests for the public demo limits: the question guard, live viewer counts and the
live fan-out. No database and no model; the guard's clock is a fake one.

Rules:
- money held equals questions in flight times the reserve, and is never negative
- a question gets in only if spent + held + one reserve fits under the daily cap
- a visitor gets at most `per_minute` questions in 60 seconds and `per_day` in 24 hours
- a refused question changes nothing
- spend is booked on the UTC day the answer finished
- the live viewer count equals the open connections, and the cap per address holds
- a slow viewer's queue never passes 30 messages and always ends with the newest
"""

import asyncio
import contextlib
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from chaos_support import Step, check, seeds

pytest.importorskip("fastapi")
pytest.importorskip("confluent_kafka")

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from upchirp.api import guard as guard_module
from upchirp.api.app import Broadcaster, create_app
from upchirp.api.guard import Limited, PublicGuard

PER_MINUTE, PER_DAY, CAP, RESERVE = 3, 8, 1.0, 0.10
CLOCK = SimpleNamespace(now=0.0)
NEAR = 1e-9  # sums of cents are not exact in floating point


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).date().isoformat()


class GuardWorld:
    def __init__(self) -> None:
        CLOCK.now = 1_800_000_000.0 + 86_400 - 30  # half a minute before midnight UTC
        self.guard = PublicGuard(PER_MINUTE, PER_DAY, CAP, RESERVE)
        self.in_flight = 0
        self.hits: dict[str, list[float]] = {}
        self.spent: dict[str, float] = {}
        self.problems: list[str] = []

    def _expected(self, visitor: str) -> set[int]:
        """Statuses the rules allow for a question from this visitor right now (0 = let in)."""
        hits = [t for t in self.hits.get(visitor, []) if t >= CLOCK.now - 86_400]
        if sum(1 for t in hits if t > CLOCK.now - 60) >= PER_MINUTE or len(hits) >= PER_DAY:
            return {429}
        need = self.spent.get(_day(CLOCK.now), 0.0) + self.in_flight * RESERVE + RESERVE
        if abs(need - CAP) < NEAR:
            return {0, 503}
        return {503} if need > CAP else {0}

    def apply(self, step: Step) -> None:
        name, args = step
        if name == "wait":
            CLOCK.now += args[0]
        elif name == "ask":
            visitor = args[0]
            expected = self._expected(visitor)
            held, known = self.guard.reserved, len(self.guard.hits[visitor])
            try:
                self.guard.check(visitor)
                status = 0
            except Limited as e:
                status = e.status
                kept = sum(1 for t in self.hits.get(visitor, []) if t >= CLOCK.now - 86_400)
                now_known = len(self.guard.hits[visitor])  # old hits may have aged out
                if self.guard.reserved != held or now_known not in (known, kept):
                    self.problems.append("a refused question changed the guard")
            if status not in expected:
                self.problems.append(f"question got {status}, the rules allow {sorted(expected)}")
            if status == 0:
                self.in_flight += 1
                self.hits.setdefault(visitor, []).append(CLOCK.now)
        elif self.in_flight:  # "finish" with its real cost, or "fail" with the reserve
            cost = args[0] / 100 if name == "finish" else RESERVE
            self.guard.record(10, 10, cost)
            self.in_flight -= 1
            day = _day(CLOCK.now)
            self.spent[day] = self.spent.get(day, 0.0) + cost

    def broken(self) -> list[str]:
        out = list(self.problems)
        if abs(self.guard.reserved - self.in_flight * RESERVE) > NEAR or self.guard.reserved < 0:
            out.append(f"{self.guard.reserved:.4f} held for {self.in_flight} questions in flight")
        today = self.spent.get(_day(CLOCK.now), 0.0)
        if abs(self.guard.spent_today() - today) > NEAR:
            out.append(f"spent today is {self.guard.spent_today():.4f}, booked {today:.4f}")
        return out


def _guard_steps(seed: int, n: int = 120) -> list[Step]:
    rng = random.Random(seed)
    steps: list[Step] = []
    for _ in range(n):
        kind = rng.choice(["ask"] * 6 + ["finish"] * 3 + ["fail", "wait", "wait"])
        if kind == "ask":
            steps.append(("ask", (rng.choice(["a", "a", "b", "c", "d", "e", "f"]),)))
        elif kind == "finish":
            steps.append(("finish", (rng.choice([0, 1, 2, 5, 10, 10, 25]),)))
        elif kind == "fail":
            steps.append(("fail", ()))
        else:
            steps.append(("wait", (rng.choice([1, 20, 59, 60, 61, 3_600, 86_399, 86_400]),)))
    return steps


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    monkeypatch.setattr(guard_module, "time", SimpleNamespace(time=lambda: CLOCK.now))
    monkeypatch.setattr(guard_module, "_today", lambda: _day(CLOCK.now))


@pytest.mark.parametrize("seed", seeds())
def test_public_guard_keeps_its_rules_under_chaos(seed: int, fake_clock: None) -> None:
    check(GuardWorld, _guard_steps(seed), seed)


class FanOutWorld:
    def __init__(self) -> None:
        self.b = Broadcaster()
        self.queues: list[asyncio.Queue[str]] = []
        self.count = 0
        self.just_sent = False  # the last step was a message

    def apply(self, step: Step) -> None:
        name, args = step
        self.just_sent = name == "message"
        if name == "join":
            q: asyncio.Queue[str] = asyncio.Queue(maxsize=30)
            self.queues.append(q)
            self.b.clients.add(q)
        elif name == "message":
            self.count += 1
            self.b._fan_out(str(self.count))
        elif self.queues and name == "leave":
            self.b.clients.discard(self.queues.pop(args[0] % len(self.queues)))
        elif self.queues:  # "read": a viewer takes some messages
            q = self.queues[args[0] % len(self.queues)]
            for _ in range(min(args[1], q.qsize())):
                q.get_nowait()

    def broken(self) -> list[str]:
        out = []
        if self.b.clients != set(self.queues):
            out.append("the viewer set does not match the viewers that joined")
        for q in self.queues:
            waiting = [int(t) for t in list(q._queue)]  # type: ignore[attr-defined]
            if len(waiting) > 30:
                out.append(f"a viewer has {len(waiting)} messages waiting")
            if waiting != sorted(waiting):
                out.append("a viewer's messages are out of order")
            if self.just_sent and waiting[-1:] != [self.count]:
                out.append("a viewer did not get the newest message")
        return out


def _fan_out_steps(seed: int) -> list[Step]:
    rng = random.Random(seed)
    steps: list[Step] = []
    for _ in range(300):
        kind = rng.choice(["message"] * 12 + ["join", "join", "leave", "read", "read"])
        steps.append((kind, (rng.randrange(8), rng.randrange(40))))
    return steps


@pytest.mark.parametrize("seed", seeds())
def test_live_fan_out_keeps_its_rules_under_chaos(seed: int) -> None:
    check(FanOutWorld, _fan_out_steps(seed), seed)


def test_fan_out_chaos_catches_a_dropped_newest_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check itself is checked: a fan-out that keeps a full queue as it is, and so
    drops the newest message instead of the oldest, must fail the chaos test."""
    def drops_newest(self: Broadcaster, text: str) -> None:
        for q in self.clients:
            if not q.full():
                q.put_nowait(text)

    monkeypatch.setattr(Broadcaster, "_fan_out", drops_newest)
    with pytest.raises(AssertionError, match="a viewer did not get the newest message"):
        check(FanOutWorld, _fan_out_steps(0), 0)


class ViewerWorld:
    """Real WebSocket connections against the app in public mode, all from one address."""

    data_dir: Path
    per_address = 3

    def __init__(self) -> None:
        self.stack = contextlib.ExitStack()
        self.client = self.stack.enter_context(
            TestClient(create_app(self.data_dir, live=False, public=True)))
        self.open: list[contextlib.ExitStack] = []
        self.problems: list[str] = []

    def apply(self, step: Step) -> None:
        name, args = step
        if name == "open":
            viewer = contextlib.ExitStack()
            try:
                viewer.enter_context(self.client.websocket_connect("/ws/live"))
                accepted = True
            except WebSocketDisconnect:
                accepted = False
            if accepted != (len(self.open) < self.per_address):
                self.problems.append(
                    f"viewer {'let in' if accepted else 'refused'} with {len(self.open)} open")
            if accepted:
                self.open.append(viewer)
        elif self.open:
            self.open.pop(args[0] % len(self.open)).close()
            self._wait_for_count()

    def _count(self) -> Any:
        return self.client.get("/api/health").json()["live_clients"]

    def _wait_for_count(self) -> None:
        deadline = time.monotonic() + 5  # the server notices a closed socket a moment later
        while self._count() != len(self.open) and time.monotonic() < deadline:
            time.sleep(0.01)

    def broken(self) -> list[str]:
        out = list(self.problems)
        if self._count() != len(self.open):
            out.append(f"{self._count()} live viewers counted, {len(self.open)} open")
        return out

    def close(self) -> None:
        for viewer in self.open:
            viewer.close()
        self.stack.close()


@pytest.mark.parametrize("seed", seeds())
def test_live_viewer_count_keeps_its_rules_under_chaos(
        seed: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPCHIRP_DATABASE_URL", raising=False)
    monkeypatch.setenv("UPCHIRP_MAX_LIVE_PER_ADDRESS", str(ViewerWorld.per_address))
    ViewerWorld.data_dir = tmp_path
    worlds: list[ViewerWorld] = []

    def make() -> ViewerWorld:
        worlds.append(ViewerWorld())
        return worlds[-1]

    rng = random.Random(seed)
    steps: list[Step] = [(rng.choice(["open", "open", "close"]), (rng.randrange(5),))
                         for _ in range(12)]
    try:
        check(make, steps, seed)
    finally:
        for world in worlds:
            world.close()
