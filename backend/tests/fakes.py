"""In-memory Services for tests. All data is SYNTHETIC test fixtures (IDs only)."""
from datetime import datetime

from app.models.domain import (
    Assignment, Baseline, Job, Place, Plan, PlanDiff, Proposal, ReplanEvent, Route, StaffMember, Stop,
)

T0 = datetime(2026, 1, 1, 8, 0)
T1 = datetime(2026, 1, 1, 16, 0)


def _plan(plan_id: str, job_ids: list[str]) -> Plan:
    stops = [
        Stop(job_id=j, place_id="PL-1", action="service", eta=T0, meters_from_prev=10.0) for j in job_ids
    ]
    return Plan(
        id=plan_id, created_at=T0, assignments=[Assignment(staff_id="S-1", stops=stops)],
        infeasible=[], total_meters=10.0 * len(stops), baseline=Baseline(total_meters=40.0, late_jobs=0),
    )


class FakeServices:
    def __init__(self):
        self.places = [
            Place(id="PL-1", name="Synthetic A", kind="synthetic", node_id="N1", room_id=None, is_synthetic=True),
            Place(id="PL-2", name="Synthetic B", kind="synthetic", node_id="N2", room_id=None, is_synthetic=True),
        ]
        self.staff = [StaffMember(id="S-1", role="transporter", start_place_id="PL-1", shift_start=T0, shift_end=T1)]
        self.jobs = [
            Job(id=f"J-{i}", kind="transport", pickup_place_id="PL-1", dropoff_place_id="PL-2", earliest=None,
                latest=None, service_minutes=5, priority=1, status="planned")
            for i in (1, 2, 3)
        ]
        self.current_plan: Plan | None = _plan("P-0", ["J-1", "J-2"])
        self.proposals: dict[str, Proposal] = {}
        self.applied: set[str] = set()
        self.apply_calls: list[str] = []
        self.received_events: list[ReplanEvent] = []
        self._n = 0

    def list_places(self) -> list[Place]:
        return list(self.places)

    def list_staff(self) -> list[StaffMember]:
        return list(self.staff)

    def list_jobs(self, status: str | None = None) -> list[Job]:
        return [j for j in self.jobs if status is None or j.status == status]

    def get_current_plan(self) -> Plan | None:
        return self.current_plan

    def _propose(self, job_ids: list[str]) -> Proposal:
        self._n += 1
        plan = _plan(f"P-{self._n}", job_ids)
        old = {s.job_id for a in self.current_plan.assignments for s in a.stops} if self.current_plan else set()
        new = set(job_ids)
        diff = PlanDiff(
            from_plan_id=self.current_plan.id if self.current_plan else None, to_plan_id=plan.id,
            added_job_ids=sorted(new - old), removed_job_ids=sorted(old - new), reordered_staff_ids=[],
            newly_infeasible=[],
            meters_delta=plan.total_meters - (self.current_plan.total_meters if self.current_plan else 0.0),
            late_jobs_delta=0,
        )
        self.proposals[plan.id] = Proposal(plan=plan, diff=diff)
        return self.proposals[plan.id]

    def propose_plan(self, job_ids: list[str] | None = None) -> Proposal:
        return self._propose(job_ids if job_ids is not None else [j.id for j in self.jobs])

    def propose_replan(self, event: ReplanEvent) -> Proposal:
        self.received_events.append(event)
        return self._propose([j.id for j in self.jobs])

    def get_proposal(self, plan_id: str) -> Proposal:
        return self.proposals[plan_id]

    def apply_plan(self, plan_id: str) -> Plan:
        proposal = self.proposals[plan_id]
        if plan_id in self.applied:
            raise ValueError(f"plan {plan_id} already applied")
        current_id = self.current_plan.id if self.current_plan else None
        if proposal.diff.from_plan_id != current_id:
            raise ValueError(f"plan {plan_id} is stale (based on {proposal.diff.from_plan_id}, current is {current_id})")
        self.applied.add(plan_id)
        self.apply_calls.append(plan_id)
        self.current_plan = proposal.plan
        return proposal.plan

    def route_between(self, a_place_id: str, b_place_id: str) -> Route:
        return Route(from_place_id=a_place_id, to_place_id=b_place_id, meters=10.0, node_ids=["N1", "N2"])
