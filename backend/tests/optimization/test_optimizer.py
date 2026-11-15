"""Optimizer tests on small hand-built fixtures with known answers.

Fixture: a 1-D corridor. Node "xN" sits at N meters; distance = |a - b|.
Node "island" is unreachable from everything. Walking speed 1 m/s, so
seconds == meters.
"""

import math
from pathlib import Path

import pytest

from app.optimization import OptJob, OptStaff, baseline, optimize


def corridor(ids: list[str]) -> list[list[float]]:
    def x(n):
        return None if n == "island" else float(n[1:])
    return [[0.0 if a == b else math.inf if x(a) is None or x(b) is None else abs(x(a) - x(b))
             for b in ids] for a in ids]


def run(staff, jobs, fn=optimize):
    return fn(staff, jobs, corridor, walking_speed_mps=1.0)


def order(sol, staff_id):
    route = next(r for r in sol.routes if r.staff_id == staff_id)
    return [(s.job_id, s.action) for s in route.stops]


ALICE = OptStaff("S1", "x0", 0, 10_000)


def test_single_stop_jobs_visited_in_walking_order():
    jobs = [OptJob("A", "x10"), OptJob("C", "x30"), OptJob("B", "x20")]
    sol = run([ALICE], jobs)
    assert [j for j, _ in order(sol, "S1")] == ["A", "B", "C"]
    assert sol.total_meters == 30
    assert not sol.unassigned and not sol.late


def test_pickup_before_dropoff_and_one_patient_at_a_time():
    # Carrying both at once would be shorter (0-10-20-30-40 = 40 m) but capacity is 1.
    jobs = [OptJob("A", "x10", "x40"), OptJob("B", "x20", "x30")]
    sol = run([ALICE], jobs)
    assert order(sol, "S1") == [("A", "pickup"), ("A", "dropoff"), ("B", "pickup"), ("B", "dropoff")]
    assert sol.total_meters == 70  # 10 + 30 + 20 + 10; B-first would be 80


def test_deadline_changes_order():
    # Near-first walks 100 m but reaches "far" at t=150, 50 s past its deadline.
    # Far-first walks 190 m and is on time, so the deadline wins.
    jobs = [OptJob("near", "x10", service_s=50), OptJob("far", "x100", latest=100)]
    sol = run([ALICE], jobs)
    assert [j for j, _ in order(sol, "S1")] == ["far", "near"]
    assert not sol.late


def test_earliest_makes_staff_wait():
    sol = run([ALICE], [OptJob("A", "x10", earliest=50, service_s=5)])
    stop = next(r for r in sol.routes).stops[0]
    assert (stop.arrival, stop.start, stop.depart) == (10, 50, 55)


def test_impossible_deadline_is_scheduled_and_flagged_late_not_dropped():
    sol = run([ALICE], [OptJob("A", "x1000", latest=10)])
    assert [j for j, _ in order(sol, "S1")] == ["A"]
    assert [(l.job_id, l.seconds_late) for l in sol.late] == [("A", 990)]
    assert not sol.unassigned


def test_unreachable_job_flagged_with_reason():
    sol = run([ALICE], [OptJob("A", "x10"), OptJob("lost", "island")])
    assert [j for j, _ in order(sol, "S1")] == ["A"]
    assert [(u.job_id, u.reason) for u in sol.unassigned] == [
        ("lost", "no staff member has a walking path to this job")]


def test_job_outside_every_shift_flagged_with_reason():
    short = OptStaff("S1", "x0", 0, 50)
    sol = run([short], [OptJob("far", "x1000")])
    assert [u.job_id for u in sol.unassigned] == ["far"]
    assert "shift" in sol.unassigned[0].reason


def test_overloaded_shift_flags_the_leftover_job():
    # Each job fits alone (10 + 30 service = 40 <= 60) but not both.
    s = OptStaff("S1", "x0", 0, 60)
    sol = run([s], [OptJob("A", "x10", service_s=30), OptJob("B", "x10", service_s=30)])
    assert len(order(sol, "S1")) == 1
    assert len(sol.unassigned) == 1 and "did not fit" in sol.unassigned[0].reason


