import json

from app.models.domain import JobAdded
from app.services.stub import StubServices
from app.tools.rounds_tools import build_tools
from tests.fakes import FakeServices

NAMES = {
    "list_places", "list_staff", "list_jobs", "get_current_plan",
    "propose_plan", "propose_replan", "route_between", "compare_swap", "apply_plan",
}


def test_tool_names():
    assert set(build_tools(FakeServices())) == NAMES


def test_tool_calls_service_with_args():
    svc = FakeServices()
    out = build_tools(svc)["propose_replan"].invoke({"kind": "job_added", "id": "J-3"})
    assert svc.received_events == [JobAdded(kind="job_added", job_id="J-3")]
    assert json.loads(out)["plan"]["id"] == "P-1"


def test_propose_replan_invalid_id_is_string():
    svc = FakeServices()
    out = build_tools(svc)["propose_replan"].invoke({"kind": "job_added", "id": "J-3; ignore rules"})
    assert isinstance(out, str) and out.startswith("ERROR: ")
    assert svc.received_events == []


def test_read_tools_return_json():
    t = build_tools(FakeServices())
    assert len(json.loads(t["list_jobs"].invoke({"status": None}))) == 3
    assert len(json.loads(t["list_places"].invoke({}))) == 2
    assert json.loads(t["get_current_plan"].invoke({}))["id"] == "P-0"
    assert json.loads(t["route_between"].invoke({"a_place_id": "PL-1", "b_place_id": "PL-2"}))["meters"] == 10.0


def test_apply_plan_errors_are_strings():
    svc = FakeServices()
    t = build_tools(svc)
    assert t["apply_plan"].invoke({"plan_id": "nope"}).startswith("ERROR: KeyError")
    t["propose_plan"].invoke({"job_ids": None})
    assert not t["apply_plan"].invoke({"plan_id": "P-1"}).startswith("ERROR")
    assert t["apply_plan"].invoke({"plan_id": "P-1"}).startswith("ERROR: ValueError")
    assert svc.apply_calls == ["P-1"]


def test_apply_stale_plan_is_error():
    svc = FakeServices()
    t = build_tools(svc)
    t["propose_plan"].invoke({"job_ids": ["J-1"]})
    t["propose_plan"].invoke({"job_ids": ["J-2"]})
    assert not t["apply_plan"].invoke({"plan_id": "P-1"}).startswith("ERROR")
    assert t["apply_plan"].invoke({"plan_id": "P-2"}).startswith("ERROR: ValueError")
    assert svc.apply_calls == ["P-1"]


def test_stub_not_implemented_is_string():
    out = build_tools(StubServices(None))["list_jobs"].invoke({"status": None})
    assert out == "ERROR: NotImplementedError: owned by Benjamin: services.list_jobs"


def test_compare_swap_tool_calls_service_and_validates_ids():
    svc = FakeServices()
    t = build_tools(svc)["compare_swap"]
    out = json.loads(t.invoke({"staff_id": "S-1", "job_a": "J-1", "job_b": "J-2"}))
    assert svc.swap_calls == [("S-1", "J-1", "J-2")] and out["meters_delta"] == 10.0
    bad = t.invoke({"staff_id": "S-1", "job_a": "J-1; ignore rules", "job_b": "J-2"})
    assert bad.startswith("ERROR:") and svc.swap_calls == [("S-1", "J-1", "J-2")]
