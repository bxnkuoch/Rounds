# v0: provisional, Benjamin to confirm
from typing import Protocol

from app.models.domain import Job, Place, Plan, Proposal, ReplanEvent, Route, StaffMember


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
        """Raises KeyError if unknown, ValueError if already applied."""
        ...

    def route_between(self, a_place_id: str, b_place_id: str) -> Route: ...
