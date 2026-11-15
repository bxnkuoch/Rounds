# Rounds agent (Minh)

A LangChain Deep Agent (coordinator plus a scheduler subagent) on Claude Haiku 5.5 via the Anthropic API. It calls the service functions in `backend/app/services/` through the thin tools in `backend/app/tools/`. `apply_plan` is gated by `interrupt_on`, so a human must approve every schedule change.

Layout: `model.py` (model config), `prompts.py`, `coordinator.py` (agent graph), `translator.py` (LangGraph stream to `AgentEvent`), `runtime.py` (threads, locks, dispatch inbox, approvals). HTTP routes are in `backend/app/api/agent.py`. Event models are in `backend/app/models/agent_events.py` (v0, provisional, Benjamin to confirm).

## Env vars

Both go in repo-root `local.env` (gitignored; real environment variables override it):

- `ANTHROPIC_API_KEY`: required to run the agent. Without it, a message run yields `error(code="model_unavailable")` then `done`; the rest of the app keeps working.
- `AGENT_MODEL`: optional, default `anthropic:claude-haiku-5-5`.

## Run the dev app

Until `main.py` mounts the router, use the dev-only app (from `backend/`). It needs no key to start; the model is built lazily on the first run:

```bash
uv run uvicorn app.agent_dev_app:app --reload --port 8000
```

## Endpoints (SSE responses; use `curl -N`)

```bash
# create a thread (plain JSON) -> {"thread_id": "..."}
curl -s -X POST localhost:8000/agent/threads

# send a chat message (SSE stream; text is 1..4000 chars)
curl -N -X POST localhost:8000/agent/threads/$T/messages \
  -H 'content-type: application/json' -d '{"text": "What places are on the unit?"}'

# dispatch inbox event (SSE). Body is a ReplanEvent: job_added or staff_unavailable
curl -N -X POST localhost:8000/agent/threads/$T/events \
  -H 'content-type: application/json' -d '{"kind": "job_added", "job_id": "job-123"}'

# approve or reject a pending proposal (SSE). approval_id comes from the approval_required event
curl -N -X POST localhost:8000/agent/threads/$T/approvals/$APPROVAL_ID \
  -H 'content-type: application/json' -d '{"decision": "approve"}'   # or "reject", optional "note"

# thread state (plain JSON): todos, pending_approval, messages
curl -s localhost:8000/agent/threads/$T/state
```

Status codes: 404 unknown thread; 409 thread busy or awaiting approval (on messages/events), or stale/unknown approval (on approvals). These are returned before the stream starts.

## Event contract (summary)

Each SSE frame is `data: <json>\n\n`. Every event has `type`, `thread_id`, `seq`, `source` (`coordinator` or a subagent name). Types:

| type | extra fields |
|---|---|
| `run_started` | `run_id` |
| `token` | `text` |
| `todos` | `items[]` of `{content, status: pending/in_progress/completed}` |
| `tool_call` | `tool_call_id`, `name`, `args` |
| `tool_result` | `tool_call_id`, `name`, `ok`, `summary` |
| `subagent_started` / `subagent_finished` | `subagent`, `task_id` |
| `approval_required` | `approval_id`, `plan_id`, `plan_diff`, `rationale`, `allowed` (`approve`/`reject`) |
| `message` | `text` (the final assistant message) |
| `done` | `status`: `completed` or `awaiting_approval` |
| `error` | `code`, `message`, `retryable` (e.g. `model_unavailable`, `thread_busy`, `stale_approval`) |

A run ends with `done`. After `done(awaiting_approval)`, POST the approval to resume. The approval card's `plan_diff` comes from `services.get_proposal(plan_id)`, never from model arguments.

## Known limitations

- State (threads, checkpoints, pending approvals) is in memory and lost on restart.
- `seq` restarts at 0 every run, so order events per run (use `run_id`), not per thread.
- `ThreadState` and `ChatLine` live in `runtime.py` for now and should move to `app/models/`.
- The stub services (`StubServices`) raise `NotImplementedError` except `list_places` and `route_between`; the agent reports the failed tool call instead of inventing a plan until Benjamin implements the services.
- Place and route tools need the Airedale nav graph export (`backend/data/raw/matterport/6Ee2LwLfx58.json`, gitignored). Without it they return errors.
- `edit` decisions on approvals are not supported this stage.

## Real-key smoke run (not done yet)

No `ANTHROPIC_API_KEY` was available when this was written; only offline tests and a no-key sanity check have run. To do it (costs about 1 cent):

1. Put `ANTHROPIC_API_KEY=...` in `local.env`, start the dev app, create a thread.
2. Send "What places are on the unit?" and expect a `tool_call` `list_places` with real Airedale names.
3. Send "Make a plan for my shift" and expect a `tool_result` with `ok=false` (stub `NotImplementedError`) and a message that reports it rather than inventing a plan.
