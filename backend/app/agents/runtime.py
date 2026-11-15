"""Agent runtime: threads, per-thread locks, run / resume / dispatch event / state.

A run is tied to its caller (the HTTP stream). Closing the iterator (client disconnect) closes the
underlying `astream` and releases the thread lock. An approval pause lives in the LangGraph checkpoint,
so `state()` and `resume()` read it back with `aget_state` after a disconnect; nothing about the pending
approval is cached in memory.

Verified against langgraph 1.2.22: `CompiledStateGraph.aget_state(config) -> StateSnapshot`, whose
`.interrupts` holds only interrupts still waiting for an answer (latest checkpoint) and `.values` the
channel values (`messages`, `todos`).
"""
import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

import anthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Interrupt
from pydantic import BaseModel

from app.agents.coordinator import build_agent
from app.agents.model import AgentUnavailable
from app.agents.prompts import DISPATCH_TEMPLATES
from app.agents.translator import COORDINATOR, EventTranslator, _text
from app.models.agent_events import AgentEvent, ApprovalRequired, Done, Error, Message, RunStarted, TodoItem
from app.models.domain import ReplanEvent
from app.services.contract import Services

log = logging.getLogger(__name__)

STREAM_MODE = ["messages", "updates"]
ONE_PLAN_AT_A_TIME = "One plan at a time"
DEFAULT_REJECT_NOTE = "The dispatcher rejected this plan. It was not applied."
MAX_AUTO_REJECT_ROUNDS = 2


class ThreadBusy(Exception):
    """A run is active on the thread, or (for new runs) an approval is pending."""


class StaleApproval(Exception):
    """The approval_id is not the thread's pending interrupt."""


class UnknownThread(KeyError):
    """No thread with this id was created."""


