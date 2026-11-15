"""Replay one staff member's jobs in a fixed order with the same travel model as
the optimizer and baseline. Used to answer "what if these two were swapped?"
with computed numbers instead of the model's guesses.
"""

from __future__ import annotations

from app.optimization.types import (
    DEFAULT_WALKING_SPEED_MPS,
    DistanceMatrixFn,
    Distances,
    LateJob,
    OptJob,
    OptStaff,
    StaffRoute,
    Stop,
    deadline_late,
    do_job,
)


def simulate_order(staff: OptStaff, jobs: list[OptJob], distance_matrix: DistanceMatrixFn,
                   walking_speed_mps: float = DEFAULT_WALKING_SPEED_MPS) -> tuple[StaffRoute, tuple[LateJob, ...]]:
    d = Distances([staff], jobs, distance_matrix, walking_speed_mps)
    pos, now = staff.start_node, staff.shift_start
    stops: list[Stop] = []
    late: list[LateJob] = []
    for job in jobs:
        done, deadline_stop, pos, now = do_job(job, d, pos, now)
        stops += done
        if (s := deadline_late(job, deadline_stop)) > 0:
            late.append(LateJob(job.id, s))
    return StaffRoute(staff.id, tuple(stops), sum(x.meters_from_prev for x in stops)), tuple(late)
