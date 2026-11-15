"""Turn shared-contract staff/jobs into optimizer inputs, run the optimizer and
the baseline per role, and build Plan / PlanDiff models from the results.

Time zero for the optimizer is `now`: nobody can start work before it.
Lateness is computed here from real datetimes, so deadlines already in the
past are reported correctly.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.models.domain import (
    Assignment, Baseline, Infeasible, Job, LateJob, Plan, PlanDiff, StaffMember, Stop,
)
from app.optimization import OptJob, OptStaff, Solution, baseline, optimize
from app.optimization import Stop as OptStop
from app.spatial.nav_graph import NavGraph
from app.synthetic import ROLE_FOR_KIND


def _late_minutes(job: Job, stop: OptStop, ref: datetime) -> int:
    if job.latest is None or stop.action == "pickup":
        return 0
    t = stop.arrival if stop.action == "dropoff" else stop.start
    over = (ref + timedelta(seconds=t) - job.latest).total_seconds()
    return math.ceil(over / 60) if over > 0 else 0


def _late(sol: Solution, jobs: dict[str, Job], ref: datetime) -> list[LateJob]:
    out = []
    for r in sol.routes:
        for s in r.stops:
            if (m := _late_minutes(jobs[s.job_id], s, ref)) > 0:
                out.append(LateJob(job_id=s.job_id, minutes_late=m))
    return out


def solve_plan(graph: NavGraph, staff: list[StaffMember], jobs: list[Job], now: datetime, plan_id: str,
               walking_speed_mps: float) -> Plan:
    def secs(t: datetime) -> int:
        return int((t - now).total_seconds())

    node_of = {pid: p.node_id for pid, p in graph.places.items()}
    node_to_place: dict[str, str] = {}
    by_id = {j.id: j for j in jobs}
    infeasible: list[Infeasible] = []
    routes: dict[str, list[OptStop]] = {s.id: [] for s in staff}
    late: list[LateJob] = []
    meters = base_meters = 0.0
    base_late = 0

    for role in ("respiratory_therapist", "iv_nurse", "transporter"):
        role_staff = [s for s in staff if s.role == role and secs(s.shift_end) > max(0, secs(s.shift_start))]
        opt_staff = [OptStaff(s.id, node_of[s.start_place_id], max(0, secs(s.shift_start)), secs(s.shift_end))
                     for s in role_staff]
        role_jobs = [j for j in jobs if ROLE_FOR_KIND.get(j.kind) == role]
        if role_jobs and not opt_staff:
            infeasible += [Infeasible(job_id=j.id, reason=f"no available {role.replace('_', ' ')} on shift")
                           for j in role_jobs]
            continue
        opt_jobs = []
        for j in role_jobs:
            pickup, drop = node_of[j.pickup_place_id], node_of[j.dropoff_place_id] if j.dropoff_place_id else None
            node_to_place.setdefault(pickup, j.pickup_place_id)
            if drop:
                node_to_place.setdefault(drop, j.dropoff_place_id)
            opt_jobs.append(OptJob(
                j.id, pickup, drop,
                earliest=None if j.earliest is None else max(0, secs(j.earliest)),
                latest=None if j.latest is None else max(0, secs(j.latest)),
                service_s=j.service_minutes * 60, priority=j.priority))
        if not opt_jobs:
            continue
        opt = optimize(opt_staff, opt_jobs, graph.distance_matrix, walking_speed_mps)
        base = baseline(opt_staff, opt_jobs, graph.distance_matrix, walking_speed_mps)
        for r in opt.routes:
            routes[r.staff_id] = list(r.stops)
        infeasible += [Infeasible(job_id=u.job_id, reason=u.reason) for u in opt.unassigned]
        late += _late(opt, by_id, now)
        meters += opt.total_meters
        base_meters += base.total_meters
        base_late += len(_late(base, by_id, now))

    infeasible += [Infeasible(job_id=j.id, reason=f"no staff role handles job kind {j.kind!r}")
                   for j in jobs if j.kind not in ROLE_FOR_KIND]

    def place_for(job: Job, s: OptStop) -> str:
        return job.dropoff_place_id if s.action == "dropoff" else job.pickup_place_id

    assignments = [
        Assignment(staff_id=s.id, stops=[
            Stop(job_id=x.job_id, place_id=place_for(by_id[x.job_id], x), action=x.action,
                 eta=now + timedelta(seconds=x.arrival), meters_from_prev=round(x.meters_from_prev, 2))
            for x in routes[s.id]])
        for s in staff
    ]
    return Plan(id=plan_id, created_at=now, assignments=assignments,
                infeasible=sorted(infeasible, key=lambda i: i.job_id), total_meters=round(meters, 2),
                baseline=Baseline(total_meters=round(base_meters, 2), late_jobs=base_late),
                late=sorted(late, key=lambda l: l.job_id))


def _scheduled(plan: Plan) -> set[str]:
    return {s.job_id for a in plan.assignments for s in a.stops}


def make_diff(old: Plan | None, new: Plan) -> PlanDiff:
    old_jobs = _scheduled(old) if old else set()
    new_jobs = _scheduled(new)
    old_seq = {a.staff_id: [(s.job_id, s.action) for s in a.stops] for a in old.assignments} if old else {}
    reordered = [a.staff_id for a in new.assignments
                 if [(s.job_id, s.action) for s in a.stops] != old_seq.get(a.staff_id, [])]
    old_bad = {i.job_id for i in old.infeasible} if old else set()
    return PlanDiff(
        from_plan_id=old.id if old else None,
        to_plan_id=new.id,
        added_job_ids=sorted(new_jobs - old_jobs),
        removed_job_ids=sorted(old_jobs - new_jobs),
        reordered_staff_ids=reordered,
        newly_infeasible=[i for i in new.infeasible if i.job_id not in old_bad],
        meters_delta=round(new.total_meters - (old.total_meters if old else 0.0), 2),
        late_jobs_delta=len(new.late) - (len(old.late) if old else 0),
    )
