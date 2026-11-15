from datetime import timedelta
from pathlib import Path

import pytest
from app.models.domain import JobAdded, StaffUnavailable
from app.services.contract import Services
from app.services.rounds import RoundsServices
from app.spatial.nav_graph import NavGraph, Node, Place
from app.synthetic import generate_scenario

NAMES = ["Room 1", "Room 2", "Room 3", "Assessment Room 1", "Assessment Room 2", "Nurses Station",
         "Reception", "Main Entrance", "Ambulatory Care Lounge"]


def line_building() -> NavGraph:
    """Places 10 m apart along one corridor: p0 - p1 - ... - p8."""
    n = len(NAMES)
    nodes = {f"n{i}": Node(f"n{i}", "f1", 0, 10.0 * i, 0.0, 0.0) for i in range(n)}
    adj = {f"n{i}": {} for i in range(n)}
    for i in range(n - 1):
        adj[f"n{i}"][f"n{i + 1}"] = adj[f"n{i + 1}"][f"n{i}"] = 10.0
    places = {f"p{i}": Place(f"p{i}", name, "label", "f1", 10.0 * i, 0.0, 0.0, None, f"n{i}")
              for i, name in enumerate(NAMES)}
    return NavGraph(nodes=nodes, adjacency=adj, places=places, source={"model_id": "TEST"})


@pytest.fixture
def svc() -> RoundsServices:
    g = line_building()
    return RoundsServices(g, generate_scenario(g, seed=1, rt_jobs=3, iv_jobs=3, transport_jobs=2))


def scheduled(plan):
    return [(s.job_id, s.action) for a in plan.assignments for s in a.stops]


def test_implements_every_contract_method(svc):
    names = [n for n in vars(Services) if not n.startswith("_")]
    assert names and all(callable(getattr(svc, n)) for n in names)
    _: Services = svc  # type-checker hint; no runtime effect


def test_places_are_real_not_synthetic(svc):
    places = svc.list_places()
    assert {p.id for p in places} == set(svc.graph.places)
    assert not any(p.is_synthetic for p in places)


def test_propose_covers_every_job_and_changes_nothing(svc):
    proposal = svc.propose_plan()
    plan = proposal.plan
    stops = scheduled(plan)
    for j in svc.list_jobs():
        want = [(j.id, "pickup"), (j.id, "dropoff")] if j.dropoff_place_id else [(j.id, "service")]
        bad = any(i.job_id == j.id for i in plan.infeasible)
        assert ([s for s in stops if s[0] == j.id] == want) != bad, j.id  # scheduled exactly once xor flagged
    assert plan.baseline is not None and plan.total_meters <= plan.baseline.total_meters
    assert proposal.diff.from_plan_id is None and proposal.diff.to_plan_id == plan.id
    assert svc.get_current_plan() is None
    assert all(j.status == "new" for j in svc.list_jobs())
    assert svc.get_proposal(plan.id) == proposal


def test_etas_start_at_now_and_increase(svc):
    plan = svc.propose_plan().plan
    for a in plan.assignments:
        etas = [s.eta for s in a.stops]
        assert all(e >= svc.now for e in etas) and etas == sorted(etas)


def test_eta_is_service_start_not_early_arrival(svc):
    # Staff reach p1 in seconds, but the job can't start until 45 min in.
    start = svc.now + timedelta(minutes=45)
    job = svc.create_job("breathing_treatment", "p1", earliest=start, latest=start + timedelta(minutes=30))
    stop = next(s for a in svc.propose_plan([job.id]).plan.assignments for s in a.stops)
    assert stop.eta == start


def test_apply_sets_current_and_statuses_once(svc):
    pid = svc.propose_plan().plan.id
    plan = svc.apply_plan(pid)
    assert svc.get_current_plan() == plan
    planned = {j for j, _ in scheduled(plan)}
    assert all(j.status == ("planned" if j.id in planned else "new") for j in svc.list_jobs())
    with pytest.raises(ValueError, match="already applied"):
        svc.apply_plan(pid)
    with pytest.raises(KeyError):
        svc.apply_plan("P-999")
    with pytest.raises(KeyError):
        svc.get_proposal("nope")


def test_stale_proposal_cannot_be_applied(svc):
    p1, p2 = svc.propose_plan().plan.id, svc.propose_plan().plan.id
    svc.apply_plan(p1)
    with pytest.raises(ValueError, match="stale"):
        svc.apply_plan(p2)


