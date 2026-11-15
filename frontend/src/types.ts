// Shared contract: mirrors backend/app/models/domain.py and agent_events.py (v0).
// AGENTS.md §3: change these together with the Pydantic models, in the same commit.
// Datetimes are naive ISO strings ("2026-11-15T07:20:00"), simulated shift time.

export type Place = {
  id: string
  name: string
  kind: 'label' | 'tag' | 'synthetic'
  node_id: string
  room_id: string | null
  is_synthetic: boolean
}

export type Role = 'transporter' | 'respiratory_therapist' | 'iv_nurse'

export type StaffMember = {
  id: string
  role: Role
  start_place_id: string
  shift_start: string
  shift_end: string
}

export type Job = {
  id: string
  kind: string
  pickup_place_id: string
  dropoff_place_id: string | null
  earliest: string | null
  latest: string | null
  service_minutes: number
  priority: number
  status: 'new' | 'planned' | 'done' | 'cancelled'
}

export type Stop = {
  job_id: string
  place_id: string
  action: 'pickup' | 'dropoff' | 'service'
  eta: string
  meters_from_prev: number
}

export type Assignment = { staff_id: string; stops: Stop[] }
export type Infeasible = { job_id: string; reason: string }
export type LateJob = { job_id: string; minutes_late: number }
export type Baseline = { total_meters: number; late_jobs: number }

export type StaffShiftSummary = {
  staff_id: string
  role: string
  available: boolean
  remaining_job_ids: string[]
  next_stop: Stop | null
  next_place_name: string | null
  remaining_meters: number
}
export type ShiftSummary = {
  scenario_label: string
  now: string
  plan_id: string | null
  staff: StaffShiftSummary[]
  late: LateJob[]
  infeasible: Infeasible[]
  unscheduled_job_ids: string[]
  total_meters: number | null
  baseline_meters: number | null
}

export type OrderOutcome = { job_ids: string[]; stops: Stop[]; total_meters: number; late: LateJob[] }
export type SwapComparison = {
  plan_id: string
  staff_id: string
  swapped_job_ids: string[]
  current_order: OrderOutcome
  swapped_order: OrderOutcome
  meters_delta: number
  late_jobs_delta: number
}

export type Plan = {
  id: string
  created_at: string
  assignments: Assignment[]
  infeasible: Infeasible[]
  total_meters: number
  baseline: Baseline | null
  late: LateJob[]
}

export type PlanDiff = {
  from_plan_id: string | null
  to_plan_id: string
  added_job_ids: string[]
  removed_job_ids: string[]
  reordered_staff_ids: string[]
  newly_infeasible: Infeasible[]
  meters_delta: number
  late_jobs_delta: number
}

export type Proposal = { plan: Plan; diff: PlanDiff }

export type Route = { from_place_id: string; to_place_id: string; meters: number; node_ids: string[] }

export type ReplanEvent =
  | { kind: 'job_added'; job_id: string }
  | { kind: 'staff_unavailable'; staff_id: string }

// ---- /api extras (backend/app/api/rounds.py) ----

export type Meta = {
  scenario_label: string
  now: string
  shift_start: string
  shift_end: string
  unavailable_staff_ids: string[]
  job_kinds: Record<string, Role>
}

export type BuildingMap = {
  model_id: string | null
  attribution: Record<string, string>
  nodes: { id: string; x: number; y: number; floor_id: string | null; room_id: string | null }[]
  edges: [string, string][]
  rooms: { id: string; label: string | null; floor_id: string | null; min_x: number; min_y: number; max_x: number; max_y: number }[]
  places: { id: string; name: string; x: number; y: number; node_id: string }[]
}

// ---- agent events (backend/app/models/agent_events.py) ----

type Base = { thread_id: string; seq: number; source: string }
export type TodoItem = { content: string; status: 'pending' | 'in_progress' | 'completed' }

export type ApprovalRequired = Base & {
  type: 'approval_required'
  approval_id: string
  plan_id: string
  plan_diff: PlanDiff
  rationale: string
  allowed: ('approve' | 'reject')[]
}

export type AgentEvent =
  | (Base & { type: 'run_started'; run_id: string })
  | (Base & { type: 'token'; text: string })
  | (Base & { type: 'todos'; items: TodoItem[] })
  | (Base & { type: 'tool_call'; tool_call_id: string; name: string; args: Record<string, unknown> })
  | (Base & { type: 'tool_result'; tool_call_id: string; name: string; ok: boolean; summary: string })
  | (Base & { type: 'subagent_started' | 'subagent_finished'; subagent: string; task_id: string })
  | ApprovalRequired
  | (Base & { type: 'message'; text: string })
  | (Base & { type: 'done'; status: 'completed' | 'awaiting_approval' })
  | (Base & { type: 'error'; code: string; message: string; retryable: boolean })

export type ThreadState = {
  todos: TodoItem[]
  pending_approval: ApprovalRequired | null
  messages: { role: 'user' | 'assistant'; text: string }[]
}