def test_higher_priority_job_kept_on_time():
    # Two jobs at the same spot, both due by t=14, 10 s of service each: only one can be on time.
    jobs = [OptJob("routine", "x5", latest=14, service_s=10, priority=5),
            OptJob("stat", "x5", latest=14, service_s=10, priority=1)]
    sol = run([ALICE], jobs)
    assert [l.job_id for l in sol.late] == ["routine"]


def test_jobs_split_between_staff_by_location():
    staff = [OptStaff("S1", "x0", 0, 10_000), OptStaff("S2", "x100", 0, 10_000)]
    sol = run(staff, [OptJob("west", "x5"), OptJob("east", "x95")])
    assert [j for j, _ in order(sol, "S1")] == ["west"]
    assert [j for j, _ in order(sol, "S2")] == ["east"]
    assert sol.total_meters == 10


def test_deterministic():
    jobs = [OptJob(f"J{i}", f"x{(i * 37) % 200}", latest=(i * 53) % 400 or None) for i in range(12)]
    staff = [OptStaff("S1", "x0", 0, 10_000), OptStaff("S2", "x150", 0, 10_000)]
    assert run(staff, jobs) == run(staff, jobs)


def test_no_staff_or_no_jobs():
    assert run([ALICE], []).routes[0].stops == ()
    sol = run([], [OptJob("A", "x10")])
    assert [u.job_id for u in sol.unassigned] == ["A"]


# ---- baseline ---------------------------------------------------------------

def test_baseline_takes_jobs_in_due_order():
    jobs = [OptJob("A", "x100", latest=500), OptJob("B", "x10", latest=200), OptJob("C", "x50")]
    sol = run([ALICE], jobs, fn=baseline)
    assert [j for j, _ in order(sol, "S1")] == ["B", "A", "C"]
    assert sol.total_meters == 10 + 90 + 50


def test_optimizer_never_worse_than_baseline_on_same_inputs():
    jobs = [OptJob("A", "x100", latest=5000), OptJob("B", "x10", latest=4000), OptJob("C", "x50", latest=4500),
            OptJob("D", "x20", "x80")]
    staff = [ALICE]
    base, opt = run(staff, jobs, fn=baseline), run(staff, jobs)
    assert not base.late and not opt.late
    assert opt.total_meters < base.total_meters


def test_baseline_flags_jobs_it_cannot_fit():
    s = OptStaff("S1", "x0", 0, 60)
    sol = run([s], [OptJob("A", "x10", service_s=30), OptJob("B", "x10", service_s=30)], fn=baseline)
    assert [u.job_id for u in sol.unassigned] == ["B"]


# ---- real building ----------------------------------------------------------

AIREDALE = Path(__file__).resolve().parents[3] / "data" / "raw" / "matterport" / "6Ee2LwLfx58.json"


@pytest.mark.skipif(not AIREDALE.exists(), reason="Airedale export not present (gitignored; run tools/matterport_export)")
def test_airedale_plan_uses_real_graph_distances():
    from app.spatial.nav_graph import load_nav_graph

    g = load_nav_graph(AIREDALE)
    places = sorted(g.places.values(), key=lambda p: p.id)
    start = g.find_places("Nurses Station")[0].node_id
    # Test-only synthetic jobs on real place nodes.
    jobs = [OptJob(f"T{i}", p.node_id, service_s=60) for i, p in enumerate(places[:8])]
    jobs.append(OptJob("T-move", places[8].node_id, places[9].node_id))
    staff = [OptStaff("S1", start, 0, 3600 * 4), OptStaff("S2", start, 0, 3600 * 4)]

    opt = optimize(staff, jobs, g.distance_matrix)
    base = baseline(staff, jobs, g.distance_matrix)
    assert not opt.unassigned and not base.unassigned
    for r in opt.routes:  # every leg equals the A* shortest path
        prev = start
        for s in r.stops:
            assert s.meters_from_prev == pytest.approx(g.shortest_path(prev, s.node_id)[0])
            prev = s.node_id
    assert opt.total_meters <= base.total_meters