def test_job_added_replan_diff(svc):
    svc.apply_plan(svc.propose_plan().plan.id)
    job = svc.create_job("breathing_treatment", "p1", priority=1, latest=svc.now + timedelta(minutes=20))
    proposal = svc.propose_replan(JobAdded(kind="job_added", job_id=job.id))
    assert proposal.diff.from_plan_id == svc.get_current_plan().id
    assert job.id in proposal.diff.added_job_ids
    assert job.id in {j for j, _ in scheduled(proposal.plan)}
    with pytest.raises(KeyError):
        svc.propose_replan(JobAdded(kind="job_added", job_id="SYN-J-999"))


def test_staff_unavailable_only_after_apply(svc):
    out = "SYN-RT-1"
    proposal = svc.propose_replan(StaffUnavailable(kind="staff_unavailable", staff_id=out))
    assert out not in {a.staff_id for a in proposal.plan.assignments}
    # Not applied (e.g. human rejected): still available.
    assert out in {a.staff_id for a in svc.propose_plan().plan.assignments}
    svc.apply_plan(svc.propose_replan(StaffUnavailable(kind="staff_unavailable", staff_id=out)).plan.id)
    assert svc.unavailable_staff_ids() == [out]
    assert out not in {a.staff_id for a in svc.propose_plan().plan.assignments}


def test_role_with_no_staff_flags_its_jobs(svc):
    for tr in ("SYN-TR-1", "SYN-TR-2"):
        svc.apply_plan(svc.propose_replan(StaffUnavailable(kind="staff_unavailable", staff_id=tr)).plan.id)
    plan = svc.propose_plan().plan
    transports = {j.id for j in svc.list_jobs() if j.kind == "transport"}
    flagged = {i.job_id: i.reason for i in plan.infeasible}
    assert transports and all("no available transporter" in flagged[t] for t in transports)


def test_past_deadline_is_scheduled_and_reported_late(svc):
    svc.set_now(svc.now + timedelta(hours=2))
    job = svc.create_job("iv_start", "p0", latest=svc.now - timedelta(minutes=30))
    plan = svc.propose_plan([job.id]).plan
    assert scheduled(plan) == [(job.id, "service")]
    assert [l.job_id for l in plan.late] == [job.id] and plan.late[0].minutes_late >= 30
    assert not plan.infeasible


def test_propose_subset_and_unknown_ids(svc):
    some = [j.id for j in svc.list_jobs()][:2]
    assert {j for j, _ in scheduled(svc.propose_plan(some).plan)} <= set(some)
    with pytest.raises(KeyError):
        svc.propose_plan(["SYN-J-999"])


def test_create_job_validation(svc):
    assert svc.create_job("transport", "p0", "p7").id.startswith("SYN-J-")
    with pytest.raises(ValueError):
        svc.create_job("surgery", "p0")
    with pytest.raises(ValueError):
        svc.create_job("transport", "p0")
    with pytest.raises(ValueError):
        svc.create_job("iv_start", "p0", "p7")
    with pytest.raises(KeyError):
        svc.create_job("iv_start", "nowhere")
    with pytest.raises(ValueError):
        svc.create_job("iv_start", "p0", priority=9)


def test_list_jobs_rejects_unknown_status(svc):
    # The agent once asked for status="open"; an error it can read beats a silent [].
    with pytest.raises(ValueError, match="new"):
        svc.list_jobs("open")


def test_route_between(svc):
    r = svc.route_between("p0", "p3")
    assert r.meters == 30 and r.node_ids == ["n0", "n1", "n2", "n3"]


AIREDALE = Path(__file__).resolve().parents[3] / "data" / "raw" / "matterport" / "6Ee2LwLfx58.json"


@pytest.mark.skipif(not AIREDALE.exists(), reason="Airedale export not present (gitignored; run tools/matterport_export)")
def test_airedale_full_scenario():
    from app.spatial.nav_graph import load_nav_graph

    g = load_nav_graph(AIREDALE)
    svc = RoundsServices(g, generate_scenario(g, seed=0))
    plan = svc.apply_plan(svc.propose_plan().plan.id)
    assert not plan.infeasible
    assert plan.total_meters < plan.baseline.total_meters


