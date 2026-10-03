"""Cost and latency per answer, hosted vs local (step 5).

Asks a fixed set of questions about simulated sessions several times, checks
each answer against ground truth, and records wall time and tokens. Writes a
Markdown report to docs/reports/. Prices are per million tokens, from Anthropic's
public price list; a local model costs no money per answer, only CPU time.
"""

import asyncio
import json
import os
import platform
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from upchirp.agent.answers import DroneTruth, check_drone_answer, drone_truth
from upchirp.agent.costs import cost_usd, tokens
from upchirp.recording import read_ground_truth, record_simulation
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene

QUESTION = ("How many drone-like tracks crossed in the last 10 minutes, "
            "and how close did the closest one get?")


@dataclass
class Sample:
    scene: str
    seconds: float
    input_tokens: int
    output_tokens: int
    correct: bool


def model_name() -> str:
    from upchirp.agent.graph import model_id

    return model_id()


def _prepare(root: Path, scene: str) -> tuple[Path, DroneTruth]:
    data_dir = root / scene
    sim = Simulator(get_scene(scene), session_id=f"bench-{scene}",
                    start_ns=1_800_000_000_000_000_000, seed=0)
    session_dir = record_simulation(sim, data_dir)
    process_session(session_dir)
    return data_dir, drone_truth(read_ground_truth(session_dir), last_minutes=10)


def run(root: Path, runs: int, scenes: tuple[str, ...] = ("default", "crossing")) -> list[Sample]:
    from upchirp.agent.graph import ask

    os.environ.pop("UPCHIRP_DATABASE_URL", None)
    prepared = {s: _prepare(root, s) for s in scenes}
    samples = []
    for _ in range(runs):
        for scene, (data_dir, expected) in prepared.items():
            start = time.perf_counter()
            answer, messages = asyncio.run(ask(QUESTION, data_dir, approver=lambda _: False))
            seconds = time.perf_counter() - start
            inp, out = tokens(messages)
            samples.append(Sample(scene, seconds, inp, out,
                                  check_drone_answer(answer, expected).ok))
    return samples


def _p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=20, method="inclusive")[18] if len(xs) > 1 else xs[0]


def report(samples: list[Sample], model: str) -> str:
    secs = [s.seconds for s in samples]
    inp = statistics.mean(s.input_tokens for s in samples)
    out = statistics.mean(s.output_tokens for s in samples)
    per_answer = cost_usd(model, round(inp), round(out))
    cost = f"${per_answer:.4f}" if per_answer else "$0 (local CPU)"
    right = sum(s.correct for s in samples)
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    machine = f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPU threads"
    return "\n".join([
        f"# Agent benchmark: {model}",
        "",
        f"- Date: {when}",
        f"- Machine: {machine}",
        f"- Question: \"{QUESTION}\" on the default and crossing scenes",
        f"- Answers: {len(samples)} ({len(samples) // 2} per scene)",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Correct against ground truth | {right} of {len(samples)} |",
        f"| Latency p50 | {statistics.median(secs):.1f} s |",
        f"| Latency p95 | {_p95(secs):.1f} s |",
        f"| Mean input tokens per answer | {inp:.0f} |",
        f"| Mean output tokens per answer | {out:.0f} |",
        f"| Cost per answer | {cost} |",
        "",
        "Raw samples:",
        "",
        "```json",
        json.dumps([s.__dict__ for s in samples], indent=1),
        "```",
        "",
    ])
