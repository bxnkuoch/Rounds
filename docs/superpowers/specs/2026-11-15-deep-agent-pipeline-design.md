# Design: Deep Agent pipeline, end to end against stubs

Date: 2026-11-15 · Owner: Minh · Status: proposed

## Intent

Rounds needs an AI coordinator that turns plain-language requests ("STAT blood gas in Room 4, fit it in") into visible planning steps and tool calls, and then **pauses for a human to approve** any schedule change before it applies. That pause is our clinical-safety story and a core part of the LangChain "Best Use of DeepAgents" pitch.

At this stage Benjamin's services (optimizer, jobs, plans) don't exist yet. The goal is to **prove the riskiest plumbing early, end to end:**

chat → agent → tools → approval pause → approve/reject → resume, all streamed to the frontend.

We build this against stubbed services so Benjamin's frontend can integrate against it right away, and so the real services slot in later without changes to the agent side.

## Goals

- A Deep Agent (coordinator + one `scheduler` subagent + todo list) that calls tools wrapping **service functions** (AGENTS.md §3.1).
- **Human approval is mandatory before `apply_plan`.** The schedule never changes without a human approve.
- FastAPI endpoints in `backend/app/api/agent.py` that stream a **typed event protocol of our own** to the frontend, and accept approve/reject decisions that resume the run.
- **Tests run with a fake model:** no API key, no network, deterministic.
- The real model is **Claude Haiku 5.5 via the Anthropic API**, chosen by config (`AGENT_MODEL`).

## Non-goals (this stage)

- **The real optimizer and services.** Benjamin owns them; we use stubs.
- **More subagents** (spatial, explainer), memory across shifts, the shift handoff report, and filesystem artifacts. These come next stage, on top of this pipeline.
- **Frontend UI.** Benjamin builds it; we only define the event contract.
- **Persistence across server restarts.** Conversation state is in memory.
- **Auth, multi-user, and deployment.**

## Anti-goals (failure even if it "works")

- **The LLM computes or invents anything.** No routes, distances, ETAs, priorities, job IDs or places from the model. Tools return service output, and the model only relays and explains it.
- **The agent creates or edits a job.** New jobs only enter through the dispatch inbox (below), never through chat.
- **A schedule change applies without an explicit human approve.** This includes edge cases: errors, timeouts, a rejected or missing decision, or the subagent calling `apply_plan` directly.
- **LangGraph internals leak into the frontend contract.** If a library upgrade changes LangGraph's stream format, only our translator changes, never the event schema.
- **The frontend contract is raw LangGraph interrupt dicts** instead of our plan diff.

## Constraints

- **Library versions:** `deepagents` 0.7.x (0.7.38 latest at time of writing). Check the docs MCP servers before writing code, per AGENTS.md §6. Confirmed facts:
  - `write_todos` needs `TodoListMiddleware()`.
  - `interrupt_on` needs a checkpointer and the same `thread_id` on resume.
  - Subagent interrupts surface in the parent stream.
  - `allowed_decisions` can restrict a tool to `["approve", "reject"]`.
