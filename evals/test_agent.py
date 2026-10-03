"""Agent evals (step 3). They need a model, so they skip when none is reachable.

1. The agent answers the drone question correctly on both scenes, checked
   against ground truth.
2. A planted wrong tool output (closest range pushed out by 25 m) makes the
   answer wrong, and the check catches it.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

from upchirp.agent.answers import check_drone_answer, drone_truth
from upchirp.agent.availability import model_available
from upchirp.recording import read_ground_truth, record_simulation
from upchirp.replay import process_session
from upchirp.sim.engine import Simulator
from upchirp.sim.scene import get_scene

QUESTION = ("How many drone-like tracks crossed in the last 10 minutes, "
            "and how close did the closest one get?")


pytestmark = pytest.mark.skipif(not model_available(), reason="no model reachable")

agent = pytest.importorskip("upchirp.agent.graph")


@pytest.fixture(scope="module", params=["default", "crossing"])
def session(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
            ) -> tuple[Path, Path]:
    data_dir = tmp_path_factory.mktemp(f"agent-{request.param}")
    sim = Simulator(get_scene(request.param), session_id=f"eval-{request.param}",
                    start_ns=1_800_000_000_000_000_000, seed=0)
    session_dir = record_simulation(sim, data_dir)
    process_session(session_dir)
    return data_dir, session_dir


def _never(_: object) -> bool:
    return False


def test_drone_question_answered_correctly(session: tuple[Path, Path]) -> None:
    data_dir, session_dir = session
    expected = drone_truth(read_ground_truth(session_dir), last_minutes=10)
    answer, _ = asyncio.run(agent.ask(QUESTION, data_dir, approver=_never))
    verdict = check_drone_answer(answer, expected)
    print(f"\nexpected {expected}\nanswer: {answer}\nverdict: {verdict}")
    assert verdict.ok, verdict.reasons


def _push_closest_out(name: str, content: str) -> str:
    """Planted fault: every closest range the tools report is 25 m too far."""
    if name not in {"get_tracks", "summarize_session"}:
        return content
    return re.sub(r'("closest_range_m": )([\d.]+)',
                  lambda m: f"{m.group(1)}{float(m.group(2)) + 25:.2f}", content)


def test_planted_wrong_tool_output_fails_the_check(session: tuple[Path, Path]) -> None:
    data_dir, session_dir = session
    expected = drone_truth(read_ground_truth(session_dir), last_minutes=10)
    answer, messages = asyncio.run(
        agent.ask(QUESTION, data_dir, approver=_never, tool_filter=_push_closest_out)
    )
    seen = " ".join(str(m.content) for m in messages if getattr(m, "type", "") == "tool")
    verdict = check_drone_answer(answer, expected)
    print(f"\nexpected {expected}\nanswer from tampered tools: {answer}\nverdict: {verdict}")
    assert expected.closest_range_m is not None
    planted = [float(x) for x in re.findall(r'closest_range_m\\*"\s*:\s*([\d.]+)', seen)]
    assert planted, "the agent never saw a closest range"
    assert min(planted) > expected.closest_range_m + 20, "the planted fault did not land"
    assert not verdict.ok, "a wrong tool output produced an answer that passed"


def test_audit_log_records_question_tools_and_answer(session: tuple[Path, Path]) -> None:
    data_dir, _ = session
    lines = [json.loads(x) for x in (data_dir / "audit.jsonl").read_text().splitlines()]
    assert any("question" in e for e in lines)
    assert any(e.get("actor") == "mcp" and e.get("tool") for e in lines)
    assert any("answer" in e for e in lines)
