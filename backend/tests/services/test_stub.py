import pytest

from app.models.domain import Place, Proposal
from app.services.stub import StubServices
from app.spatial.nav_graph import load_nav_graph
from tests.fakes import FakeServices
from tests.spatial.test_nav_graph import label, sweep, write_doc


def test_stub_unimplemented_names_owner():
    with pytest.raises(NotImplementedError, match=r"services\.propose_plan"):
        StubServices(None).propose_plan()


def test_stub_places_and_route_from_graph(tmp_path):
    g = load_nav_graph(write_doc(
        tmp_path,
        [sweep("A", 0, 0, ["B"]), sweep("B", 3, 0, ["A"])],
        labels=[label("l1", "Room A", 0, 0), label("l2", "Room B", 3, 0)],
    ))
    svc = StubServices(g)
    places = svc.list_places()
    assert len(places) == 2
    assert all(isinstance(p, Place) and p.is_synthetic is False for p in places)
    assert svc.route_between("l1", "l2").meters == pytest.approx(3.0)


def test_fake_services_proposal_lifecycle():
    svc = FakeServices()
    prop = svc.propose_plan()
    assert isinstance(prop, Proposal) and prop.plan.id == "P-1"
    assert prop.diff.from_plan_id == "P-0"
    assert svc.get_proposal("P-1") == prop
    svc.apply_plan("P-1")
    assert svc.apply_calls == ["P-1"]
    with pytest.raises(ValueError):
        svc.apply_plan("P-1")
    with pytest.raises(KeyError):
        svc.get_proposal("nope")