def test_agent_tools_run_on_real_services(svc):
    """Minh's tool wrappers (app/tools) work against RoundsServices, not only fakes."""
    import json

    from app.tools.rounds_tools import build_tools

    tools = build_tools(svc)
    proposal = json.loads(tools["propose_plan"].invoke({}))
    pid = proposal["plan"]["id"]
    assert json.loads(tools["apply_plan"].invoke({"plan_id": pid}))["id"] == pid
    assert tools["apply_plan"].invoke({"plan_id": pid}).startswith("ERROR: ValueError")
    job = svc.create_job("iv_start", "p2")
    replan = json.loads(tools["propose_replan"].invoke({"kind": "job_added", "id": job.id}))
    assert job.id in replan["diff"]["added_job_ids"]
    assert json.loads(tools["route_between"].invoke({"a_place_id": "p0", "b_place_id": "p2"}))["meters"] == 20


def test_compare_swap_replays_current_order_and_swap(svc):
    plan = svc.apply_plan(svc.propose_plan().plan.id)
    a = next(a for a in plan.assignments if len({s.job_id for s in a.stops}) >= 2)
    order = list(dict.fromkeys(s.job_id for s in a.stops))
    cmp = svc.compare_swap(a.staff_id, order[0], order[1])
    # The current order replays to exactly the plan's stops and meters.
    assert cmp.current_order.job_ids == order and cmp.plan_id == plan.id
    assert [(s.job_id, s.action, s.place_id, s.eta) for s in cmp.current_order.stops] == [
        (s.job_id, s.action, s.place_id, s.eta) for s in a.stops]
    assert cmp.current_order.total_meters == round(sum(s.meters_from_prev for s in a.stops), 2)
    assert cmp.swapped_order.job_ids == [order[1], order[0]] + order[2:]
    assert cmp.meters_delta == round(cmp.swapped_order.total_meters - cmp.current_order.total_meters, 2)
    assert cmp.late_jobs_delta == len(cmp.swapped_order.late) - len(cmp.current_order.late)
    assert svc.get_current_plan().id == plan.id and len(svc._proposals) == 1  # read-only


def test_compare_swap_errors(svc):
    with pytest.raises(ValueError, match="no current plan"):
        svc.compare_swap("SYN-RT-1", "SYN-J-001", "SYN-J-002")
    plan = svc.apply_plan(svc.propose_plan().plan.id)
    a = next(a for a in plan.assignments if a.stops)
    other = next(s.job_id for b in plan.assignments if b.staff_id != a.staff_id for s in b.stops)
    with pytest.raises(KeyError):
        svc.compare_swap("nobody", a.stops[0].job_id, other)
    with pytest.raises(ValueError, match="not on"):
        svc.compare_swap(a.staff_id, a.stops[0].job_id, other)
    with pytest.raises(ValueError, match="different"):
        svc.compare_swap(a.staff_id, a.stops[0].job_id, a.stops[0].job_id)


def test_shift_summary_reports_remaining_work_after_now(svc):
    empty = svc.shift_summary()
    assert empty.plan_id is None and empty.total_meters is None and empty.scenario_label.startswith("SYNTHETIC")
    assert sorted(empty.unscheduled_job_ids) == sorted(j.id for j in svc.list_jobs())
    plan = svc.apply_plan(svc.propose_plan().plan.id)
    s = svc.shift_summary()
    assert s.plan_id == plan.id and s.total_meters == plan.total_meters and s.unscheduled_job_ids == []
    assert s.baseline_meters == plan.baseline.total_meters and s.late == plan.late
    busy = next(a for a in plan.assignments if len(a.stops) >= 2)
    row = next(r for r in s.staff if r.staff_id == busy.staff_id)
    assert row.next_stop == busy.stops[0] and row.remaining_job_ids == list(dict.fromkeys(x.job_id for x in busy.stops))
    # Move the clock past the first stop: it drops out of what's left.
    svc.set_now(busy.stops[0].eta + timedelta(seconds=1))
    row = next(r for r in svc.shift_summary().staff if r.staff_id == busy.staff_id)
    assert row.next_stop == busy.stops[1]
    assert row.next_place_name == svc.graph.places[busy.stops[1].place_id].name
    assert row.remaining_meters == round(sum(x.meters_from_prev for x in busy.stops[1:]), 2)