class ChatLine(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class ThreadState(BaseModel):
    todos: list[TodoItem]
    pending_approval: ApprovalRequired | None
    messages: list[ChatLine]


def is_retryable(exc: BaseException) -> bool:
    """Rate limit, overloaded (529), 5xx and connection/timeout errors are worth retrying."""
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code == 529


def _error_fields(exc: BaseException) -> dict[str, Any]:
    # Never echo the exception text: keep the message generic (class name only) so nothing sensitive leaks.
    name = type(exc).__name__
    if isinstance(exc, anthropic.AnthropicError):
        retryable = is_retryable(exc)
        hint = " Please try again." if retryable else ""
        return {"code": "model_error", "retryable": retryable, "message": f"The model call failed ({name}).{hint}"}
    return {"code": "internal_error", "retryable": False, "message": f"The agent run failed ({name})."}


class AgentRuntime:
    def __init__(self, services: Services, model_factory: Callable[[], BaseChatModel]):
        self.services = services
        self.model_factory = model_factory
        self._checkpointer = InMemorySaver()
        self._agent: CompiledStateGraph | None = None
        self._locks: dict[str, asyncio.Lock] = {}

    # -- setup -------------------------------------------------------------------------

    def create_thread(self) -> str:
        thread_id = str(uuid.uuid4())
        self._locks[thread_id] = asyncio.Lock()
        return thread_id

    def _lock(self, thread_id: str) -> asyncio.Lock:
        try:
            return self._locks[thread_id]
        except KeyError:
            raise UnknownThread(thread_id) from None

    def _get_agent(self) -> CompiledStateGraph | None:
        """Build once on first use. AgentUnavailable is not cached, so adding a key later works."""
        if self._agent is None:
            try:
                model = self.model_factory()
            except AgentUnavailable:
                return None
            self._agent = build_agent(self.services, model, self._checkpointer)
        return self._agent

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    async def _pending_interrupt(self, thread_id: str) -> Interrupt | None:
        if self._agent is None:  # no agent yet means no run has ever checkpointed
            return None
        snap = await self._agent.aget_state(self._config(thread_id))
        return snap.interrupts[0] if snap.interrupts else None

    # -- preconditions (the route calls these before it starts a 200 stream) ------------

    async def check_run(self, thread_id: str) -> None:
        if self._lock(thread_id).locked() or await self._pending_interrupt(thread_id) is not None:
            raise ThreadBusy(thread_id)

    async def check_resume(self, thread_id: str, approval_id: str) -> Interrupt:
        if self._lock(thread_id).locked():
            raise ThreadBusy(thread_id)
        intr = await self._pending_interrupt(thread_id)
        if intr is None or intr.id != approval_id:
            raise StaleApproval(approval_id)
        return intr

    # -- runs --------------------------------------------------------------------------

    # These return the run generator itself (no wrapper generator), so closing the returned iterator
    # closes the run directly: its `finally` stops astream and releases the lock right away.

    def run_message(self, thread_id: str, text: str) -> AsyncIterator[AgentEvent]:
        return self._run(thread_id, {"messages": [{"role": "user", "content": text}]})

    def run_event(self, thread_id: str, event: ReplanEvent) -> AsyncIterator[AgentEvent]:
        # The ids were validated as SafeId by the model; only the fixed template text reaches the agent.
        return self.run_message(thread_id, DISPATCH_TEMPLATES[event.kind].format(**event.model_dump()))

    def resume(self, thread_id: str, approval_id: str, decision: Literal["approve", "reject"],
               note: str | None) -> AsyncIterator[AgentEvent]:
        return self._run(thread_id, None, resume=(approval_id, decision, note))

    @staticmethod
    def _decisions(intr: Interrupt, decision: str, note: str | None) -> list[dict]:
        """One decision per action request, in order. The human's decision covers the first apply_plan;
        every other gated call is auto-rejected, so it can never reach services.apply_plan."""
        out: list[dict] = []
        decided = False
        for action in intr.value.get("action_requests", []):
            if not decided and action.get("name") == "apply_plan":
                decided = True
                out.append({"type": "approve"} if decision == "approve"
                           else {"type": "reject", "message": note or DEFAULT_REJECT_NOTE})
            else:
                out.append({"type": "reject", "message": ONE_PLAN_AT_A_TIME})
        return out

    async def _run(self, thread_id: str, user_input: Any,
                   resume: tuple[str, str, str | None] | None = None) -> AsyncIterator[AgentEvent]:
        lock = self._lock(thread_id)
        if lock.locked():  # no await between this check and the acquire, so it is atomic
            raise ThreadBusy(thread_id)
        async with lock:
            # Re-check under the lock: the route's eager check may have raced another request.
            if resume is None:
                if await self._pending_interrupt(thread_id) is not None:
                    raise ThreadBusy(thread_id)
            else:
                approval_id, decision, note = resume
                intr = await self._pending_interrupt(thread_id)
                if intr is None or intr.id != approval_id:
                    raise StaleApproval(approval_id)
                user_input = Command(resume={"decisions": self._decisions(intr, decision, note)})

            tr = EventTranslator(thread_id, self.services)  # fresh per run: seq restarts at 0 (R7)
            yield tr.emit(RunStarted, run_id=uuid.uuid4().hex)

            try:
                agent = self._get_agent()
            except Exception as exc:  # noqa: BLE001 - a broken model config must not crash the stream
                log.warning("agent build failed: %s", type(exc).__name__)
                agent, build_error = None, exc
            else:
                build_error = None
            if agent is None:
                yield tr.emit(Error, code="model_unavailable", retryable=False,
                              message="The agent model is not configured (no API key). The rest of the app works."
                              if build_error is None else f"The agent could not start ({type(build_error).__name__}).")
                yield tr.emit(Done, status="completed")
                return

            config = self._config(thread_id)
            graph_input: Any = user_input
            for _ in range(MAX_AUTO_REJECT_ROUNDS + 1):
                stream = agent.astream(graph_input, config, stream_mode=STREAM_MODE, subgraphs=True)
                try:
                    async for chunk in stream:
                        for ev in tr.feed(chunk):
                            yield ev
                    snap = await agent.aget_state(config)
                except Exception as exc:  # noqa: BLE001 - every failure becomes an error event
                    log.warning("agent run failed on thread %s: %s", thread_id, type(exc).__name__)
                    yield tr.emit(Error, **_error_fields(exc))
                    yield tr.emit(Done, status="completed")
                    return
                finally:
                    # On client disconnect (aclose / cancellation) this stops the graph run.
                    await stream.aclose()

                if not snap.interrupts:
                    final = _final_text(snap.values.get("messages", []))
                    if final:
                        yield tr.emit(Message, text=final)
                    yield tr.emit(Done, status="completed")
                    return
                intr = snap.interrupts[0]
                if self._approval_from_checkpoint(thread_id, intr, snap.values.get("messages", [])) is not None:
                    yield tr.emit(Done, status="awaiting_approval")
                    return
                # No card can be shown (unknown plan_id; the translator already emitted `unknown_plan`).
                # Reject every request ourselves so the thread is not stuck on an invisible approval.
                graph_input = Command(resume={"decisions": _reject_all(intr)})

            yield tr.emit(Error, code="unknown_plan", retryable=False,
                          message="The agent kept requesting approval for plans that do not exist.")
            yield tr.emit(Done, status="awaiting_approval")

    # -- state -------------------------------------------------------------------------

    async def state(self, thread_id: str) -> ThreadState:
        self._lock(thread_id)  # raises UnknownThread
        if self._agent is None:
            return ThreadState(todos=[], pending_approval=None, messages=[])
        snap = await self._agent.aget_state(self._config(thread_id))
        values = snap.values or {}
        messages = values.get("messages", [])
        pending = None
        if snap.interrupts:
            pending = self._approval_from_checkpoint(thread_id, snap.interrupts[0], messages)
        return ThreadState(
            todos=[TodoItem(**t) for t in values.get("todos", [])],
            pending_approval=pending,
            messages=_chat_lines(messages),
        )

    def _approval_from_checkpoint(self, thread_id: str, intr: Interrupt, messages: list) -> ApprovalRequired | None:
        """Rebuild the card the live stream showed: first apply_plan request only, diff loaded from
        services.get_proposal (never from model args). An unknown plan_id yields no card."""
        action = next((a for a in intr.value.get("action_requests", []) if a.get("name") == "apply_plan"), None)
        args = action.get("args") if action else None
        plan_id = args.get("plan_id") if isinstance(args, dict) else None
        if not isinstance(plan_id, str):
            return None
        try:
            diff = self.services.get_proposal(plan_id).diff
        except KeyError:
            return None
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage) and _text(m.content)), None)
        return ApprovalRequired(
            thread_id=thread_id, seq=0, source=COORDINATOR, approval_id=intr.id, plan_id=plan_id, plan_diff=diff,
            rationale=_text(last_ai.content) if last_ai else "", allowed=["approve", "reject"],
        )


def _reject_all(intr: Interrupt) -> list[dict]:
    out = []
    for action in intr.value.get("action_requests", []):
        args = action.get("args")
        plan_id = args.get("plan_id") if isinstance(args, dict) else None
        out.append({"type": "reject", "message": f"ERROR: plan_id {plan_id!r} does not exist. Nothing was applied. "
                                                 "Ask the scheduler to propose a plan first."})
    return out


def _final_text(messages: list) -> str:
    last = messages[-1] if messages else None
    return _text(last.content) if isinstance(last, AIMessage) else ""


def _chat_lines(messages: list) -> list[ChatLine]:
    out: list[ChatLine] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue
        text = _text(m.content)
        if text:
            out.append(ChatLine(role=role, text=text))
    return out
