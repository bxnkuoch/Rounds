# v0: provisional, Benjamin to confirm
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, StringConstraints

SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class Place(BaseModel):
    id: str
    name: str
    kind: Literal["label", "tag", "synthetic"]
    node_id: str
    room_id: str | None
    is_synthetic: bool


class StaffMember(BaseModel):
    id: str
    role: Literal["transporter", "respiratory_therapist", "iv_nurse"]
    start_place_id: str
    shift_start: datetime
    shift_end: datetime


class Job(BaseModel):
    id: str
    kind: str
    pickup_place_id: str
    dropoff_place_id: str | None
    earliest: datetime | None
    latest: datetime | None
    service_minutes: int
    priority: int
    status: Literal["new", "planned", "done", "cancelled"]


class Stop(BaseModel):
    job_id: str
    place_id: str
    action: Literal["pickup", "dropoff", "service"]
    eta: datetime
    meters_from_prev: float


class Assignment(BaseModel):
    staff_id: str
    stops: list[Stop]


class Infeasible(BaseModel):
    job_id: str
    reason: str


class LateJob(BaseModel):
    job_id: str
    minutes_late: int


class Baseline(BaseModel):
    total_meters: float
    late_jobs: int


class Plan(BaseModel):
    id: str
    created_at: datetime
    assignments: list[Assignment]
    infeasible: list[Infeasible]
    total_meters: float
    baseline: Baseline | None
    # Additive (Benjamin): scheduled jobs that miss their deadline. Unscheduled ones stay in `infeasible`.
    late: list[LateJob] = Field(default_factory=list)


class PlanDiff(BaseModel):
    from_plan_id: str | None
    to_plan_id: str
    added_job_ids: list[str]
    removed_job_ids: list[str]
    reordered_staff_ids: list[str]
    newly_infeasible: list[Infeasible]
    meters_delta: float
    late_jobs_delta: int


class Proposal(BaseModel):
    plan: Plan
    diff: PlanDiff


class JobAdded(BaseModel):
    kind: Literal["job_added"]
    job_id: SafeId


class StaffUnavailable(BaseModel):
    kind: Literal["staff_unavailable"]
    staff_id: SafeId


ReplanEvent = Annotated[Union[JobAdded, StaffUnavailable], Field(discriminator="kind")]


class OrderOutcome(BaseModel):
    job_ids: list[str]
    stops: list[Stop]
    total_meters: float
    late: list[LateJob]


class SwapComparison(BaseModel):
    """Additive (Benjamin): one staff member's current order vs the same jobs with two of them swapped,
    replayed with the optimizer's travel model. Deltas are swapped minus current."""
    plan_id: str
    staff_id: str
    swapped_job_ids: list[str]
    current_order: OrderOutcome
    swapped_order: OrderOutcome
    meters_delta: float
    late_jobs_delta: int


class StaffShiftSummary(BaseModel):
    staff_id: str
    role: str
    available: bool
    remaining_job_ids: list[str]  # jobs with a stop at or after `now`, in plan order
    next_stop: Stop | None
    next_place_name: str | None
    remaining_meters: float


class ShiftSummary(BaseModel):
    """Additive (Benjamin): deterministic facts for the shift handoff report, so the agent never counts."""
    scenario_label: str
    now: datetime
    plan_id: str | None
    staff: list[StaffShiftSummary]
    late: list[LateJob]
    infeasible: list[Infeasible]
    unscheduled_job_ids: list[str]  # active jobs that aren't in the current plan
    total_meters: float | None
    baseline_meters: float | None


class Route(BaseModel):
    from_place_id: str
    to_place_id: str
    meters: float
    node_ids: list[str]
