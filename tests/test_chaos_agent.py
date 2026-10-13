"""Chaos test for the agent's approval gate: the real graph and Agent class, with a fake
model that answers by the question it is given and two fake tools. No model, no MCP server.

Rules:
- a destructive tool runs only after a human yes for that same question, once per yes
- a denied or blocked call never runs
- a decision for an unknown thread, or a second decision, is refused and runs nothing
- a decision on one thread never changes another thread
- every question, decision, block and answer leaves a line in the audit log
- in public mode a control or destructive tool does not exist, whatever the server offers
- chirp settings that are accepted always sweep inside 5.725 to 5.875 GHz
"""

import asyncio
import json
import random
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from chaos_support import Step, check, seeds

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from upchirp.agent import server
from upchirp.agent.graph import GROUNDING_NUDGE, Agent, build_graph, text_of

# What the fake model does for each kind of question. "settings" in the question is what
# lets a destructive call reach the human; "sneaky" asks for no change but the model tries.
QUESTIONS = {
    "plain": ("hello", []),
    "read": ("which sessions are there", ["list_sessions"]),
    "change": ("change the chirp settings", ["set_chirp_config"]),
    "mixed": ("list sessions and change the settings", ["list_sessions", "set_chirp_config"]),
    "sneaky": ("which sessions are there today", ["set_chirp_config"]),
}


