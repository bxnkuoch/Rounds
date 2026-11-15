"""EventTranslator: hand-built chunks plus one real scripted-agent integration run. Offline."""
import uuid

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Interrupt

from app.agents.coordinator import build_agent
from app.agents.translator import EventTranslator
from app.models.agent_events import (
    ApprovalRequired, Done, Error, SubagentFinished, SubagentStarted, Todos, Token, ToolCall, ToolResult,
)
from tests.fakes import FakeServices, ScriptedChatModel


def tr():
    fake = FakeServices()
    fake.propose_plan()  # P-1
    return fake, EventTranslator("t-1", fake)


def task_call(call_id="c9", sub="scheduler"):
    return AIMessage(content="", tool_calls=[{"name": "task", "args": {"description": "d", "subagent_type": sub}, "id": call_id}])


def interrupt_chunk(args, iid="abc123"):
    value = {
        "action_requests": [{"name": "apply_plan", "args": args, "description": "x"}],
        "review_configs": [{"action_name": "apply_plan", "allowed_decisions": ["approve", "reject"]}],
    }
    return (), "updates", {"__interrupt__": (Interrupt(value=value, id=iid),)}


def test_coordinator_token():
    _, t = tr()
    (ev,) = t.feed(((), "messages", (AIMessageChunk(content="Hello"), {"lc_agent_name": None})))
    assert isinstance(ev, Token) and ev.text == "Hello" and ev.source == "coordinator" and ev.thread_id == "t-1"
    assert t.feed(((), "messages", (AIMessageChunk(content=""), {}))) == []


def test_subagent_tokens_are_not_emitted():
    _, t = tr()
    t.feed(((), "updates", {"model": {"messages": [task_call()]}}))
    assert t.feed((("tools:c9",), "messages", (AIMessageChunk(content="thinking"), {"lc_agent_name": "scheduler"}))) == []


def test_todos_update():
    _, t = tr()
    items = [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "pending"}]
    evs = t.feed(((), "updates", {"tools": {"todos": items, "messages": []}}))
    (ev,) = evs
    assert isinstance(ev, Todos) and [i.content for i in ev.items] == ["a", "b"] and ev.items[0].status == "in_progress"


def test_task_call_emits_subagent_started_and_source_mapping():
    _, t = tr()
    evs = t.feed(((), "updates", {"model": {"messages": [task_call()]}}))
    assert [type(e) for e in evs] == [ToolCall, SubagentStarted]
    assert evs[0].name == "task" and evs[0].tool_call_id == "c9" and evs[0].args["subagent_type"] == "scheduler"
    assert evs[1].subagent == "scheduler" and evs[1].task_id == "c9" and evs[1].source == "coordinator"
    sub = AIMessage(content="", tool_calls=[{"name": "propose_plan", "args": {}, "id": "pp"}])
    (ev,) = t.feed((("tools:c9",), "updates", {"model": {"messages": [sub]}}))
    assert isinstance(ev, ToolCall) and ev.source == "subagent:scheduler"


def test_namespace_mapped_from_agent_name_or_fifo():
    _, t = tr()
    t.feed(((), "updates", {"model": {"messages": [task_call("c1", "scheduler")]}}))
    t.feed(((), "updates", {"model": {"messages": [task_call("c2", "general-purpose")]}}))
    sub = AIMessage(content="", tool_calls=[{"name": "list_jobs", "args": {}, "id": "x"}])
    # real namespaces carry a uuid, not the call id; lc_agent_name metadata identifies the subagent
    t.feed((("tools:u2",), "messages", (AIMessageChunk(content=""), {"lc_agent_name": "general-purpose"})))
    (ev,) = t.feed((("tools:u2",), "updates", {"model": {"messages": [sub]}}))
    assert ev.source == "subagent:general-purpose"
    # no metadata at all: first unseen namespace takes the oldest pending task call
    (ev,) = t.feed((("tools:u1",), "updates", {"model": {"messages": [sub]}}))
    assert ev.source == "subagent:scheduler"


def test_tool_result_ok_flag():
    _, t = tr()
    t.feed(((), "updates", {"model": {"messages": [task_call()]}}))
    ok = ToolMessage(content="fine", name="list_jobs", tool_call_id="a")
    bad = ToolMessage(content="ERROR: nope", name="list_jobs", tool_call_id="b")
    long = ToolMessage(content="x" * 500, name="list_jobs", tool_call_id="c")
    e_ok, e_bad, e_long = (t.feed(((), "updates", {"tools": {"messages": [m]}}))[0] for m in (ok, bad, long))
    assert isinstance(e_ok, ToolResult) and e_ok.ok and e_ok.summary == "fine" and e_ok.tool_call_id == "a"
    assert not e_bad.ok and e_bad.summary == "ERROR: nope"
    assert len(e_long.summary) == 200
    done = ToolMessage(content="Proposed", name="task", tool_call_id="c9")
    evs = t.feed(((), "updates", {"tools": {"messages": [done]}}))
    assert [type(e) for e in evs] == [ToolResult, SubagentFinished]
    assert evs[1].subagent == "scheduler" and evs[1].task_id == "c9"


