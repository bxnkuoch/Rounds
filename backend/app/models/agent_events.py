# v0: provisional, Benjamin to confirm
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.models.domain import PlanDiff


class _Event(BaseModel):
    type: str
    thread_id: str
    seq: int
    source: str


class RunStarted(_Event):
    type: Literal["run_started"] = "run_started"
    run_id: str


class Token(_Event):
    type: Literal["token"] = "token"
    text: str


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "completed"]


class Todos(_Event):
    type: Literal["todos"] = "todos"
    items: list[TodoItem]


class ToolCall(_Event):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    name: str
    args: dict


class ToolResult(_Event):
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    ok: bool
    summary: str


class SubagentStarted(_Event):
    type: Literal["subagent_started"] = "subagent_started"
    subagent: str
    task_id: str


class SubagentFinished(_Event):
    type: Literal["subagent_finished"] = "subagent_finished"
    subagent: str
    task_id: str


class ApprovalRequired(_Event):
    type: Literal["approval_required"] = "approval_required"
    approval_id: str
    plan_id: str
    plan_diff: PlanDiff
    rationale: str
    allowed: list[Literal["approve", "reject"]]


class Message(_Event):
    type: Literal["message"] = "message"
    text: str


class Done(_Event):
    type: Literal["done"] = "done"
    status: Literal["completed", "awaiting_approval"]


class Error(_Event):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool


AgentEvent = Annotated[
    Union[
        RunStarted, Token, Todos, ToolCall, ToolResult, SubagentStarted,
        SubagentFinished, ApprovalRequired, Message, Done, Error,
    ],
    Field(discriminator="type"),
]


def to_sse(event: AgentEvent) -> str:
    return "data: " + event.model_dump_json() + "\n\n"


class ChatLine(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class ThreadState(BaseModel):
    todos: list[TodoItem]
    pending_approval: ApprovalRequired | None
    messages: list[ChatLine]
