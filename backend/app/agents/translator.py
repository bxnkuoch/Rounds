"""LangGraph stream chunks -> typed AgentEvents. The only code that knows LangGraph's stream format."""
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.models.agent_events import (
    AgentEvent, ApprovalRequired, Error, SubagentFinished, SubagentStarted, TodoItem, Todos, Token, ToolCall,
    ToolResult,
)
from app.services.contract import Services

COORDINATOR = "coordinator"


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in content
                       if isinstance(b, str) or (isinstance(b, dict) and b.get("type") == "text"))
    return ""


class EventTranslator:
    def __init__(self, thread_id: str, services: Services):
        self.thread_id = thread_id
        self.services = services
        self._seq = 0
        self._task_subagent: dict[str, str] = {}   # task tool_call_id -> subagent name
        self._pending_tasks: list[str] = []        # task call ids whose namespace is not yet known
        self._ns_names: dict[str, str] = {}        # "tools:<uuid>" segment -> subagent name
        self._call_names: dict[str, str] = {}      # tool_call_id -> tool name
        self._buf = ""                             # coordinator tokens of the message in flight
        self._last_text = ""                       # coordinator's most recent finished AI text

    def emit(self, event_cls: type, source: str = COORDINATOR, **fields: Any) -> AgentEvent:
        """Build an event with the next seq. The runtime uses this for run_started/message/done/error."""
        ev = event_cls(thread_id=self.thread_id, seq=self._seq, source=source, **fields)
        self._seq += 1
        return ev

    def feed(self, chunk: tuple) -> list[AgentEvent]:
        """Translate one item of agent.stream(..., stream_mode=["messages","updates"], subgraphs=True).

        Confirmed shape (langgraph 1.2.22, deepagents 0.7.38): chunk = (namespace, mode, data).
        - namespace: () for the coordinator; ("tools:<uuid>",) for a subagent run by the `task` tool. The
          uuid is NOT the task tool_call id, so the namespace is mapped to a subagent name via, in order:
          the id itself if it equals a known task call id, `lc_agent_name` in messages-mode metadata
          (the subagent's name, set before its first model update), the subagent AIMessage.name, then
          the oldest task call not yet matched to a namespace.
        - mode "messages": data = (message_chunk, metadata). Used ONLY for coordinator text tokens and
          namespace discovery. Tool calls/results are never taken from here (they would duplicate).
        - mode "updates": data = {node_name: output | None}. Node "model" output has
          {"messages": [AIMessage]} (tool calls; each call appears exactly once), node "tools" output
          has {"messages": [ToolMessage...]} and, for write_todos, a "todos" list. Middleware nodes
          ("PatchToolCallsMiddleware.before_agent", ...) carry None and are ignored.
        - Interrupt: updates data = {"__interrupt__": (Interrupt, ...)} at namespace () (tuple or list).
          Interrupt.value = {"action_requests": [{name, args, description}], "review_configs": [...]}.
        """
        ns, mode, data = chunk
        if mode == "messages":
            return self._on_message(ns, data)
        if mode == "updates" and isinstance(data, dict):
            return self._on_update(ns, data)
        return []

    # -- source resolution ---------------------------------------------------------

    def _source(self, ns: tuple, agent_name: str | None = None) -> str:
        seg = next((s for s in reversed(ns) if s.startswith("tools:")), None)
        if seg is None:
            return COORDINATOR
        if seg not in self._ns_names:
            call_id = seg.split(":", 1)[1]
            if call_id in self._task_subagent:
                name = self._task_subagent[call_id]
                if call_id in self._pending_tasks:
                    self._pending_tasks.remove(call_id)
            elif agent_name:
                name = agent_name
                self._claim_pending(agent_name)
            elif self._pending_tasks:
                name = self._task_subagent[self._pending_tasks.pop(0)]
            else:
                return "subagent:unknown"
            self._ns_names[seg] = name
        return f"subagent:{self._ns_names[seg]}"

    def _claim_pending(self, name: str) -> None:
        for cid in self._pending_tasks:
            if self._task_subagent[cid] == name:
                self._pending_tasks.remove(cid)
                return

    # -- messages mode ---------------------------------------------------------------

    def _on_message(self, ns: tuple, data: Any) -> list[AgentEvent]:
        msg, meta = data
        agent_name = (meta or {}).get("lc_agent_name")
        source = self._source(ns, agent_name)
        if source != COORDINATOR or not isinstance(msg, AIMessageChunk):
            return []
        text = _text(msg.content)
        if not text:
            return []
        self._buf += text
        return [self.emit(Token, text=text)]

    # -- updates mode ----------------------------------------------------------------

    def _on_update(self, ns: tuple, data: dict) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for node, out in data.items():
            if node == "__interrupt__":
                for intr in out:
                    events += self._on_interrupt(ns, intr)
                continue
            if not isinstance(out, dict):
                continue
            msgs = out.get("messages") or []
            agent_name = next((m.name for m in msgs if isinstance(m, AIMessage) and m.name), None)
            source = self._source(ns, agent_name)
            if "todos" in out:
                events.append(self.emit(Todos, source=source, items=[TodoItem(**t) for t in out["todos"]]))
            for m in msgs:
                if isinstance(m, AIMessage):
                    events += self._on_ai(source, m)
                elif isinstance(m, ToolMessage):
                    events += self._on_tool_message(source, m)
        return events

    def _on_ai(self, source: str, m: AIMessage) -> list[AgentEvent]:
        if source == COORDINATOR:
            text = _text(m.content)
            if text:
                self._last_text = text
            self._buf = ""
        events: list[AgentEvent] = []
        for tc in m.tool_calls:
            self._call_names[tc["id"]] = tc["name"]
            events.append(self.emit(ToolCall, source=source, tool_call_id=tc["id"], name=tc["name"], args=tc["args"]))
            if tc["name"] == "task":
                sub = tc["args"].get("subagent_type", "unknown")
                self._task_subagent[tc["id"]] = sub
                self._pending_tasks.append(tc["id"])
                events.append(self.emit(SubagentStarted, source=source, subagent=sub, task_id=tc["id"]))
        return events

    def _on_tool_message(self, source: str, m: ToolMessage) -> list[AgentEvent]:
        content = _text(m.content) if not isinstance(m.content, str) else m.content
        name = m.name or self._call_names.get(m.tool_call_id, "")
        ok = not content.startswith("ERROR:") and m.status != "error"
        events: list[AgentEvent] = [
            self.emit(ToolResult, source=source, tool_call_id=m.tool_call_id, name=name, ok=ok, summary=content[:200])
        ]
        if name == "task":
            events.append(self.emit(
                SubagentFinished, source=source,
                subagent=self._task_subagent.get(m.tool_call_id, "unknown"), task_id=m.tool_call_id,
            ))
        return events

    def _on_interrupt(self, ns: tuple, intr: Any) -> list[AgentEvent]:
        source = self._source(ns)
        for action in intr.value.get("action_requests", []):
            if action.get("name") != "apply_plan":
                continue
            args = action.get("args")
            plan_id = args.get("plan_id") if isinstance(args, dict) else None
            try:
                if not isinstance(plan_id, str):
                    raise KeyError(plan_id)
                diff = self.services.get_proposal(plan_id).diff
            except Exception:  # noqa: BLE001 - unknown plan or broken services: an error event, never a raise
                return [self.emit(Error, source=source, code="unknown_plan", retryable=False,
                                  message=f"Proposal {plan_id!r} does not exist.")]
            return [self.emit(
                ApprovalRequired, source=source, approval_id=intr.id, plan_id=plan_id, plan_diff=diff,
                rationale=self._buf or self._last_text, allowed=["approve", "reject"],
            )]
        return []
