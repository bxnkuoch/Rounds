"""Shift optimizer: OR-Tools vehicle routing on NavGraph distances.

Each staff member is a vehicle that starts at their start node at shift start
and may end anywhere before shift end. Constraints:
- pickup before dropoff, same staff member (transport jobs)
- at most one patient/bed carried at a time (capacity 1)
- `earliest` is hard (staff wait); `latest` is soft: missing it costs a
  penalty weighted by the job's input priority, and the job is reported late
- shift end is hard; a job that doesn't fit is reported unassigned with a
  reason, never silently dropped

Objective: minimize meters walked + lateness penalty. Default search is
deterministic (no time-limited metaheuristic) so tests and demos repeat.
"""

from __future__ import annotations

import math

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimization.types import (
    DEFAULT_WALKING_SPEED_MPS, DistanceMatrixFn, Distances, LateJob, OptJob, OptStaff, Solution, StaffRoute,
    Stop, Unassigned, deadline_late, precheck,
)

_DROP_PENALTY = 10**9
_UNREACHABLE_COST = 10**8
_LATE_COST_PER_S = 10  # per second late, times priority weight (cost unit: 0.1 m walked)


def _priority_weight(priority: int) -> int:
    return max(1, 6 - priority)


def optimize(staff: list[OptStaff], jobs: list[OptJob], distance_matrix: DistanceMatrixFn,
             walking_speed_mps: float = DEFAULT_WALKING_SPEED_MPS,
             time_limit_s: int | None = None) -> Solution:
    """Plan all jobs across staff. With `time_limit_s`, also runs guided local
    search for that long (better plans, but timing-dependent)."""
    d = Distances(staff, jobs, distance_matrix, walking_speed_mps)
    plannable, unassigned = precheck(staff, jobs, d)
    unassigned = list(unassigned)
    if not staff or not plannable:
        return Solution(tuple(StaffRoute(s.id, (), 0.0) for s in staff), (),
                        tuple(sorted(unassigned, key=lambda u: u.job_id)), 0.0)

    # Index layout: one start per staff, one shared "end anywhere" node, then stops.
    n_staff = len(staff)
    end = n_staff
    loc: list[str | None] = [s.start_node for s in staff] + [None]
    service = [0] * (n_staff + 1)
    demand = [0] * (n_staff + 1)
    stop_meta: dict[int, tuple[OptJob, str]] = {}
    job_stops: list[tuple[OptJob, list[int], int, int | None]] = []
    for job, allowed in plannable:
        first = len(loc)
        loc.append(job.pickup_node)
        service.append(job.service_s)
        is_transport = job.dropoff_node is not None
        demand.append(1 if is_transport else 0)
        stop_meta[first] = (job, "pickup" if is_transport else "service")
        drop = None
        if is_transport:
            drop = len(loc)
            loc.append(job.dropoff_node)
            service.append(0)
            demand.append(-1)
            stop_meta[drop] = (job, "dropoff")
        job_stops.append((job, allowed, first, drop))

    manager = pywrapcp.RoutingIndexManager(len(loc), n_staff, list(range(n_staff)), [end] * n_staff)
    routing = pywrapcp.RoutingModel(manager)

    def meters(i: int, k: int) -> float:
        return 0.0 if loc[i] is None or loc[k] is None else d.meters(loc[i], loc[k])

    def dist_cb(fi: int, ti: int) -> int:
        m = meters(manager.IndexToNode(fi), manager.IndexToNode(ti))
        return _UNREACHABLE_COST if math.isinf(m) else round(m * 10)

    def time_cb(fi: int, ti: int) -> int:
        i, k = manager.IndexToNode(fi), manager.IndexToNode(ti)
        m = meters(i, k)
        travel = _UNREACHABLE_COST if math.isinf(m) else math.ceil(m / walking_speed_mps)
        return travel + service[i]

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(dist_cb))
    horizon = max(s.shift_end for s in staff)
    routing.AddDimension(routing.RegisterTransitCallback(time_cb), horizon, horizon, False, "Time")
    time = routing.GetDimensionOrDie("Time")
    load_cb = routing.RegisterUnaryTransitCallback(lambda fi: demand[manager.IndexToNode(fi)])
    routing.AddDimensionWithVehicleCapacity(load_cb, 0, [1] * n_staff, True, "Load")

    for v, s in enumerate(staff):
        time.CumulVar(routing.Start(v)).SetRange(s.shift_start, s.shift_end)
        time.CumulVar(routing.End(v)).SetMax(s.shift_end)

    solver = routing.solver()

    def restrict(idx: int, allowed: list[int]) -> None:
        # Same effect as SetAllowedVehiclesForIndex (whose Python binding rejects lists in this build).
        banned = [v for v in range(n_staff) if v not in allowed]
        if banned:
            routing.VehicleVar(idx).RemoveValues(banned)

    for job, allowed, first, drop in job_stops:
        fi = manager.NodeToIndex(first)
        if job.earliest is not None:
            time.CumulVar(fi).SetMin(job.earliest)
        restrict(fi, allowed)
        routing.AddDisjunction([fi], _DROP_PENALTY)
        deadline_idx = fi
        if drop is not None:
            di = manager.NodeToIndex(drop)
            restrict(di, allowed)
            routing.AddDisjunction([di], _DROP_PENALTY)
            routing.AddPickupAndDelivery(fi, di)
            solver.Add(routing.VehicleVar(fi) == routing.VehicleVar(di))
            solver.Add(time.CumulVar(fi) <= time.CumulVar(di))
            deadline_idx = di
        if job.latest is not None:
            time.SetCumulVarSoftUpperBound(deadline_idx, job.latest,
                                           _LATE_COST_PER_S * _priority_weight(job.priority))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    if time_limit_s:
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = time_limit_s
    sol = routing.SolveWithParameters(params)

    if sol is None:
        unassigned += [Unassigned(j.id, "optimizer found no feasible plan") for j, *_ in job_stops]
        return Solution(tuple(StaffRoute(s.id, (), 0.0) for s in staff), (),
                        tuple(sorted(unassigned, key=lambda u: u.job_id)), 0.0)

    routes: list[StaffRoute] = []
    late: list[LateJob] = []
    for v, s in enumerate(staff):
        stops: list[Stop] = []
        prev_node, prev_depart = s.start_node, sol.Min(time.CumulVar(routing.Start(v)))
        idx = sol.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            job, action = stop_meta[node]
            arrival = prev_depart + d.seconds(prev_node, loc[node])
            start = max(arrival, sol.Min(time.CumulVar(idx)))
            stop = Stop(job.id, loc[node], action, arrival, start, start + service[node],
                        d.meters(prev_node, loc[node]))
            stops.append(stop)
            if action != "pickup" and (sec := deadline_late(job, stop)) > 0:
                late.append(LateJob(job.id, sec))
            prev_node, prev_depart = loc[node], stop.depart
            idx = sol.Value(routing.NextVar(idx))
        routes.append(StaffRoute(s.id, tuple(stops), sum(x.meters_from_prev for x in stops)))

    for job, _, first, _ in job_stops:
        fi = manager.NodeToIndex(first)
        if sol.Value(routing.NextVar(fi)) == fi:
            unassigned.append(Unassigned(job.id, "did not fit in staff shifts alongside the other jobs"))

    return Solution(tuple(routes), tuple(sorted(late, key=lambda x: x.job_id)),
                    tuple(sorted(unassigned, key=lambda u: u.job_id)), sum(r.meters for r in routes))
