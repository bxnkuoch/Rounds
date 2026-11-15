"""Coordinator + scheduler subagent + apply_plan approval gate. Offline: scripted model, fake services.

The ScriptedChatModel is shared by the coordinator and every subagent, so the script is
written in call order across agents.
"""
import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents import coordinator
from app.agents.coordinator import GENERAL_PURPOSE_TOOL_NAMES, SCHEDULER_TOOL_NAMES, build_agent
from app.agents.prompts import COORDINATOR_PROMPT, DISPATCH_TEMPLATES, SCHEDULER_PROMPT
from tests.fakes import FakeServices, ScriptedChatModel

USER = {"messages": [{"role": "user", "content": "Plan the shift."}]}


def call(name: str, args: dict, call_id: str | None = None) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id or f"c-{uuid.uuid4().hex[:8]}"}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


def cfg() -> dict:
    return {"configurable": {"thread_id": f"t-{uuid.uuid4().hex}"}}


TODOS = call("write_todos", {"todos": [{"content": "Propose a plan", "status": "in_progress"}]})
TO_SCHEDULER = call("task", {"description": "Propose a plan for all jobs.", "subagent_type": "scheduler"})


def until_interrupt() -> list:
    return [
        TODOS,
        TO_SCHEDULER,
        call("propose_plan", {}),        # scheduler
        say("Proposed P-1"),             # scheduler final
        call("apply_plan", {"plan_id": "P-1"}, "apply-1"),  # coordinator
    ]


def _agent(script: list):
    fake = FakeServices()
    model = ScriptedChatModel(script)
    return fake, model, build_agent(fake, model, InMemorySaver())


# --- static shape -------------------------------------------------------------

def test_scheduler_has_no_apply_plan():
    assert "apply_plan" not in SCHEDULER_TOOL_NAMES
    assert set(SCHEDULER_TOOL_NAMES) == {"list_jobs", "get_current_plan", "propose_plan", "propose_replan"}


def test_general_purpose_has_no_apply_or_propose():
    assert "apply_plan" not in GENERAL_PURPOSE_TOOL_NAMES
    assert not {"propose_plan", "propose_replan"} & set(GENERAL_PURPOSE_TOOL_NAMES)


