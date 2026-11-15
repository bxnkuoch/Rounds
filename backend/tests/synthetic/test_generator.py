from datetime import date
from pathlib import Path

import pytest

from app.optimization import OptJob, OptStaff, baseline, optimize
from app.spatial.nav_graph import NavGraph, Node, Place
from app.synthetic import ROLE_FOR_KIND, generate_scenario
from app.synthetic.generator import TRANSPORT_DESTINATIONS

NAMES = ["Room 1", "Room 2", "Room 3", "Assessment Room 1", "Assessment Room 2", "Nurses Station",
         "Reception", "Main Entrance", "Ambulatory Care Lounge", "Crash Trolley"]


def building(names=NAMES) -> NavGraph:
    nodes = {f"n{i}": Node(f"n{i}", "f1", 0, float(i), 0.0, 0.0) for i in range(len(names))}
    places = {f"p{i}": Place(f"p{i}", n, "label", "f1", float(i), 0.0, 0.0, None, f"n{i}")
              for i, n in enumerate(names)}
    return NavGraph(nodes=nodes, adjacency={n: {} for n in nodes}, places=places, source={"model_id": "TEST"})


def test_same_seed_same_scenario_different_seed_differs():
    g = building()
    assert generate_scenario(g, seed=7) == generate_scenario(g, seed=7)
    assert generate_scenario(g, seed=7).jobs != generate_scenario(g, seed=8).jobs


def test_everything_labeled_synthetic_with_unique_ids():
    s = generate_scenario(building())
    assert s.label.startswith("SYNTHETIC")
    ids = [x.id for x in s.staff] + [j.id for j in s.jobs]
    assert all(i.startswith("SYN-") for i in ids)
    assert len(ids) == len(set(ids))


def test_counts_roles_and_real_place_ids():
    g = building()
    s = generate_scenario(g, staff_per_role=3, rt_jobs=4, iv_jobs=5, transport_jobs=6)
    assert sorted(st.role for st in s.staff) == sorted(["respiratory_therapist", "iv_nurse", "transporter"] * 3)
    kinds = [j.kind for j in s.jobs]
    assert sum(ROLE_FOR_KIND[k] == "respiratory_therapist" for k in kinds) == 4
    assert sum(ROLE_FOR_KIND[k] == "iv_nurse" for k in kinds) == 5
    assert kinds.count("transport") == 6
    used = {st.start_place_id for st in s.staff} | {j.pickup_place_id for j in s.jobs} | {
        j.dropoff_place_id for j in s.jobs if j.dropoff_place_id}
    assert used <= set(g.places)
    assert g.places["p9"].id not in used  # "Crash Trolley" is not a patient room or destination


def test_job_shapes_and_windows_inside_shift():
    g = building()
    dest_ids = {p.id for p in g.places.values() if p.name in TRANSPORT_DESTINATIONS}
    s = generate_scenario(g, seed=3)
    for j in s.jobs:
        assert j.priority in (1, 2, 3) and j.status == "new" and j.service_minutes > 0
        assert (j.dropoff_place_id is not None) == (j.kind == "transport")
        if j.dropoff_place_id:
            assert j.dropoff_place_id in dest_ids
            assert j.dropoff_place_id != j.pickup_place_id
        for t in (j.earliest, j.latest):
            assert t is None or s.shift_start <= t <= s.shift_end
        if j.earliest and j.latest:
            assert j.earliest < j.latest
    assert s.shift_start.date() == date(2026, 11, 15)


def test_missing_required_place_raises():
    with pytest.raises(ValueError, match="Reception"):
        generate_scenario(building([n for n in NAMES if n != "Reception"]))


AIREDALE = Path(__file__).resolve().parents[3] / "data" / "raw" / "matterport" / "6Ee2LwLfx58.json"


@pytest.mark.skipif(not AIREDALE.exists(), reason="Airedale export not present (gitignored; run tools/matterport_export)")
def test_airedale_scenario_is_plannable_per_role():
    from app.spatial.nav_graph import load_nav_graph

    g = load_nav_graph(AIREDALE)
    s = generate_scenario(g, seed=0)

    def secs(t):
        return None if t is None else int((t - s.shift_start).total_seconds())

    for role in ("respiratory_therapist", "iv_nurse", "transporter"):
        staff = [OptStaff(x.id, g.places[x.start_place_id].node_id, 0, secs(x.shift_end))
                 for x in s.staff if x.role == role]
        jobs = [OptJob(j.id, g.places[j.pickup_place_id].node_id,
                       g.places[j.dropoff_place_id].node_id if j.dropoff_place_id else None,
                       secs(j.earliest), secs(j.latest), j.service_minutes * 60, j.priority)
                for j in s.jobs if ROLE_FOR_KIND[j.kind] == role]
        opt, base = optimize(staff, jobs, g.distance_matrix), baseline(staff, jobs, g.distance_matrix)
        assert not opt.unassigned, role
        assert opt.total_meters <= base.total_meters + 1e-6, role