- **Model:** `AGENT_MODEL=anthropic:claude-haiku-5-5` and `ANTHROPIC_API_KEY`, both in `local.env`. Switching to Sonnet or Opus is a config change. No Bedrock and no AWS credits; the Amazon track claim in `pitch.md` must be dropped or reworded.
- **Ownership:** Minh owns `backend/app/agents/`, `backend/app/tools/` and `backend/app/api/agent.py`. Stubs go in `backend/app/services/` (Benjamin's) only with the signatures agreed in `docs/task-split.md` Step 0, so Benjamin replaces their bodies. Event models go in `backend/app/models/` (shared; announce changes).
- **Graceful degradation (AGENTS.md §7):** if the model or key is unavailable, `/agent/*` returns a clear error event and the rest of the app keeps working.
- **No patient-identifying data** goes to the LLM; use IDs only. All jobs and staff are synthetic.

## Approaches considered

1. **Our own typed event stream from FastAPI (chosen).** `api/agent.py` runs the agent and translates its stream into a small Pydantic event schema, sent as Server-Sent Events.
   - *Pros:* works with any frontend framework; the approval card carries our `PlanDiff`; it keeps the Minh/Benjamin seam clean.
   - *Cons:* about 150 lines of translation layer to write and test, and Benjamin hand-builds the chat/todo UI.
2. **LangGraph Agent Server + React `useStream`.**
   - *Pros:* least code, and polished subagent and approval UI out of the box.
   - *Cons:* forces React, adds a second backend server next to FastAPI, and the approval payload is in LangGraph's shape.
3. **FastAPI passing LangGraph's raw stream through.**
   - *Pros:* almost no backend code.
   - *Cons:* the frontend parses LangGraph internals, the contract isn't ours, and upgrades can break the UI.

**Picked: 1** (Minh, 2026-11-15). It is the only option that keeps a stable contract we own and shows a real plan diff on the approval card.

## Design

### Agent shape (`backend/app/agents/`)

- **Coordinator** (`create_deep_agent`):
  - Model from `AGENT_MODEL`.
  - `middleware=[TodoListMiddleware()]`.
  - Checkpointer `InMemorySaver`.
  - Its tools are the read tools plus `apply_plan`.
  - `interrupt_on={"apply_plan": {"allowed_decisions": ["approve", "reject"]}}`. No `edit` this stage, so a human can't hand-alter optimizer output without it being recomputed.
- **`scheduler` subagent:**
  - Tools: `list_jobs`, `get_current_plan`, `propose_plan`, `propose_replan`.
  - It proposes plans and returns a summary plus the proposed `plan_id`, and **does not have `apply_plan`**. Only the coordinator applies, which keeps the approval point in one place.
- **System prompt** encodes the product rules:
  - The model never computes or estimates distances, times, orderings or priorities; it uses tools and quotes their numbers.
  - Every schedule change goes through `apply_plan`, which a human approves.
  - Infeasible jobs are always reported, never dropped.
  - No clinical judgments; priorities come from the data.
  - Refer to jobs, places and staff by ID and name only.
- **Other built-in tools:** the built-in `general-purpose` subagent and the filesystem tools stay at their defaults this stage. Exposing the filesystem tools is harmless with the in-memory state backend; to be revisited next stage.

### Tools (`backend/app/tools/`)

Thin wrappers. Each one calls exactly one service function from the Step 0 contract and returns its Pydantic result serialized as JSON. Tools contain no logic.

| Tool | Service function |
|---|---|
| `list_places` | `list_places()` |
| `list_staff` | `list_staff()` |
| `list_jobs` | `list_jobs(status)` |
| `get_current_plan` | `get_current_plan()` |
| `propose_plan` | `propose_plan(job_ids)` |
| `propose_replan` | `propose_replan(event)` |
| `route_between` | `route_between(a, b)` |
| `apply_plan` | `apply_plan(plan_id)` (gated) |

Service exceptions (including `NotImplementedError` from stubs) become a tool error message the model sees, never a crash.

### Where new jobs come from: the dispatch inbox (decided by Minh: option A)

New requests ("STAT blood gas, Room 4") arrive as **structured jobs from outside the agent**, the way orders come from a hospital's order system.

- **Creating the job:** the UI has a "New request" form and a "simulate STAT call" button (Benjamin's). They call Benjamin's job service, which creates the job. Its kind, place, time window and **priority come from that input**, never from the model.
- **Notifying the agent:** the UI then calls `POST /agent/threads/{thread_id}/events` with `{"kind": "job_added", "job_id": "J-17"}`. Our code turns that into a fixed, templated user message ("Dispatch: new job J-17 arrived. Propose a replan.") built only from IDs. No free text from the event reaches the model.
- **The agent's part:** it looks the job up with `list_jobs`, asks the `scheduler` subagent for `propose_replan`, and pauses for approval on `apply_plan`.
- **No job tools:** the agent has no tool that creates or edits jobs. Chat-drafted jobs (option B) are deferred to a later stage.
- **`ReplanEvent` (v0)** carries IDs only: `{kind: "job_added", job_id}` or `{kind: "staff_unavailable", staff_id}`.

### Services and stubs

- **Models:** Step 0 models (`Place`, `StaffMember`, `Job`, `Plan`, `PlanDiff`, `ReplanEvent`, `Route`) go into `backend/app/models/`.
  - **They're provisional:** each file carries a `# v0: provisional, Benjamin to confirm` header so the frontend can start now.
  - **If Benjamin changes a field,** he updates the model, and the translator and fixtures follow it. The event envelope itself is ours and stays stable.
  - **v0 shapes:**
    - `Plan {id, created_at, assignments: [{staff_id, stops: [{job_id, place_id, action: "pickup"|"dropoff"|"service", eta, meters_from_prev}]}], infeasible: [{job_id, reason}], total_meters, baseline: {total_meters, late_jobs} | None}`
    - `PlanDiff {from_plan_id | None, to_plan_id, added_job_ids, removed_job_ids, reordered_staff_ids, newly_infeasible: [{job_id, reason}], meters_delta, late_jobs_delta}`
    - `Proposal {plan: Plan, diff: PlanDiff}`
- **One new service function (Minh's call, to agree with Benjamin):** `get_proposal(plan_id) -> Proposal`.
  - `propose_plan` and `propose_replan` both **store** their proposal, with a diff against the current plan, and return a `Proposal`.
  - `apply_plan` only accepts a stored, unapplied `plan_id`.
  - An unknown or stale `plan_id` raises; the tool turns that into an error, never into an apply.
- **Stubs:** `backend/app/services/` gets functions with those signatures that `raise NotImplementedError`. The exception is `route_between` and `list_places`, which can be real today using `NavGraph` (`backend/app/spatial/nav_graph.py`) on the Airedale export.
- **Tests:** inject **fake services** that return small fixed fixtures (labeled test data, never shown as real). Inject them through a `services` object passed when building the agent, so tests and the real app swap implementations without patching.

### Event protocol (`backend/app/models/agent_events.py`, shared contract)

SSE, one JSON object per `data:` line. Every event has `type`, `thread_id`, `seq` (increasing per run) and `source` (`"coordinator"` or `"subagent:<name>"`).

| `type` | Payload | Emitted when |
|---|---|---|
| `run_started` | `run_id` | a run or resume begins |
| `token` | `text` | the model streams text (coordinator only this stage) |
| `todos` | `items: [{content, status}]` | `write_todos` updates state |
| `tool_call` | `tool_call_id, name, args` | a tool is called |
| `tool_result` | `tool_call_id, name, ok, summary` | a tool returns or errors |
| `subagent_started` / `subagent_finished` | `subagent, task_id` | `task` delegation starts/ends |
| `approval_required` | `approval_id, plan_id, plan_diff, rationale, allowed: ["approve","reject"]` | `apply_plan` interrupts |
| `message` | `text` | final assistant message of the run |
| `done` | `status: "completed" \| "awaiting_approval"` | the stream ends |
| `error` | `code, message, retryable` | model unavailable, bad key, internal error |

- **Where `plan_diff` comes from:** in the `approval_required` event it is loaded from the services (the proposal stored for `plan_id`), **not** taken from the model's tool arguments. The model only passes `plan_id`, so the card always shows optimizer output.
- **Mapping:** the translator maps LangGraph stream chunks (`stream_mode=["messages","updates"]`, `subgraphs=True`, namespaces identify subagents) onto these events. It is the only code that knows LangGraph's stream format.

### Endpoints (`backend/app/api/agent.py`, mounted by Benjamin's `main.py`)

- **`POST /agent/threads`** → `{thread_id}`.
- **`POST /agent/threads/{thread_id}/messages`**, body `{text}` → SSE stream of events until `done`.
- **`POST /agent/threads/{thread_id}/approvals/{approval_id}`**, body `{decision: "approve"|"reject", note?}` → SSE stream of the resumed run.
  - Rejects a stale or unknown `approval_id` with 409.
  - Reject sends `{"type": "reject", "message": note}` so the agent can respond.
- **`GET /agent/threads/{thread_id}/state`** → current todos, pending approval if any, and message history, so the UI can rehydrate after a refresh.
- **`POST /agent/threads/{thread_id}/events`**, body `{kind: "job_added", job_id}` or `{kind: "staff_unavailable", staff_id}` → SSE stream. This is the dispatch inbox's templated message (see above).
- **One run at a time per thread:** a second message or event while a run is active or awaiting approval → 409.
- **A run is tied to its HTTP request (Minh's call).**
  - If the client disconnects, the run is cancelled. The thread keeps its last checkpoint, and the user can resend.
  - A run that already reached the approval pause keeps it, because the pause lives in the checkpoint. So a page refresh shows the pending approval again through `GET /state`, and approving still works.
  - Background runs and a "re-attach to stream" endpoint are out of scope this stage.

Until `main.py` exists, Minh ships a tiny `app/agent_dev_app.py` that mounts only the agent router for local testing. It is deleted once Benjamin's app mounts the router.

### Model and config

- **`backend/app/agents/model.py`** builds the chat model from `AGENT_MODEL` (default `anthropic:claude-haiku-5-5`), reading `ANTHROPIC_API_KEY` from `local.env`.
- **Tests** use LangChain's fake chat model with scripted tool calls, so tool calling, the approval pause and resume all run without network.
- **Prompt caching** on the system prompt and tool list if `langchain-anthropic` supports it cleanly. Builder to verify; skip if it's fiddly.

### Testing (all offline)

- **Tool tests:** each tool calls its service with the right args; a service error becomes a tool error, not a crash.
- **Translator tests:** recorded or synthetic LangGraph chunks → expected event sequence, including subagent namespaces and the interrupt.
- **Pipeline tests** with the fake model and fake services:
  - message → `todos` → `tool_call`/`tool_result` → `approval_required` → `done(awaiting_approval)`.
  - approve → `apply_plan` called exactly once.
  - reject → `apply_plan` **never** called, and the agent replies.
  - stale approval → 409.
  - a dispatch `job_added` event → templated message → `propose_replan` → `approval_required` whose `plan_diff` equals the stored proposal's diff.
  - a refresh after the approval pause: `GET /state` shows the pending approval, and approving resumes the run.
  - second message while pending → 409.
  - model init failure → `error` event.
- **Safety test:** a scripted subagent attempt to apply a plan is impossible (tool not available), and no code path calls `services.apply_plan` without a recorded approve.
- **One manual smoke run with the real Haiku 5.5 key**, reported separately. Not in CI; it costs money.

## Decided vs left to the builder

**Decided:**
- Approach 1.
- Haiku 5.5 via the Anthropic API.
- Coordinator + `scheduler` subagent + todos.
- Approval on `apply_plan` with approve/reject only; only the coordinator has `apply_plan`.
- `plan_diff` comes from services, not model args.
- The event types above.
- In-memory checkpointer.
- Offline tests with a fake model.

**Left to the builder:**
- Exact LangGraph stream API (`stream` with modes vs `stream_events` v3), whichever maps cleanly to the events; verify against the installed version.
- SSE implementation (`sse-starlette` or `StreamingResponse`).
- How the fake model scripts tool calls.
- File layout inside `agents/` and `tools/`.
- Whether `token` events for subagents are worth emitting.
- Prompt-caching details.

**Builder's calls (marked by Minh's agent while writing):**
- No `edit` decision this stage.
- Default filesystem and general-purpose subagent left on.
- Dev-only app file until `main.py` exists.
- `get_proposal` added to the contract.
- v0 provisional schemas.
- Runs tied to the request.

**Decided by Minh after review:** new jobs come only from the dispatch inbox (option A).
