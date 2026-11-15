# Task split (started 2026-11-15)

Ownership paths are in `AGENTS.md` §3; the agent↔backend boundary is in §3.1. This file is the working task list. Check items off as you go, and change ownership only after agreeing in person.

## Step 0: agree on the contract together (~30 min, before splitting)

Draft for Benjamin to confirm or change. The models are in `backend/app/models/` (v0, provisional) and the service seam is `backend/app/services/contract.py` (a `Services` Protocol; `StubServices` stands in until Benjamin's implementation lands).

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
get_current_plan() -> Plan | None                                 # None until a plan has been applied
propose_plan(job_ids: list[str] | None = None) -> Proposal        # optimizer; stores the proposal, does not apply it
propose_replan(event: ReplanEvent) -> Proposal                    # e.g. new STAT job, staff unavailable; stores the proposal
get_proposal(plan_id: str) -> Proposal                            # the proposed plan + its PlanDiff; raises KeyError for an unknown id. The approval card is built from this, never from model args
apply_plan(plan_id: str) -> Plan                                  # only after human approval. KeyError: unknown id. ValueError: already applied, or stale (the proposal's diff.from_plan_id is not the current plan)
route_between(a_place_id: str, b_place_id: str) -> Route          # meters + node path, for UI/explanations
```

## Minh: FastAPI agent endpoints + Deep Agent

Read `deepagents-notes.md` and check the docs MCP servers first (AGENTS.md §6).

- [x] Add `deepagents`, `langchain-anthropic` and `fastapi` deps. Coordinate the `pyproject.toml` edit with Benjamin; `uv add` in one commit.
- [x] `backend/app/agents/`: build the Deep Agent on Claude Haiku 5.5 (Anthropic API, `AGENT_MODEL` configurable) with a system prompt that encodes the product rules (no clinical decisions, no invented data, IDs only).
- [x] `backend/app/tools/`: thin tools over the service functions above. Stub the services that don't exist yet.
- [x] HITL: `interrupt_on` for `apply_plan`. Resume with approve/reject (no `edit` decision this stage).
- [x] `backend/app/api/agent.py`: SSE endpoints `POST /agent/threads`, `/threads/{id}/messages`, `/events`, `/approvals/{approval_id}` and `GET /threads/{id}/state`, with thread handling via a checkpointer. See `backend/app/agents/README.md`.
- [x] Model failure path (no key -> `error(model_unavailable)`): the app keeps working without the agent (AGENTS.md §7).
- [x] Tests: tools call services with the right args; a reject never calls `apply_plan`.

## Benjamin: optimizer, main backend, frontend

Read `docs/handoff-2026-11-15.md` first. It covers the nav graph, the exporter, and the data caveats.

- [x] Take over `backend/app/spatial/` (nav graph v1 is done, with 19 tests). Spot-check the 15 out-of-room place snaps (checked numerically, see the handoff caveats).
- [x] Generate synthetic staff and jobs on Airedale places, deterministic from a seed and clearly labeled synthetic.
- [x] `backend/app/optimization/`: OR-Tools on `NavGraph.distance_matrix`, with pickup before dropoff, time windows and priorities. Infeasible jobs are flagged, never dropped. Use small deterministic fixtures.
- [x] Baseline vs optimized metrics on the same graph, start and job set (no hardcoded improvements).
- [x] `backend/app/services/`: implement the contract above.
- [x] `backend/app/main.py` + `backend/app/api/`: app setup, CORS, endpoints for places/staff/jobs/plans/routes, and loading the nav graph at startup.
- [x] Frontend: pick the framework (it's still TBD in AGENTS.md §4; update it there). Then build the 2D floor plan with routes, the Matterport Showcase view (localhost only), the plan view, the chat panel, and the approval card.
- [x] Full demo rehearsal with a real key, in a browser: see `docs/demo-runbook.md`.

## Both: decide later

- [ ] Airedale usage rights. Decide together whether to ask the CoStar/Matterport sponsor team if exporting the layout of the public Airedale tour (`6Ee2LwLfx58`) is OK for the demo. Either way: keep the export out of git, and credit the source in the UI ("Airedale Hospital AAU, public Matterport tour by apollo3d"). If the answer is no, switch to a CoStar medical office building (e.g. `7uM5JKssTED`) and call it a clinic, not a hospital. See `docs/handoff-2026-11-15.md`, "Open questions".
