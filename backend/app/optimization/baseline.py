"""Naive baseline: what a dispatcher does without an optimizer.

Jobs are taken in due-time order (deadline, then earliest start, then id) and
each goes to the staff member who is free soonest and can still finish it in
their shift. Same graph, travel model and job set as the optimizer, so the
comparison is computed, never hardcoded.
"""

from __future__ import annotations

from app.optimization.types import (
    DEFAULT_WALKING_SPEED_MPS, DistanceMatrixFn, Distances, LateJob, OptJob, OptStaff, Solution, StaffRoute,
    Stop, Unassigned, deadline_late, precheck, solo_finish,
)


def baseline(staff: list[OptStaff], jobs: list[OptJob], distance_matrix: DistanceMatrixFn,
             walking_speed_mps: float = DEFAULT_WALKING_SPEED_MPS) -> Solution:
    d = Distances(staff, jobs, distance_matrix, walking_speed_mps)
    plannable, unassigned = precheck(staff, jobs, d)
    unassigned = list(unassigned)

    pos = [s.start_node for s in staff]
    now = [s.shift_start for s in staff]
    stops: list[list[Stop]] = [[] for _ in staff]
    late: list[LateJob] = []

    due_order = sorted(plannable, key=lambda p: (p[0].latest is None, p[0].latest or 0,
                                                 p[0].earliest or 0, p[0].id))
    for job, allowed in due_order:
        chosen = next((i for i in sorted(allowed, key=lambda i: (now[i], staff[i].id))
                       if solo_finish(job, staff[i], d, pos[i], now[i]) <= staff[i].shift_end), None)
        if chosen is None:
            unassigned.append(Unassigned(job.id, "did not fit in any staff member's remaining shift"))
            continue
        i = chosen
        arrival = now[i] + d.seconds(pos[i], job.pickup_node)
        start = max(arrival, job.earliest) if job.earliest is not None else arrival
        first = Stop(job.id, job.pickup_node, "service" if job.dropoff_node is None else "pickup",
                     arrival, start, start + job.service_s, d.meters(pos[i], job.pickup_node))
        stops[i].append(first)
        deadline_stop = first
        pos[i], now[i] = job.pickup_node, first.depart
        if job.dropoff_node is not None:
            arrival = now[i] + d.seconds(pos[i], job.dropoff_node)
            deadline_stop = Stop(job.id, job.dropoff_node, "dropoff", arrival, arrival, arrival,
                                 d.meters(pos[i], job.dropoff_node))
            stops[i].append(deadline_stop)
            pos[i], now[i] = job.dropoff_node, arrival
        if (s := deadline_late(job, deadline_stop)) > 0:
            late.append(LateJob(job.id, s))

    routes = tuple(StaffRoute(s.id, tuple(st), sum(x.meters_from_prev for x in st)) for s, st in zip(staff, stops))
    return Solution(routes, tuple(sorted(late, key=lambda x: x.job_id)),
                    tuple(sorted(unassigned, key=lambda x: x.job_id)), sum(r.meters for r in routes))