def test_messages_mode_tool_chunks_are_ignored():
    _, t = tr()
    assert t.feed(((), "messages", (ToolMessage(content="x", name="n", tool_call_id="a"), {}))) == []
    assert t.feed(((), "messages", (task_call(), {}))) == []


def test_interrupt_diff_comes_from_services():
    fake, t = tr()
    t.feed(((), "messages", (AIMessageChunk(content="Apply it?"), {})))
    (ev,) = t.feed(interrupt_chunk({"plan_id": "P-1", "plan_diff": {"bogus": True}}))
    assert isinstance(ev, ApprovalRequired)
    assert ev.plan_diff == fake.get_proposal("P-1").diff
    assert ev.approval_id == "abc123" and ev.plan_id == "P-1" and ev.allowed == ["approve", "reject"]
    assert ev.rationale == "Apply it?" and ev.source == "coordinator"


def test_interrupt_rationale_empty_by_default():
    _, t = tr()
    (ev,) = t.feed(interrupt_chunk({"plan_id": "P-1"}))
    assert ev.rationale == ""


def test_interrupt_first_apply_plan_only():
    _, t = tr()
    value = {
        "action_requests": [
            {"name": "apply_plan", "args": {"plan_id": "P-1"}, "description": ""},
            {"name": "apply_plan", "args": {"plan_id": "P-1"}, "description": ""},
        ],
        "review_configs": [],
    }
    evs = t.feed(((), "updates", {"__interrupt__": [Interrupt(value=value, id="i")]}))
    assert len(evs) == 1


def test_interrupt_unknown_plan_is_error():
    _, t = tr()
    (ev,) = t.feed(interrupt_chunk({"plan_id": "P-404"}))
    assert isinstance(ev, Error) and ev.code == "unknown_plan" and ev.retryable is False


def test_unrelated_chunks_ignored():
    _, t = tr()
    assert t.feed(((), "updates", {"PatchToolCallsMiddleware.before_agent": None})) == []
    assert t.feed(((), "updates", {"model": {"messages": [AIMessage(content="hi")]}})) == []
    assert t.feed(((), "custom", {"x": 1})) == []


def test_seq_monotonic():
    _, t = tr()
    a = t.emit(Done, status="completed")
    b = t.feed(((), "messages", (AIMessageChunk(content="x"), {})))[0]
    c = t.feed(((), "updates", {"model": {"messages": [task_call()]}}))
    seqs = [a.seq, b.seq] + [e.seq for e in c]
    assert seqs == sorted(set(seqs)) and seqs[0] == 0
    assert a.source == "coordinator" and a.thread_id == "t-1"


# --- integration: real scripted agent --------------------------------------------

def call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_integration_scripted_run():
    script = [
        call("write_todos", {"todos": [{"content": "Propose a plan", "status": "in_progress"}]}, "td-1"),
        call("task", {"description": "Propose.", "subagent_type": "scheduler"}, "task-1"),
        call("propose_plan", {}, "pp-1"),
        AIMessage(content="Proposed P-1"),
        call("apply_plan", {"plan_id": "P-1"}, "apply-1"),
    ]
    fake = FakeServices()
    agent = build_agent(fake, ScriptedChatModel(script), InMemorySaver())
    t = EventTranslator("t-int", fake)
    events = []
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": "Plan the shift."}]},
        {"configurable": {"thread_id": f"t-{uuid.uuid4().hex}"}},
        stream_mode=["messages", "updates"], subgraphs=True,
    ):
        events += t.feed(chunk)
    got = [(e.type, e.source) for e in events]
    sub = "subagent:scheduler"
    assert got == [
        ("tool_call", "coordinator"),       # write_todos
        ("todos", "coordinator"),
        ("tool_result", "coordinator"),
        ("tool_call", "coordinator"),       # task
        ("subagent_started", "coordinator"),
        ("tool_call", sub),                 # propose_plan
        ("tool_result", sub),
        ("tool_result", "coordinator"),     # task result
        ("subagent_finished", "coordinator"),
        ("tool_call", "coordinator"),       # apply_plan
        ("approval_required", "coordinator"),
    ]
    approval = events[-1]
    assert approval.plan_diff == fake.get_proposal("P-1").diff
    assert approval.plan_id == "P-1" and approval.rationale == ""
    assert [e.seq for e in events] == list(range(len(events)))
    assert fake.apply_calls == []
