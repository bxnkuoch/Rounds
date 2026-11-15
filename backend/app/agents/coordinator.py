"""The Deep Agent graph: coordinator + scheduler and explainer subagents, with apply_plan gated by human approval.

Only the coordinator holds apply_plan, so there is one approval point. deepagents 0.7.38 would otherwise
give its built-in `general-purpose` subagent a copy of every coordinator tool (including apply_plan), so we
pass an explicit `general-purpose` spec (default name/description/prompt) with read-only tools.

Subagents get `interrupt_on={}`. They would otherwise inherit the coordinator's config, and
HumanInTheLoopMiddleware matches on tool-call *name*, not on the agent's tools: a subagent's hallucinated
apply_plan call would raise an approval card for a call that can never run. With no subagent gate, that call
fails as an unknown tool and the only approval point is the coordinator's real apply_plan.
"""
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT, SubAgent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.agents.prompts import COORDINATOR_PROMPT, EXPLAINER_PROMPT, SCHEDULER_PROMPT
from app.services.contract import Services
from app.tools.rounds_tools import build_tools

COORDINATOR_TOOL_NAMES = ("list_places", "list_staff", "list_jobs", "get_current_plan", "route_between", "shift_summary",
                          "apply_plan")
SCHEDULER_TOOL_NAMES = ("list_jobs", "get_current_plan", "propose_plan", "propose_replan")
EXPLAINER_TOOL_NAMES = ("get_current_plan", "list_jobs", "list_places", "list_staff", "route_between", "compare_swap")
GENERAL_PURPOSE_TOOL_NAMES = ("list_places", "list_staff", "list_jobs", "get_current_plan", "route_between")

INTERRUPT_ON = {"apply_plan": {"allowed_decisions": ["approve", "reject"]}}

# Files under /memories/ live in the LangGraph store, so they outlive a thread: the shift handoff written in one
# thread (shift) is readable from the next. Every other path stays in the thread's own state.
MEMORIES = "/memories/"


def build_backend(store: BaseStore) -> CompositeBackend:
    return CompositeBackend(default=StateBackend(),
                            routes={MEMORIES: StoreBackend(namespace=lambda _rt: ("rounds", "memories"), store=store)})


def build_agent(services: Services, model: BaseChatModel, checkpointer: BaseCheckpointSaver,
                store: BaseStore) -> CompiledStateGraph:
    tools = build_tools(services)

    def pick(names: tuple[str, ...]) -> list:
        return [tools[n] for n in names]

    scheduler: SubAgent = {
        "name": "scheduler",
        "description": "Uses the optimizer to propose plans and replans; returns a summary and the proposed "
                       "plan_id. It never applies them.",
        "system_prompt": SCHEDULER_PROMPT,
        "tools": pick(SCHEDULER_TOOL_NAMES),
        "interrupt_on": {},
    }
    explainer: SubAgent = {
        "name": "explainer",
        "description": "Explains why the current plan orders and times jobs as it does, quoting plan, job-window "
                       "and route numbers. Read-only: it never proposes or applies plans.",
        "system_prompt": EXPLAINER_PROMPT,
        "tools": pick(EXPLAINER_TOOL_NAMES),
        "interrupt_on": {},
    }
    general_purpose: SubAgent = {
        **GENERAL_PURPOSE_SUBAGENT, "tools": pick(GENERAL_PURPOSE_TOOL_NAMES), "interrupt_on": {},
    }

    return create_deep_agent(
        model=model,
        tools=pick(COORDINATOR_TOOL_NAMES),
        system_prompt=COORDINATOR_PROMPT,
        middleware=[TodoListMiddleware()],
        subagents=[scheduler, explainer, general_purpose],
        interrupt_on=INTERRUPT_ON,
        checkpointer=checkpointer,
        backend=build_backend(store),
        store=store,
    )
