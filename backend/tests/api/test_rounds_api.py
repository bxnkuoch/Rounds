"""Domain API (/api) and app wiring in main.py, on the small line-building fixture."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.services.rounds import RoundsServices
from app.synthetic import generate_scenario
from tests.services.test_rounds_services import line_building


@pytest.fixture
def client(monkeypatch):
    g = line_building()
    svc = RoundsServices(g, generate_scenario(g, seed=1, rt_jobs=3, iv_jobs=3, transport_jobs=2))
    monkeypatch.setattr(main, "build_services", lambda path, seed: svc)
    with TestClient(main.app) as c:
        yield c


def test_health_and_agent_uses_same_services(client):
    assert client.get("/health").json() == {"ok": True, "domain_api": True}
    assert main.app.state.agent_runtime.services is main.app.state.services
    assert client.post("/agent/threads").status_code == 200


def test_meta_is_labeled_synthetic(client):
    m = client.get("/api/meta").json()
    assert m["scenario_label"].startswith("SYNTHETIC")
    assert m["now"] == m["shift_start"] and m["job_kinds"]["transport"] == "transporter"


def test_map_geometry(client):
    m = client.get("/api/map").json()
    assert len(m["nodes"]) == 9 and len(m["edges"]) == 8 and len(m["places"]) == 9
    assert m["model_id"] == "TEST"


def test_reads(client):
    assert len(client.get("/api/places").json()) == 9
    assert len(client.get("/api/staff").json()) == 6
    assert len(client.get("/api/jobs").json()) == 8
    assert client.get("/api/jobs", params={"status": "done"}).json() == []
    assert client.get("/api/jobs", params={"status": "open"}).status_code == 422
    r = client.get("/api/routes", params={"from_place_id": "p0", "to_place_id": "p2"}).json()
    assert r["meters"] == 20
    assert client.get("/api/routes", params={"from_place_id": "p0", "to_place_id": "zz"}).status_code == 404


def test_propose_apply_flow(client):
    assert client.get("/api/plans/current").json() is None
    proposal = client.post("/api/plans/propose").json()
    pid = proposal["plan"]["id"]
    assert proposal["plan"]["baseline"]["total_meters"] >= proposal["plan"]["total_meters"]
    assert client.get(f"/api/plans/{pid}").json() == proposal
    assert client.post(f"/api/plans/{pid}/apply").json()["id"] == pid
    assert client.get("/api/plans/current").json()["id"] == pid
    assert client.post(f"/api/plans/{pid}/apply").status_code == 409
    assert client.post("/api/plans/P-404/apply").status_code == 404
    assert client.post("/api/plans/propose", json={"job_ids": ["nope"]}).status_code == 404


def test_create_job_and_validation(client):
    r = client.post("/api/jobs", json={"kind": "transport", "pickup_place_id": "p0", "dropoff_place_id": "p7",
                                       "priority": 2})
    assert r.status_code == 201 and r.json()["status"] == "new"
    assert client.post("/api/jobs", json={"kind": "surgery", "pickup_place_id": "p0"}).status_code == 422
    assert client.post("/api/jobs", json={"kind": "iv_start", "pickup_place_id": "zz"}).status_code == 404


def test_simulate_stat(client):
    now = client.get("/api/meta").json()["now"]
    job = client.post("/api/jobs/simulate-stat").json()
    assert job["priority"] == 1 and job["earliest"] == now and job["id"].startswith("SYN-J-")
    proposal = client.post("/api/plans/propose").json()
    assert job["id"] in {s["job_id"] for a in proposal["plan"]["assignments"] for s in a["stops"]}


def test_simulate_stat_transport_never_drops_off_where_it_picks_up(client):
    jobs = [client.post("/api/jobs/simulate-stat").json() for _ in range(40)]
    assert any(j["kind"] == "transport" for j in jobs)
    assert all(j["dropoff_place_id"] != j["pickup_place_id"] for j in jobs)


def test_clock(client):
    m = client.post("/api/clock", json={"now": "2026-11-15T09:30:00"}).json()
    assert m["now"] == "2026-11-15T09:30:00"


def test_cors_for_vite_dev_server(client):
    r = client.options("/api/places", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_no_graph_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "graph_path", lambda: tmp_path / "missing.json")
    with TestClient(main.app) as c:
        assert c.get("/health").json() == {"ok": True, "domain_api": False}
        assert c.get("/api/places").status_code == 503
        assert c.post("/agent/threads").status_code == 200