def test_create_deep_agent_kwargs(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return "graph"

    monkeypatch.setattr(coordinator, "create_deep_agent", fake_create)
    saver = InMemorySaver()
    model = ScriptedChatModel([])
    assert build_agent(FakeServices(), model, saver) == "graph"

    assert captured["model"] is model
    assert captured["checkpointer"] is saver
    assert captured["system_prompt"] == COORDINATOR_PROMPT
    assert [t.name for t in captured["tools"]] == [
        "list_places", "list_staff", "list_jobs", "get_current_plan", "route_between", "apply_plan"]
    assert captured["interrupt_on"] == {"apply_plan": {"allowed_decisions": ["approve", "reject"]}}
    assert [type(m).__name__ for m in captured["middleware"]] == ["TodoListMiddleware"]
    specs = {s["name"]: s for s in captured["subagents"]}
    assert set(specs) == {"scheduler", "general-purpose"}
    assert specs["scheduler"]["system_prompt"] == SCHEDULER_PROMPT
    assert [t.name for t in specs["scheduler"]["tools"]] == list(SCHEDULER_TOOL_NAMES)
    assert "never applies" in specs["scheduler"]["description"]
    assert [t.name for t in specs["general-purpose"]["tools"]] == list(GENERAL_PURPOSE_TOOL_NAMES)
    # No subagent holds apply_plan, and none carries its own gate: the coordinator is the single approval point.
    for spec in specs.values():
        assert "apply_plan" not in [t.name for t in spec["tools"]]
        assert spec["interrupt_on"] == {}


def test_coordinator_offers_write_todos_and_task():
    """R2: TodoListMiddleware is passed explicitly and not duplicated; write_todos reaches the model."""
    fake, model, agent = _agent([say("hello")])
    agent.invoke(USER, cfg())
    assert len(model.calls) == 1
    # bind_tools returns self in the scripted model, so check the compiled graph's tool node instead.
    assert {"write_todos", "task", "apply_plan"} <= _tool_names(agent)


def _tool_names(agent) -> set[str]:
    node = agent.nodes["tools"].bound
    return set(node.tools_by_name)


def test_prompts_encode_rules():
    for p in (COORDINATOR_PROMPT, SCHEDULER_PROMPT):
        low = p.lower()
        assert "never" in low and "estimate" in low
        assert "infeasible" in low
        assert "clinical" in low
        assert " id" in low
    assert "apply_plan" in COORDINATOR_PROMPT and "approv" in COORDINATOR_PROMPT.lower()
    assert DISPATCH_TEMPLATES == {
        "job_added": "Dispatch: new job {job_id} arrived. Propose a replan.",
        "staff_unavailable": "Dispatch: staff {staff_id} is unavailable. Propose a replan.",
    }


# --- approval gate ------------------------------------------------------------

def _pause(script_tail: list):
    fake, model, agent = _agent(until_interrupt() + script_tail)
    config = cfg()
    out = agent.invoke(USER, config)
    return fake, model, agent, config, out


def test_pauses_before_apply():
    fake, _, _, _, out = _pause([])
    assert "__interrupt__" in out
    (intr,) = out["__interrupt__"]
    assert isinstance(intr.id, str) and intr.id
    (req,) = intr.value["action_requests"]
    assert req["name"] == "apply_plan"
    assert req["args"] == {"plan_id": "P-1"}
    assert intr.value["review_configs"] == [{"action_name": "apply_plan", "allowed_decisions": ["approve", "reject"]}]
    assert "P-1" in fake.proposals
    assert fake.apply_calls == []


def test_approve_applies_once():
    fake, _, agent, config, _ = _pause([say("Applied P-1.")])
    out = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
    assert fake.apply_calls == ["P-1"]
    assert "__interrupt__" not in out
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage) and m.name == "apply_plan"]
    assert len(tool_msgs) == 1 and '"id":"P-1"' in tool_msgs[0].content
    assert out["messages"][-1].content == "Applied P-1."


def test_reject_never_applies():
    fake, _, agent, config, _ = _pause([say("Understood, P-1 was not applied.")])
    out = agent.invoke(Command(resume={"decisions": [{"type": "reject", "message": "not now"}]}), config)
    assert fake.apply_calls == []
    rejected = [m for m in out["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "apply-1"]
    assert len(rejected) == 1 and "not now" in rejected[0].content and rejected[0].status == "error"
    assert isinstance(out["messages"][-1], AIMessage)
    assert out["messages"][-1].content == "Understood, P-1 was not applied."


def _subagent_tries_apply(subagent_type: str):
    script = [
        call("task", {"description": "Propose and apply.", "subagent_type": subagent_type}),
        call("apply_plan", {"plan_id": "P-1"}, "sub-apply"),  # subagent tries the gated tool
        say("I could not apply."),                            # subagent final
        say("Done."),                                         # coordinator final
    ]
    fake, model, agent = _agent(script)
    # A stored proposal exists, so only the missing tool can stop the apply.
    fake.propose_plan()
    out = agent.invoke(USER, cfg())
    return fake, model, out


def _subagent_tool_messages(model) -> list[ToolMessage]:
    # The subagent's own messages never reach the parent state; read them from the model's inputs.
    return [m for msgs in model.calls for m in msgs if isinstance(m, ToolMessage) and m.tool_call_id == "sub-apply"]


def test_unscripted_subagent_apply_impossible():
    fake, model, out = _subagent_tries_apply("scheduler")
    assert "__interrupt__" not in out
    assert fake.apply_calls == []
    (err,) = _subagent_tool_messages(model)
    assert err.status == "error" and "apply_plan" in err.content and "not a valid tool" in err.content
    assert out["messages"][-1].content == "Done."


def test_general_purpose_subagent_cannot_bypass_approval():
    fake, model, out = _subagent_tries_apply("general-purpose")
    assert "__interrupt__" not in out
    assert fake.apply_calls == []
    (err,) = _subagent_tool_messages(model)
    assert err.status == "error" and "not a valid tool" in err.content
    assert out["messages"][-1].content == "Done."
