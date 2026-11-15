"""Navigation graph loader tests.

Small hand-built fixtures with known answers, plus one integration test on the
real Airedale export (skipped when the gitignored file isn't present).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.spatial.nav_graph import NavGraph, NoPathError, load_nav_graph

FLOOR = "f0"


def sweep(sid, x, y, neighbors, *, z=0.0, floor=FLOOR, seq=0, placement="auto", alignment="aligned", enabled=True):
    return {
        "id": sid,
        "uuid": None,
        "floor_id": floor,
        "floor_sequence": seq,
        "position": {"x": x, "y": y, "z": z + 1.5},
        "floor_position": {"x": x, "y": y, "z": z},
        "neighbors": neighbors,
        "enabled": enabled,
        "alignment": alignment,
        "placement": placement,
    }


def room(rid, xmin, ymin, xmax, ymax, label=None, floor=FLOOR):
    return {
        "id": rid,
        "label": label,
        "floor_id": floor,
        "center": {"x": (xmin + xmax) / 2, "y": (ymin + ymax) / 2, "z": 1.5},
        "bounds": {"min": {"x": xmin, "y": ymin, "z": 0.0}, "max": {"x": xmax, "y": ymax, "z": 3.0}},
        "size": {"x": xmax - xmin, "y": ymax - ymin, "z": 3.0},
    }


def write_doc(tmp_path: Path, sweeps, rooms=(), floors=None, labels=None, tags=None) -> Path:
    doc = {
        **({"labels": labels} if labels is not None else {}),
        **({"tags": tags} if tags is not None else {}),
        "schema_version": 1,
        "source": {"kind": "matterport-showcase-sdk", "model_id": "TESTMODEL01", "attribution": {"name": "fixture"}},
        "coordinate_frame": {"units": "meters", "up_axis": "z"},
        "floors": floors if floors is not None else [{"id": FLOOR, "sequence": 0, "name": "Floor 1"}],
        "rooms": list(rooms),
        "sweeps": list(sweeps),
    }
    p = tmp_path / "model.json"
    p.write_text(json.dumps(doc))
    return p


@pytest.fixture
def corridor(tmp_path) -> NavGraph:
    """
    A(0,0) --- B(3,0) --- C(6,0)
     |                     |
    D(0,4) --------------- E(6,4)

    A->C via B = 6. A->E: via B,C = 10, via D = 4 + 6 = 10, tie; A->D->E is the
    only route if B-C were missing. Unplaced U has no position.
    The B->C link is listed on B only (asymmetric) to check it's made undirected.
    """
    return load_nav_graph(write_doc(tmp_path, [
        sweep("A", 0, 0, ["B", "D"]),
        sweep("B", 3, 0, ["A", "C"]),
        sweep("C", 6, 0, ["E"]),
        sweep("D", 0, 4, ["A", "E"]),
        sweep("E", 6, 4, ["C", "D"]),
        sweep("U", 0, 0, [], placement="unplaced", alignment="unaligned"),
    ], rooms=[room("r_left", -1, -1, 1, 5), room("r_small", 2, -1, 4, 1, label="Supply")]))


def test_edges_weighted_by_floor_distance_and_undirected(corridor):
    assert corridor.edge_length("A", "B") == pytest.approx(3.0)
    assert corridor.edge_length("B", "C") == pytest.approx(3.0)
    assert corridor.edge_length("C", "B") == pytest.approx(3.0)  # only B listed C
    assert corridor.edge_length("D", "E") == pytest.approx(6.0)
    assert corridor.edge_length("A", "C") is None


def test_unplaced_sweeps_dropped_and_reported(corridor):
    assert "U" not in corridor.nodes
    assert corridor.dropped == {"U": "unplaced"}


def test_shortest_path_known_answer(corridor):
    dist, path = corridor.shortest_path("A", "C")
    assert dist == pytest.approx(6.0)
    assert path == ["A", "B", "C"]
    dist, path = corridor.shortest_path("A", "E")
    assert dist == pytest.approx(10.0)
    assert path[0] == "A" and path[-1] == "E"


def test_shortest_path_to_self(corridor):
    assert corridor.shortest_path("B", "B") == (0.0, ["B"])


def test_unknown_node_raises(corridor):
    with pytest.raises(KeyError):
        corridor.shortest_path("A", "U")


def test_no_path_raises(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [sweep("A", 0, 0, []), sweep("B", 1, 0, [])]))
    with pytest.raises(NoPathError):
        g.shortest_path("A", "B")
    assert sorted(map(sorted, g.components())) == [["A"], ["B"]]


def test_distance_matrix_matches_shortest_paths(corridor):
    ids = ["A", "C", "E"]
    m = corridor.distance_matrix(ids)
    assert m[0][1] == pytest.approx(6.0)
    assert m[0][2] == pytest.approx(10.0)
    assert m[1][2] == pytest.approx(4.0)
    for i in range(3):
        assert m[i][i] == 0.0
        for j in range(3):
            assert m[i][j] == pytest.approx(m[j][i])


def test_distance_matrix_unreachable_is_inf(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [sweep("A", 0, 0, []), sweep("B", 1, 0, [])]))
    assert g.distance_matrix(["A", "B"])[0][1] == math.inf


def test_rooms_assigned_by_bounds_smallest_wins(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [
        sweep("in_both", 3, 0, []),
        sweep("in_big", 8, 8, []),
        sweep("outside", 50, 50, []),
    ], rooms=[room("big", 0, -5, 10, 10), room("small", 2, -1, 4, 1, label="Supply")]))
    assert g.nodes["in_both"].room_id == "small"
    assert g.nodes["in_big"].room_id == "big"
    assert g.nodes["outside"].room_id is None
    assert g.rooms["small"].label == "Supply"
    assert g.nodes_in_room("big") == ["in_big"]


def test_rooms_respect_floor(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [
        sweep("up", 0, 0, [], z=4.0, floor="f1", seq=1),
    ], rooms=[room("ground", -1, -1, 1, 1)], floors=[
        {"id": FLOOR, "sequence": 0, "name": "Floor 1"}, {"id": "f1", "sequence": 1, "name": "Floor 2"}]))
    assert g.nodes["up"].room_id is None


def test_multi_floor_edge_includes_vertical_distance(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [
        sweep("low", 0, 0, ["high"]),
        sweep("high", 3, 0, ["low"], z=4.0, floor="f1", seq=1),
    ], floors=[{"id": FLOOR, "sequence": 0, "name": "1"}, {"id": "f1", "sequence": 1, "name": "2"}]))
    assert g.edge_length("low", "high") == pytest.approx(5.0)


def test_nearest_node(corridor):
    assert corridor.nearest_node(5.5, 0.4) == "C"
    assert corridor.nearest_node(0.2, 3.0, floor_id=FLOOR) == "D"


def test_rejects_unknown_schema(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": 99, "sweeps": []}))
    with pytest.raises(ValueError, match="schema_version"):
        load_nav_graph(p)


def label(lid, text, x, y, floor=FLOOR, visible=True):
    return {"id": lid, "text": text, "visible": visible, "floor_id": floor, "position": {"x": x, "y": y, "z": 0.0}}


def tag(tid, text, x, y, z=0.0):
    return {"id": tid, "label": text, "description": None, "room_id": None, "position": {"x": x, "y": y, "z": z}}


def test_places_loaded_and_snapped_to_nearest_node(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [
        sweep("A", 0, 0, ["B"]), sweep("B", 10, 0, ["A"]),
    ], labels=[label("l1", " Nurses Station ", 9, 1)], tags=[tag("t1", "Dirty Utility", 1, 0.5)]))
    ns = g.places["l1"]
    assert (ns.name, ns.kind, ns.node_id, ns.floor_id) == ("Nurses Station", "label", "B", FLOOR)
    du = g.places["t1"]
    assert (du.kind, du.node_id, du.floor_id) == ("tag", "A", FLOOR)  # tag floor inferred


def test_place_inside_room_snaps_into_that_room(tmp_path):
    # corridor node C is closer to the label, but the label sits in room r4,
    # whose only node is R; routing to "Room 4" must end inside the room.
    g = load_nav_graph(write_doc(tmp_path, [
        sweep("C", 0, 0, ["R"]), sweep("R", 4, 0, ["C"]),
    ], rooms=[room("r4", 1, -1, 6, 1)], labels=[label("l4", "Room 4", 1.2, 0)]))
    assert g.places["l4"].room_id == "r4"
    assert g.places["l4"].node_id == "R"


def test_hidden_and_empty_labels_skipped(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [sweep("A", 0, 0, [])],
                                 labels=[label("h", "Hidden", 0, 0, visible=False), label("e", "", 0, 0)]))
    assert g.places == {}


def test_missing_labels_and_tags_ok(corridor):
    assert corridor.places == {}


def test_find_places_case_insensitive_and_duplicates(tmp_path):
    g = load_nav_graph(write_doc(tmp_path, [sweep("A", 0, 0, [])], labels=[
        label("b1", "5 Bed Bays with Showers", 0, 0), label("b2", "5 Bed Bays with Showers", 0, 0),
        label("n", "Nurses Station", 0, 0)]))
    assert [p.id for p in g.find_places("bed bays")] == ["b1", "b2"]
    assert [p.id for p in g.find_places("NURSES")] == ["n"]


AIREDALE = Path(__file__).resolve().parents[3] / "data" / "raw" / "matterport" / "6Ee2LwLfx58.json"


@pytest.mark.skipif(not AIREDALE.exists(), reason="Airedale export not present (gitignored; run tools/matterport_export)")
def test_airedale_export_loads_connected():
    g = load_nav_graph(AIREDALE)
    assert len(g.dropped) == 5 and set(g.dropped.values()) == {"unplaced"}
    comps = g.components()
    assert len(comps) == 1 and len(comps[0]) == len(g.nodes) == 104
    ids = sorted(g.nodes)[:10]
    m = g.distance_matrix(ids)
    assert all(math.isfinite(v) for row in m for v in row)
    # labels/tags were added to the exporter later; older exports have none
    if g.places:
        assert len(g.places) == 38
        assert [p.kind for p in g.find_places("Nurses Station")] == ["label"]
        assert all(p.node_id in g.nodes for p in g.places.values())
