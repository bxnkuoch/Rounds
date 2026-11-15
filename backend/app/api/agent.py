"""Agent endpoints: chat, dispatch inbox, approvals (SSE), and thread state.

Preconditions (unknown thread 404, busy 409, stale approval 409) are checked BEFORE the stream starts, so
the client gets a real status code instead of a 200 with an error in the body.
"""
import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.types import Receive, Scope, Send

from app.agents.translator import COORDINATOR
from app.agents.runtime import AgentRuntime, StaleApproval, ThreadBusy, UnknownThread
from app.models.agent_events import AgentEvent, Done, Error, ThreadState, to_sse
from app.models.domain import ReplanEvent

router = APIRouter(prefix="/agent", tags=["agent"])


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.agent_runtime


class ThreadCreated(BaseModel):
    thread_id: str


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ApprovalIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)


async def _guard(check) -> None:
    try:
        await check
    except UnknownThread:
        raise HTTPException(404, "unknown thread") from None
    except ThreadBusy:
        raise HTTPException(409, "thread is busy or awaiting approval") from None
    except StaleApproval:
        raise HTTPException(409, "approval is stale or unknown") from None


class RunStreamingResponse(StreamingResponse):
    """StreamingResponse that cancels the run as soon as the client disconnects, on every ASGI spec version.

    Starlette 1.10 only listens for `http.disconnect` when spec_version < 2.4. On >= 2.4 a disconnect shows up
    only as an OSError on the next send, which may never come while a model call is in flight, and the body
    iterator is left to the async-gen finalizer. Here the stream always races a disconnect listener.

    The stream runs in its own asyncio task and is cancelled ONCE with task.cancel(). Starlette's anyio
    cancel scope re-delivers cancellation at every await, which interrupts LangGraph's own astream cleanup
    before it cancels the in-flight node (the model call kept running). The final close is shielded, so the
    run generator's `finally` always runs and the thread lock is always released.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def stream() -> None:
            try:
                await self.stream_response(send)
            except OSError:
                pass  # client went away mid-send

        stream_task = asyncio.ensure_future(stream())
        watch_task = asyncio.ensure_future(self.listen_for_disconnect(receive))
        try:
            await asyncio.wait({stream_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            with anyio.CancelScope(shield=True):
                for task in (stream_task, watch_task):
                    task.cancel()
                await asyncio.gather(stream_task, watch_task, return_exceptions=True)
                await self.body_iterator.aclose()
        if not stream_task.cancelled() and stream_task.exception() is not None:
            raise stream_task.exception()  # a real failure, not a disconnect: let the server see it
        if self.background is not None:
            await self.background()


def _sse(thread_id: str, events: AsyncIterator[AgentEvent]) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        try:
            async for ev in events:
                yield to_sse(ev)
        except (ThreadBusy, StaleApproval) as exc:
            # Lost a race with another request after the eager check passed: report it in-stream.
            busy = isinstance(exc, ThreadBusy)
            yield to_sse(Error(thread_id=thread_id, seq=0, source=COORDINATOR, retryable=False,
                               code="thread_busy" if busy else "stale_approval",
                               message="Another request is using this thread." if busy
                               else "This approval is no longer pending."))
            yield to_sse(Done(thread_id=thread_id, seq=1, source=COORDINATOR, status="completed"))
        finally:
            with anyio.CancelScope(shield=True):
                await events.aclose()  # stops the agent run and releases the thread lock

    return RunStreamingResponse(body(), media_type="text/event-stream",
                                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/threads")
async def create_thread(runtime: AgentRuntime = Depends(get_runtime)) -> ThreadCreated:
    return ThreadCreated(thread_id=runtime.create_thread())


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageIn, runtime: AgentRuntime = Depends(get_runtime)):
    await _guard(runtime.check_run(thread_id))
    return _sse(thread_id, runtime.run_message(thread_id, body.text))


@router.post("/threads/{thread_id}/events")
async def post_event(thread_id: str, event: ReplanEvent, runtime: AgentRuntime = Depends(get_runtime)):
    await _guard(runtime.check_run(thread_id))
    return _sse(thread_id, runtime.run_event(thread_id, event))


@router.post("/threads/{thread_id}/approvals/{approval_id}")
async def post_approval(thread_id: str, approval_id: str, body: ApprovalIn,
                        runtime: AgentRuntime = Depends(get_runtime)):
    await _guard(runtime.check_resume(thread_id, approval_id))
    return _sse(thread_id, runtime.resume(thread_id, approval_id, body.decision, body.note))


@router.get("/threads/{thread_id}/state")
async def get_state(thread_id: str, runtime: AgentRuntime = Depends(get_runtime)) -> ThreadState:
    try:
        return await runtime.state(thread_id)
    except UnknownThread:
        raise HTTPException(404, "unknown thread") from None
