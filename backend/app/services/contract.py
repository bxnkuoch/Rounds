# v0: provisional, Benjamin to confirm
from typing import Protocol

from app.models.domain import (
    Job, Place, Plan, Proposal, ReplanEvent, Route, ShiftSummary, StaffMember, SwapComparison,
)


class Services(Protocol):
    """Domain service seam: the agent's tools and FastAPI both call this."""

    def list_places(self) -> list[Place]: ...

    def list_staff(self) -> list[StaffMember]: ...

    def list_jobs(self, status: str | None = None) -> list[Job]: ...

    def get_current_plan(self) -> Plan | None: ...

    def propose_plan(self, job_ids: list[str] | None = None) -> Proposal: ...

    def propose_replan(self, event: ReplanEvent) -> Proposal: ...

    def get_proposal(self, plan_id: str) -> Proposal:
        """Raises KeyError if the plan_id is unknown."""
        ...

    def apply_plan(self, plan_id: str) -> Plan:
        """Raises KeyError if unknown; ValueError if already applied or stale (the proposal's
        diff.from_plan_id is not the current plan)."""
        ...

    def route_between(self, a_place_id: str, b_place_id: str) -> Route: ...

    def compare_swap(self, staff_id: str, job_a: str, job_b: str) -> SwapComparison:
        """Read-only: the staff member's current order vs the same jobs with job_a and job_b swapped.
        Raises KeyError for an unknown staff id; ValueError if there's no current plan or a job isn't on
        that staff member's route."""
        ...

    def shift_summary(self) -> ShiftSummary:
        """Read-only facts for the shift handoff report (remaining work per staff, late, infeasible,
        unscheduled)."""
        ...
