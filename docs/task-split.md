# Task split (started 2026-11-15)

Ownership paths are in `AGENTS.md` §3; the agent↔backend boundary is in §3.1. This file is the working task list. Check items off as you go, and change ownership only after agreeing in person.

## Step 0: agree on the contract together (~30 min, before splitting)

Draft for Benjamin to confirm or change. Nothing below is built yet. Models go in `backend/app/models/`, functions in `backend/app/services/`.

**Models (Pydantic)**
- `Place`: `id`, `name`, `kind` (`label|tag|synthetic`), `node_id`, `room_id`, `is_synthetic`. Comes from `NavGraph.places`, plus any synthetic ones we add.
- `StaffMember`: `id`, `role` (transporter / RT / IV nurse), `start_place_id`, `shift_start`, `shift_end`. Synthetic.
- `Job`: `id`, `kind`, `pickup_place_id`, `dropoff_place_id | None`, `earliest`, `latest`, `service_minutes`, `priority`. Priority comes from the input data, never decided by the LLM. Synthetic.
- `Plan`: `id`, `assignments` (per staff: ordered stops with ETAs and meters), `unassigned`/`infeasible` jobs **with reasons**, `total_meters`, `baseline` metrics from the same graph, start and job set.
- `PlanDiff`: what changes between the current plan and a proposed plan. The agent shows this in the approval card.
- `ApprovalRequest`: the interrupt payload that `api/agent.py` sends to the UI. It wraps a `PlanDiff` plus the agent's short rationale.

**Service functions (sync is fine for now)**
```python
list_places() -> list[Place]
list_staff() -> list[StaffMember]
list_jobs(status: str | None = None) -> list[Job]
get_current_plan() -> Plan
propose_plan(job_ids: list[str] | None = None) -> Plan            # optimizer, no side effects
propose_replan(event: ReplanEvent) -> tuple[Plan, PlanDiff]        # e.g. new STAT job, staff unavailable
apply_plan(plan_id: str) -> Plan                                  # only after human approval
route_between(a_place_id: str, b_place_id: str) -> Route          # meters + node path, for UI/explanations
```

## Minh: FastAPI agent endpoints + Deep Agent

Read `deepagents-notes.md` and check the docs MCP servers first (AGENTS.md §6).

- [ ] Add `deepagents`, `langchain-aws` (Bedrock) and `fastapi` deps. Coordinate the `pyproject.toml` edit with Benjamin; `uv add` in one commit.
- [ ] `backend/app/agents/`: build the Deep Agent on Bedrock with a system prompt that encodes the product rules (no clinical decisions, no invented data, IDs only).
- [ ] `backend/app/tools/`: thin tools over the service functions above. Stub the services that don't exist yet.
- [ ] HITL: `interrupt_on` for `apply_plan`. Resume with approve/reject/edit.
- [ ] `backend/app/api/agent.py`: `POST /agent/chat` (streamed), `POST /agent/approvals/{id}` (approve/reject), and thread/session handling via a checkpointer.
- [ ] Bedrock failure path: the app keeps working without the agent (AGENTS.md §7).
- [ ] Tests: tools call services with the right args; a reject never calls `apply_plan`.

## Benjamin: optimizer, main backend, frontend

Read `docs/handoff-2026-11-15.md` first. It covers the nav graph, the exporter, and the data caveats.

- [ ] Take over `backend/app/spatial/` (nav graph v1 is done, with 19 tests). Spot-check the 15 out-of-room place snaps.
- [ ] Generate synthetic staff and jobs on Airedale places, deterministic from a seed and clearly labeled synthetic.
- [ ] `backend/app/optimization/`: OR-Tools on `NavGraph.distance_matrix`, with pickup before dropoff, time windows and priorities. Infeasible jobs are flagged, never dropped. Use small deterministic fixtures.
- [ ] Baseline vs optimized metrics on the same graph, start and job set (no hardcoded improvements).
- [ ] `backend/app/services/`: implement the contract above.
- [ ] `backend/app/main.py` + `backend/app/api/`: app setup, CORS, endpoints for places/staff/jobs/plans/routes, and loading the nav graph at startup.
- [ ] Frontend: pick the framework (it's still TBD in AGENTS.md §4; update it there). Then build the 2D floor plan with routes, the Matterport Showcase view (localhost only), the plan view, the chat panel, and the approval card.
