"""Tripwires: cheap checks, in running code, of things that must always be true.

A tripwire that fires means a bug somewhere, not bad input. It writes one log line
("TRIPWIRE <rule>: <detail>") and counts in `upchirp_tripwires_total{rule=...}`, which
Grafana can alarm on. It never raises and never changes what the caller does next.

The detail holds numbers only: never text from frames, questions, file paths or
visitor addresses.
"""

import logging
import time

log = logging.getLogger(__name__)

LOG_EVERY_S = 60.0  # a rule broken on every frame must not flood the log
COUNTS: dict[str, int] = {}  # per rule, since the process started (also read by the tests)
_last_logged: dict[str, float] = {}


def tripped(rule: str, detail: str = "") -> None:
    """Report that an always-true rule does not hold."""
    try:
        COUNTS[rule] = COUNTS.get(rule, 0) + 1
        now = time.monotonic()
        if now - _last_logged.get(rule, -LOG_EVERY_S) >= LOG_EVERY_S:
            _last_logged[rule] = now
            log.error("TRIPWIRE %s: %s", rule, detail)
        try:
            from upchirp import metrics  # needs the platform extra; the count above does not
        except ImportError:
            return
        metrics.TRIPWIRES.labels(rule).inc()
    except Exception:  # reporting a broken rule must never break the caller as well
        log.exception("TRIPWIRE %s could not be reported", rule)