class _Model(FakeMessagesListChatModel):
    """Calls the tools its question's kind names, then says done. The question's tag (q3)
    travels in the tool arguments, so each tool run can be tied to its question."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "_Model":
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        humans = [m for m in messages if isinstance(m, HumanMessage)
                  and m.content != GROUNDING_NUDGE]
        tag, kind = text_of(humans[-1]).split()[:2]
        if isinstance(messages[-1], HumanMessage):
            calls = [{"name": name, "id": f"{tag}-{i}", "args": {"tag": tag}}
                     for i, name in enumerate(QUESTIONS[kind][1])]
            reply = AIMessage("" if calls else f"done {tag}", tool_calls=calls)
        else:
            reply = AIMessage(f"done {tag}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


class AgentWorld:
    root: Path
    public = False

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(dir=self.root))
        self.loop = asyncio.new_event_loop()
        self.changed: list[str] = []  # question tags whose settings change really ran
        self.read: list[str] = []
        changed, read = self.changed, self.read

        @tool
        def set_chirp_config(tag: str) -> str:
            """Change the radar settings."""
            changed.append(tag)
            return "queued"

        @tool
        def list_sessions(tag: str) -> str:
            """List sessions."""
            read.append(tag)
            return "none"

        set_chirp_config.metadata = {"destructiveHint": True}
        self.agent = Agent(self.dir, model=_Model(responses=[]))
        self.agent.graph = build_graph(self.agent.model, [set_chirp_config, list_sessions],
                                       self.dir, public=self.public)
        self.asked: list[tuple[str, str, str]] = []  # tag, kind, thread id
        self.waiting: dict[str, str] = {}  # thread id -> tag
        self.approved: list[str] = []
        self.decisions = 0  # decisions that reached a waiting question
        self.blocked = 0
        self.answered = 0
        self.problems: list[str] = []

    def _do(self, coroutine: Any) -> Any:
        return self.loop.run_until_complete(coroutine)

    def _thread(self, k: int) -> str:
        return self.asked[k % len(self.asked)][2]

    def apply(self, step: Step) -> None:
        name, args = step
        if name == "ask":
            tag, kind = f"q{len(self.asked)}", args[0]
            turn = self._do(self.agent.start(f"{tag} {kind} {QUESTIONS[kind][0]}"))
            self.asked.append((tag, kind, turn["thread_id"]))
            gated = kind in ("change", "mixed") and not self.public
            if (turn["status"] == "needs_approval") != gated:
                self.problems.append(f"a {kind} question came back as {turn['status']}")
            if turn["status"] == "needs_approval":
                self.waiting[turn["thread_id"]] = tag
            else:
                self.answered += 1
                self.blocked += kind == "sneaky" and not self.public
        elif name == "decide_unknown":
            self._decide(["no-such-thread"], [args[0]])
        elif self.asked and name == "decide":
            self._decide([self._thread(args[0])], [args[1]])
        elif self.asked:  # "decide_twice": two decisions for one thread at the same instant
            self._decide([self._thread(args[0])] * 2, [args[1], args[2]])

    def _decide(self, threads: list[str], approvals: list[bool]) -> None:
        async def together() -> list[Any]:
            return await asyncio.gather(
                *(self.agent.resume(t, a) for t, a in zip(threads, approvals, strict=True)),
                return_exceptions=True)

        tag = self.waiting.pop(threads[0], None)
        results = self._do(together())
        taken = [(r, a) for r, a in zip(results, approvals, strict=True)
                 if not isinstance(r, Exception)]
        refused = [r for r in results if isinstance(r, Exception)]
        if any(not isinstance(r, FileNotFoundError) for r in refused):
            self.problems.append(f"a decision failed with {refused!r}")
        if len(taken) != (1 if tag else 0):
            self.problems.append(
                f"{len(taken)} of {len(results)} decisions were carried out for a question "
                f"that was {'waiting' if tag else 'not waiting'}")
        for turn, approve in taken:
            self.decisions += 1
            self.answered += turn["status"] == "answered"
            if approve and tag:
                self.approved.append(tag)

    def broken(self) -> list[str]:
        out = list(self.problems)
        if sorted(self.changed) != sorted(self.approved):
            out.append(f"settings changes ran for {sorted(self.changed)}, "
                       f"a human approved {sorted(self.approved)}")
        for thread, tag in self.waiting.items():
            state = self._do(self.agent.graph.aget_state({"configurable": {"thread_id": thread}}))
            if not state.next:
                out.append(f"question {tag} is no longer waiting, but nobody decided it")
        path = self.dir / server.AUDIT_FILE
        audit = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
        counts = {
            "questions": (sum("question" in e for e in audit), len(self.asked)),
            "answers": (sum("answer" in e for e in audit), self.answered),
            "decisions": (sum(e.get("approval") in ("approved", "denied") for e in audit),
                          self.decisions),
            "blocks": (sum(str(e.get("approval", "")).startswith("blocked") for e in audit),
                       self.blocked),
        }
        out += [f"audit log has {seen} {what}, expected {want}"
                for what, (seen, want) in counts.items() if seen != want]
        return out

    def close(self) -> None:
        self.loop.close()


def _steps(seed: int, n: int = 25) -> list[Step]:
    rng = random.Random(seed)
    steps: list[Step] = []
    for _ in range(n):
        kind = rng.choice(["ask"] * 5 + ["decide"] * 5 + ["decide_twice", "decide_unknown"])
        if kind == "ask":
            steps.append(("ask", (rng.choice(["plain", "read", "change", "change", "mixed",
                                              "sneaky"]),)))
        else:
            steps.append((kind, (rng.randrange(50), rng.random() < 0.5, rng.random() < 0.5)))
    return steps


def _check(steps: list[Step], root: Path, seed: int | None = None) -> None:
    AgentWorld.root = root
    worlds: list[AgentWorld] = []

    def make() -> AgentWorld:
        worlds.append(AgentWorld())
        return worlds[-1]

    try:
        check(make, steps, seed)
    finally:
        for world in worlds:
            world.close()


@pytest.mark.parametrize("seed", seeds())
def test_approval_gate_keeps_its_rules_under_chaos(seed: int, tmp_path: Path) -> None:
    _check(_steps(seed), tmp_path, seed)


class PublicAgentWorld(AgentWorld):
    """The same agent in public mode: the settings tool is offered but must not exist."""

    public = True


@pytest.mark.parametrize("seed", seeds())
def test_public_agent_never_changes_settings_under_chaos(seed: int, tmp_path: Path) -> None:
    PublicAgentWorld.root = tmp_path
    worlds: list[AgentWorld] = []

    def make() -> AgentWorld:
        worlds.append(PublicAgentWorld())
        return worlds[-1]

    try:
        check(make, _steps(seed), seed)
    finally:
        for world in worlds:
            world.close()


@pytest.mark.parametrize("seed", seeds())
def test_accepted_chirp_settings_stay_in_band(seed: int) -> None:
    rng = random.Random(seed)
    edges = [5.725e9, 5.875e9, 5.8e9, 5.724999e9, 5.875001e9, 0.0, -1.0, 6e9]
    widths = [0.0, 1.0, 75e6, 150e6, 150.000001e6, 149.999999e6, 1e9, -150e6]
    for _ in range(300):
        start = rng.choice(edges) + rng.choice([0.0, 0.0, rng.uniform(-200e6, 200e6)])
        width = rng.choice(widths) + rng.choice([0.0, 0.0, rng.uniform(-10e6, 10e6)])
        try:
            ok = server.ChirpConfigRequest(
                f_start_hz=start, bandwidth_hz=width, n_chirps=rng.choice([15, 16, 64, 256, 257]),
                chirp_duration_s=rng.choice([1e-5, 1e-4, 1e-3, 1e-2, 1.0]), reason="test")
        except ValueError:
            continue
        assert 5.725e9 <= ok.f_start_hz and ok.f_start_hz + ok.bandwidth_hz <= 5.875e9
        assert ok.bandwidth_hz > 0 and 16 <= ok.n_chirps <= 256
