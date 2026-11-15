import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.agents.model import AgentUnavailable, build_chat_model
from tests.fakes import ScriptedChatModel


@tool
def list_jobs() -> str:
    """List jobs."""
    return "[]"


def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_default_model_id(monkeypatch, tmp_path):
    _clear(monkeypatch)
    env = tmp_path / "local.env"
    env.write_text("ANTHROPIC_API_KEY=test\n")
    model = build_chat_model(env_path=env)
    assert "claude-haiku-5-5" in model.model


def test_agent_model_from_env_file(monkeypatch, tmp_path):
    _clear(monkeypatch)
    env = tmp_path / "local.env"
    env.write_text("ANTHROPIC_API_KEY=test\nAGENT_MODEL=anthropic:claude-sonnet-5-5\n")
    assert "claude-sonnet-5-5" in build_chat_model(env_path=env).model


def test_missing_key_raises(monkeypatch, tmp_path):
    _clear(monkeypatch)
    env = tmp_path / "local.env"
    env.write_text("")
    with pytest.raises(AgentUnavailable, match="ANTHROPIC_API_KEY not set"):
        build_chat_model(env_path=env)


def test_scripted_model_replays_tool_calls():
    m = ScriptedChatModel(
        [AIMessage("", tool_calls=[{"name": "list_jobs", "args": {}, "id": "c1"}]), AIMessage("done")]
    ).bind_tools([list_jobs])
    first = m.invoke([HumanMessage("hi")])
    second = m.invoke([HumanMessage("again")])
    assert first.tool_calls[0]["name"] == "list_jobs"
    assert second.content == "done"
    with pytest.raises(AssertionError, match="script exhausted"):
        m.invoke([HumanMessage("x")])


def test_scripted_model_records_calls():
    m = ScriptedChatModel([AIMessage("a")])
    m.invoke([HumanMessage("hi")])
    assert len(m.calls) == 1 and m.calls[0][0].content == "hi"


def test_scripted_model_ainvoke_consumes_one():
    m = ScriptedChatModel([AIMessage("a"), AIMessage("b")])
    assert asyncio.run(m.ainvoke([HumanMessage("x")])).content == "a"
    assert m.invoke([HumanMessage("y")]).content == "b"


def test_scripted_model_streaming_keeps_tool_calls_and_consumes_one():
    m = ScriptedChatModel(
        [AIMessage("", tool_calls=[{"name": "list_jobs", "args": {}, "id": "c1"}]), AIMessage("next")]
    )
    chunks = list(m.stream([HumanMessage("x")]))
    merged = chunks[0]
    for c in chunks[1:]:
        merged = merged + c
    assert len(merged.tool_calls) == 1 and merged.tool_calls[0]["name"] == "list_jobs"

    async def collect():
        return [c async for c in m.astream([HumanMessage("y")])]

    achunks = asyncio.run(collect())
    assert "".join(c.content for c in achunks) == "next"
    assert len(m.calls) == 2


def test_scripted_model_raises_exception_items():
    m = ScriptedChatModel([RuntimeError("boom"), AIMessage("ok")])
    with pytest.raises(RuntimeError, match="boom"):
        m.invoke([HumanMessage("x")])
    assert m.invoke([HumanMessage("y")]).content == "ok"
    m2 = ScriptedChatModel([ValueError("aboom")])
    with pytest.raises(ValueError):
        asyncio.run(m2.ainvoke([HumanMessage("x")]))
