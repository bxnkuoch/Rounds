"""RoundsServices: the real implementation of the Services contract
(app/services/contract.py), in memory.

State: the building graph, synthetic staff and jobs, stored proposals, the
current (applied) plan and a simulated clock. Proposing never changes the
schedule; only apply_plan does, and the agent calls it only after a human
approves (interrupt_on). A proposal made against an older plan is stale and
can't be applied.
"""

from __future__ import annotations

import threading
from datetime import datetime

from app.models.domain import (
    Job, JobAdded, Place, Plan, Proposal, ReplanEvent, Route, StaffMember, StaffUnavailable, SwapComparison,
)
from app.optimization import DEFAULT_WALKING_SPEED_MPS
from app.services.planning import make_diff, replay_order, solve_plan
from app.spatial.nav_graph import NavGraph
from app.synthetic import ROLE_FOR_KIND, SERVICE_MINUTES, Scenario

_ACTIVE = ("new", "planned")
_STATUSES = ("new", "planned", "done", "cancelled")


class RoundsServices:
    def __init__(self, graph: NavGraph, scenario: Scenario, now: datetime | None = None,
                 walking_speed_mps: float = DEFAULT_WALKING_SPEED_MPS):
        self.graph = graph
        self.scenario_label = scenario.label
        self.walking_speed_mps = walking_speed_mps
        self._now = now or scenario.shift_start
        self._lock = threading.RLock()
        self._places = {p.id: Place(id=p.id, name=p.name, kind=p.kind, node_id=p.node_id, room_id=p.room_id,
                                    is_synthetic=False) for p in sorted(graph.places.values(), key=lambda p: p.id)}
        self._staff = {s.id: StaffMember(id=s.id, role=s.role, start_place_id=s.start_place_id,
                                         shift_start=s.shift_start, shift_end=s.shift_end) for s in scenario.staff}
        self._jobs = {j.id: Job(**j.__dict__) for j in scenario.jobs}
        self._unavailable: set[str] = set()
        self._proposals: dict[str, Proposal] = {}
        self._pending_unavailable: dict[str, set[str]] = {}
        self._applied: set[str] = set()
        self._current: str | None = None
        self._plan_seq = 0

    # ---- clock (simulated, for the demo) ------------------------------------

    @property
    def now(self) -> datetime:
        return self._now

    def set_now(self, t: datetime) -> None:
        with self._lock:
            self._now = t

    # ---- reads --------------------------------------------------------------

    def list_places(self) -> list[Place]:
        return list(self._places.values())

    def list_staff(self) -> list[StaffMember]:
        return list(self._staff.values())

    def unavailable_staff_ids(self) -> list[str]:
        return sorted(self._unavailable)

    def list_jobs(self, status: str | None = None) -> list[Job]:
        if status is not None and status not in _STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {list(_STATUSES)} or none for all")
        with self._lock:
            return [j for j in self._jobs.values() if status is None or j.status == status]

    def get_current_plan(self) -> Plan | None:
        with self._lock:
            return self._proposals[self._current].plan if self._current else None

    def get_proposal(self, plan_id: str) -> Proposal:
        with self._lock:
            if plan_id not in self._proposals:
                raise KeyError(f"unknown plan_id {plan_id!r}")
            return self._proposals[plan_id]

    def route_between(self, a_place_id: str, b_place_id: str) -> Route:
        for pid in (a_place_id, b_place_id):
            if pid not in self._places:
                raise KeyError(f"unknown place_id {pid!r}")
        meters, nodes = self.graph.shortest_path(self._places[a_place_id].node_id, self._places[b_place_id].node_id)
        return Route(from_place_id=a_place_id, to_place_id=b_place_id, meters=round(meters, 2), node_ids=nodes)

    def compare_swap(self, staff_id: str, job_a: str, job_b: str) -> SwapComparison:
        """Read-only "what if": replay `staff_id`'s jobs in the current plan's order, and again with `job_a`
        and `job_b` swapped, from the plan's start time. Nothing is proposed or applied."""
        with self._lock:
            plan = self.get_current_plan()
            if plan is None:
                raise ValueError("there is no current plan; propose and apply one first")
            if staff_id not in self._staff:
                raise KeyError(f"unknown staff_id {staff_id!r}")
            stops = next((a.stops for a in plan.assignments if a.staff_id == staff_id), [])
            order = list(dict.fromkeys(s.job_id for s in stops))
            for j in (job_a, job_b):
                if j not in order:
                    raise ValueError(f"{j} is not on {staff_id}'s route in plan {plan.id}; its jobs are {order}")
            if job_a == job_b:
                raise ValueError("job_a and job_b must be different jobs")
            swapped = list(order)
            i, k = order.index(job_a), order.index(job_b)
            swapped[i], swapped[k] = swapped[k], swapped[i]
            staff = self._staff[staff_id]
            current, other = (replay_order(self.graph, staff, [self._jobs[j] for j in o], plan.created_at,
                                           self.walking_speed_mps) for o in (order, swapped))
            return SwapComparison(plan_id=plan.id, staff_id=staff_id, swapped_job_ids=[job_a, job_b],
                                  current_order=current, swapped_order=other,
                                  meters_delta=round(other.total_meters - current.total_meters, 2),
                                  late_jobs_delta=len(other.late) - len(current.late))

    # ---- proposals (no side effects on the schedule) -------------------------

    def propose_plan(self, job_ids: list[str] | None = None) -> Proposal:
        with self._lock:
            return self._propose(job_ids, self._unavailable)

    def propose_replan(self, event: ReplanEvent) -> Proposal:
        with self._lock:
            if isinstance(event, JobAdded):
                if event.job_id not in self._jobs:
                    raise KeyError(f"unknown job_id {event.job_id!r}")
                return self._propose(None, self._unavailable)
            if isinstance(event, StaffUnavailable):
                if event.staff_id not in self._staff:
                    raise KeyError(f"unknown staff_id {event.staff_id!r}")
                unavailable = self._unavailable | {event.staff_id}
                proposal = self._propose(None, unavailable)
                self._pending_unavailable[proposal.plan.id] = unavailable
                return proposal
            raise ValueError(f"unsupported replan event {event!r}")

    def _propose(self, job_ids: list[str] | None, unavailable: set[str]) -> Proposal:
        if job_ids is not None:
            unknown = [j for j in job_ids if j not in self._jobs]
            if unknown:
                raise KeyError(f"unknown job_ids {unknown}")
        jobs = [j for j in self._jobs.values()
                if j.status in _ACTIVE and (job_ids is None or j.id in job_ids)]
        staff = [s for s in self._staff.values() if s.id not in unavailable]
        self._plan_seq += 1
        plan = solve_plan(self.graph, staff, jobs, self._now, f"P-{self._plan_seq}", self.walking_speed_mps)
        proposal = Proposal(plan=plan, diff=make_diff(self.get_current_plan(), plan))
        self._proposals[plan.id] = proposal
        return proposal

    # ---- the only schedule-changing call (after human approval) ------------

    def apply_plan(self, plan_id: str) -> Plan:
        with self._lock:
            proposal = self.get_proposal(plan_id)
            if plan_id in self._applied:
                raise ValueError(f"plan {plan_id} was already applied")
            if proposal.diff.from_plan_id != self._current:
                raise ValueError(f"plan {plan_id} is stale: it was proposed against {proposal.diff.from_plan_id}, "
                                 f"but the current plan is {self._current}. Propose again.")
            self._applied.add(plan_id)
            self._current = plan_id
            self._unavailable = self._pending_unavailable.pop(plan_id, self._unavailable)
            scheduled = {s.job_id for a in proposal.plan.assignments for s in a.stops}
            for j in self._jobs.values():
                if j.status in _ACTIVE:
                    j.status = "planned" if j.id in scheduled else "new"
            return proposal.plan

    # ---- dispatch inbox: structured new jobs (never created by the LLM) ----

    def create_job(self, kind: str, pickup_place_id: str, dropoff_place_id: str | None = None,
                   earliest: datetime | None = None, latest: datetime | None = None, priority: int = 3,
                   service_minutes: int | None = None) -> Job:
        if kind not in ROLE_FOR_KIND:
            raise ValueError(f"unknown job kind {kind!r}; expected one of {sorted(ROLE_FOR_KIND)}")
        if (kind == "transport") != (dropoff_place_id is not None):
            raise ValueError("transport jobs need a dropoff place; other kinds must not have one")
        for pid in filter(None, (pickup_place_id, dropoff_place_id)):
            if pid not in self._places:
                raise KeyError(f"unknown place_id {pid!r}")
        if not 1 <= priority <= 5:
            raise ValueError("priority must be 1 (most urgent) to 5")
        if earliest and latest and earliest >= latest:
            raise ValueError("earliest must be before latest")
        with self._lock:
            job = Job(id=f"SYN-J-{len(self._jobs) + 1:03d}", kind=kind, pickup_place_id=pickup_place_id,
                      dropoff_place_id=dropoff_place_id, earliest=earliest, latest=latest,
                      service_minutes=service_minutes or SERVICE_MINUTES[kind], priority=priority, status="new")
            self._jobs[job.id] = job
            return job
