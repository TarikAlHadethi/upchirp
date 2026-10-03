"""Limits for the public demo (UPCHIRP_PUBLIC=1): per-visitor rate limit and a daily spend cap.

Spend is estimated from token counts (agent/costs.py) and kept per UTC day, in
PostgreSQL when it is configured so a restart does not reset the cap. The AWS
budget alarm (infra/) is the backstop if this estimate is ever wrong.
"""

import os
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from upchirp import store

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_usage (
    day             date PRIMARY KEY,
    answers         integer NOT NULL DEFAULT 0,
    input_tokens    bigint NOT NULL DEFAULT 0,
    output_tokens   bigint NOT NULL DEFAULT 0,
    cost_usd        double precision NOT NULL DEFAULT 0
);
"""


class Limited(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


class PublicGuard:
    def __init__(self, per_minute: int | None = None, per_day: int | None = None,
                 daily_cap_usd: float | None = None, reserve_usd: float | None = None) -> None:
        env = os.environ.get
        self.per_minute = per_minute or int(env("UPCHIRP_RATE_PER_MINUTE", "5"))
        self.per_day = per_day or int(env("UPCHIRP_RATE_PER_DAY", "40"))
        self.cap = daily_cap_usd if daily_cap_usd is not None else float(
            env("UPCHIRP_DAILY_CAP_USD", "1.0"))
        self.lock = threading.Lock()
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.memory: dict[str, float] = defaultdict(float)
        # Each question in flight holds this much of today's budget until its real cost is
        # known, so many questions at once cannot all slip under the cap.
        self.reserve_usd = reserve_usd if reserve_usd is not None else float(
            env("UPCHIRP_RESERVE_PER_ANSWER_USD", "0.10"))
        self.reserved = 0.0
        self.use_db = bool(store.database_url())
        if self.use_db:
            with store.connect() as conn:
                conn.execute(USAGE_SCHEMA)

    def spent_today(self) -> float:
        if not self.use_db:
            return self.memory[_today()]
        with store.connect() as conn:
            row = conn.execute("SELECT cost_usd FROM daily_usage WHERE day = %s",
                               (_today(),)).fetchone()
        return float(row["cost_usd"]) if row else 0.0

    def check(self, visitor: str) -> None:
        """Raise Limited if this visitor or today's budget is used up."""
        now = time.time()
        with self.lock:
            hits = self.hits[visitor]
            while hits and hits[0] < now - 86_400:
                hits.popleft()
            if sum(1 for t in hits if t > now - 60) >= self.per_minute:
                raise Limited(429, "Too many questions; wait a minute.")
            if len(hits) >= self.per_day:
                raise Limited(429, "Daily question limit reached for your address.")
            if self.spent_today() + self.reserved + self.reserve_usd > self.cap:
                raise Limited(503, "The demo's daily budget is used up. Try again tomorrow.")
            hits.append(now)
            self.reserved += self.reserve_usd

    def record(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        """Book one answer's real cost and release its reservation. Call exactly once per
        successful check(), also when the answer failed (then with the reservation)."""
        with self.lock:
            self.reserved = max(0.0, self.reserved - self.reserve_usd)
        if not self.use_db:
            self.memory[_today()] += cost
            return
        with store.connect() as conn:
            conn.execute(
                """INSERT INTO daily_usage (day, answers, input_tokens, output_tokens, cost_usd)
                   VALUES (%s, 1, %s, %s, %s)
                   ON CONFLICT (day) DO UPDATE SET answers = daily_usage.answers + 1,
                     input_tokens = daily_usage.input_tokens + EXCLUDED.input_tokens,
                     output_tokens = daily_usage.output_tokens + EXCLUDED.output_tokens,
                     cost_usd = daily_usage.cost_usd + EXCLUDED.cost_usd""",
                (_today(), input_tokens, output_tokens, cost))

    def status(self) -> dict[str, Any]:
        return {"daily_cap_usd": self.cap, "spent_today_usd": round(self.spent_today(), 4)}
