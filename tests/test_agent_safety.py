"""Agent safety without a real model: a scripted model drives the real graph and MCP server."""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import tool

from upchirp.agent import server
from upchirp.agent.graph import ask, build_graph, mcp_client

CHIRP_CALL = AIMessage("", tool_calls=[{
    "name": "set_chirp_config", "id": "call-1",
    "args": {"settings": {"f_start_hz": 5.75e9, "bandwidth_hz": 100e6,
                        "chirp_duration_s": 1e-3, "n_chirps": 64, "reason": "test"}},
}])


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        return self


def _script(*messages: BaseMessage) -> ScriptedModel:
    return ScriptedModel(responses=[*messages, AIMessage("done")])


def _audit(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / server.AUDIT_FILE
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("approve", [False, True])
def test_destructive_tool_waits_for_a_human(tmp_path: Path, approve: bool) -> None:
    asked: list[Any] = []

    def approver(calls: list[dict[str, Any]]) -> bool:
        asked.extend(calls)
        return approve

    answer, _ = asyncio.run(ask("change the chirp", tmp_path, approver, model=_script(CHIRP_CALL)))
    assert [c["name"] for c in asked] == ["set_chirp_config"]
    assert (tmp_path / server.PENDING_CHIRP_FILE).exists() == approve
    decisions = [e["approval"] for e in _audit(tmp_path) if "approval" in e]
    assert decisions == ["approved" if approve else "denied"]
    assert answer == "done"


def test_read_tools_need_no_approval(tmp_path: Path) -> None:
    call = AIMessage("", tool_calls=[{"name": "list_sessions", "id": "c", "args": {}}])
    asked: list[Any] = []
    asyncio.run(ask("sessions?", tmp_path, lambda c: asked.append(c) or True,
                    model=_script(call)))
    assert asked == []
    assert any(e.get("tool") == "list_sessions" for e in _audit(tmp_path))


def test_tools_off_the_allowlist_never_run(tmp_path: Path) -> None:
    ran: list[str] = []

    @tool
    def wipe_disk() -> str:
        """Not allowed."""
        ran.append("wipe")
        return "wiped"

    async def run() -> list[BaseMessage]:
        tools = [*await mcp_client(tmp_path).get_tools(), wipe_disk]
        call = AIMessage("", tool_calls=[{"name": "wipe_disk", "id": "c", "args": {}}])
        graph = build_graph(_script(call), tools, tmp_path)
        state = await graph.ainvoke({"messages": []}, {"configurable": {"thread_id": "t"}})
        return list(state["messages"])

    messages = asyncio.run(run())
    assert ran == []
    assert any("wipe_disk" in str(m.content) and "not a valid tool" in str(m.content)
               for m in messages)


def test_public_mode_exposes_only_read_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPCHIRP_PUBLIC", "1")
    tools = asyncio.run(server.build_server().list_tools())
    assert {t.name for t in tools} == {
        "list_sessions", "get_tracks", "summarize_session", "search_docs"}
    assert all(t.annotations and t.annotations.readOnlyHint for t in tools)


def test_chirp_config_outside_the_band_is_rejected() -> None:
    with pytest.raises(ValueError):
        server.ChirpConfigRequest(f_start_hz=2.4e9, bandwidth_hz=100e6,
                                  chirp_duration_s=1e-3, n_chirps=64, reason="x")


def test_settings_change_not_requested_by_user_is_blocked(tmp_path: Path) -> None:
    asked: list[Any] = []
    answer, _ = asyncio.run(ask("how many drone-like tracks were there?", tmp_path,
                                lambda c: asked.append(c) or True, model=_script(CHIRP_CALL)))
    assert asked == []  # never even reached the human
    assert not (tmp_path / server.PENDING_CHIRP_FILE).exists()
    assert [e["approval"] for e in _audit(tmp_path) if "approval" in e] == [
        "blocked: user did not ask for a change"]


def test_grounding_guard() -> None:
    from langchain_core.messages import HumanMessage, ToolMessage

    from upchirp.agent.graph import GROUNDING_NUDGE, needs_grounding

    q = HumanMessage("how many drone-like tracks?")
    copied = AIMessage("The docs say 7 drone-like tracks.")
    assert needs_grounding([q, copied])
    tool = ToolMessage(content="{}", tool_call_id="c", name="get_tracks")
    assert not needs_grounding([q, tool, AIMessage("1 drone-like track.")])
    assert not needs_grounding([q, copied, HumanMessage(GROUNDING_NUDGE), copied])  # once only
    assert not needs_grounding([HumanMessage("hi"), AIMessage("Hello!")])


def test_public_agent_never_sees_control_tools(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with UPCHIRP_PUBLIC unset, a public agent gets read tools only."""
    monkeypatch.delenv("UPCHIRP_PUBLIC", raising=False)

    async def run() -> tuple[set[str], list[BaseMessage]]:
        tools = await mcp_client(tmp_path, public=True).get_tools()
        graph = build_graph(_script(CHIRP_CALL), tools, tmp_path, public=True)
        state = await graph.ainvoke({"messages": []}, {"configurable": {"thread_id": "t"}})
        return {t.name for t in tools}, list(state["messages"])

    names, messages = asyncio.run(run())
    assert names == {"list_sessions", "get_tracks", "summarize_session", "search_docs"}
    assert not (tmp_path / server.PENDING_CHIRP_FILE).exists()
    assert any("not a valid tool" in str(m.content) for m in messages)


@pytest.mark.parametrize("session", ["../sessions", "..", "a/b", "/etc"])
def test_session_ids_are_plain_names(tmp_path: Path, session: str) -> None:
    from upchirp.recording import resolve_session

    with pytest.raises(FileNotFoundError) as e:
        resolve_session(tmp_path, session)
    assert str(tmp_path) not in str(e.value)


def test_answer_text_leaves_out_thinking_blocks() -> None:
    """Hosted Claude answers in blocks; the user sees only the text, never the thinking."""
    from upchirp.agent.graph import text_of

    msg = AIMessage(content=[
        {"type": "thinking", "thinking": "private reasoning", "signature": "abc"},
        {"type": "text", "text": "1 person and 1 car so far."},
    ])
    assert text_of(msg) == "1 person and 1 car so far."
    assert text_of(AIMessage(content="plain")) == "plain"
