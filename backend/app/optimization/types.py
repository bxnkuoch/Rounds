"""Plain inputs/outputs for the optimizer, plus the travel model and the
checks both the optimizer and the baseline share.

Kept independent of the shared Pydantic models (backend/app/models/) on
purpose: services convert to/from these, so a contract change never touches
the solver. Times are integer seconds from any reference the caller picks
(e.g. seconds since shift start). Nodes are NavGraph node ids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

# Assumed average walking speed. A parameter, not measured data.
DEFAULT_WALKING_SPEED_MPS = 1.2

DistanceMatrixFn = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class OptStaff:
    id: str
    start_node: str
    shift_start: int
    shift_end: int


@dataclass(frozen=True)
class OptJob:
    """A single-stop job (dropoff_node is None) or a pickup -> dropoff job.

    earliest: the pickup/service can't start before this.
    latest:   deadline for starting service (single-stop) or for arriving at
              the dropoff (transport). Missing it makes the job late, not
              dropped.
    service_s: time spent at the pickup/service stop.
    priority: from the input data, 1 = most urgent ... 5 = least. Only weights
              lateness; the optimizer never decides it.
    """
    id: str
    pickup_node: str
    dropoff_node: str | None = None
    earliest: int | None = None
    latest: int | None = None
    service_s: int = 0
    priority: int = 3


@dataclass(frozen=True)
class Stop:
    job_id: str
    node_id: str
    action: str  # "service" | "pickup" | "dropoff"
    arrival: int
    start: int  # service start (after any wait for `earliest`)
    depart: int
    meters_from_prev: float


@dataclass(frozen=True)
class StaffRoute:
    staff_id: str
    stops: tuple[Stop, ...]
    meters: float


@dataclass(frozen=True)
class LateJob:
    job_id: str
    seconds_late: int


@dataclass(frozen=True)
class Unassigned:
    job_id: str
    reason: str


@dataclass(frozen=True)
class Solution:
    routes: tuple[StaffRoute, ...]
    late: tuple[LateJob, ...]
    unassigned: tuple[Unassigned, ...]
    total_meters: float


class Distances:
    """Shortest-path meters between every node the problem uses."""

    def __init__(self, staff: list[OptStaff], jobs: list[OptJob], distance_matrix: DistanceMatrixFn,
                 walking_speed_mps: float):
        nodes = {s.start_node for s in staff}
        for j in jobs:
            nodes.add(j.pickup_node)
            if j.dropoff_node is not None:
                nodes.add(j.dropoff_node)
        ordered = sorted(nodes)
        self._idx = {n: i for i, n in enumerate(ordered)}
        self._m = distance_matrix(ordered) if ordered else []
        self.speed = walking_speed_mps

    def meters(self, a: str, b: str) -> float:
        return self._m[self._idx[a]][self._idx[b]]

    def seconds(self, a: str, b: str) -> int:
        return math.ceil(self.meters(a, b) / self.speed)


def solo_finish(job: OptJob, s: OptStaff, d: Distances, at_node: str, at_time: int) -> int:
    """When `s`, standing at `at_node` at `at_time`, would finish `job` alone."""
    t = at_time + d.seconds(at_node, job.pickup_node)
    if job.earliest is not None:
        t = max(t, job.earliest)
    t += job.service_s
    if job.dropoff_node is not None:
        t += d.seconds(job.pickup_node, job.dropoff_node)
    return t


def precheck(staff: list[OptStaff], jobs: list[OptJob], d: Distances
             ) -> tuple[list[tuple[OptJob, list[int]]], list[Unassigned]]:
    """Split jobs into (job, indices of staff who could do it) and jobs no one
    can do, each with a reason. Never drops a job silently."""
    plannable: list[tuple[OptJob, list[int]]] = []
    unassigned: list[Unassigned] = []
    for job in sorted(jobs, key=lambda j: j.id):
        if job.dropoff_node is not None and math.isinf(d.meters(job.pickup_node, job.dropoff_node)):
            unassigned.append(Unassigned(job.id, "no walking path from pickup to dropoff"))
            continue
        reach = [i for i, s in enumerate(staff) if not math.isinf(d.meters(s.start_node, job.pickup_node))]
        if not reach:
            unassigned.append(Unassigned(job.id, "no staff member has a walking path to this job"))
            continue
        fits = [i for i in reach if solo_finish(job, staff[i], d, staff[i].start_node, staff[i].shift_start)
                <= staff[i].shift_end]
        if not fits:
            unassigned.append(Unassigned(job.id, "cannot be completed within any staff member's shift"))
            continue
        plannable.append((job, fits))
    return plannable, unassigned


def deadline_late(job: OptJob, stop: Stop) -> int:
    """Seconds late at the job's deadline stop (0 if on time or no deadline)."""
    if job.latest is None:
        return 0
    t = stop.arrival if stop.action == "dropoff" else stop.start
    return max(0, t - job.latest)
