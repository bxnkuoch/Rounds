# v0 stub: Benjamin replaces the NotImplementedError bodies.
from app.models.domain import Job, Place, Plan, Proposal, ReplanEvent, Route, StaffMember, SwapComparison
from app.spatial.nav_graph import NavGraph


def _todo(name: str) -> NotImplementedError:
    return NotImplementedError(f"owned by Benjamin: services.{name}")


class StubServices:
    def __init__(self, graph: NavGraph | None):
        self.graph = graph

    def _graph(self) -> NavGraph:
        if self.graph is None:
            raise RuntimeError("no navigation graph loaded")
        return self.graph

    def list_places(self) -> list[Place]:
        return [
            Place(id=p.id, name=p.name, kind=p.kind, node_id=p.node_id, room_id=p.room_id, is_synthetic=False)
            for p in self._graph().places.values()
        ]

    def route_between(self, a_place_id: str, b_place_id: str) -> Route:
        g = self._graph()
        a, b = g.places[a_place_id], g.places[b_place_id]
        meters, node_ids = g.shortest_path(a.node_id, b.node_id)
        return Route(from_place_id=a_place_id, to_place_id=b_place_id, meters=meters, node_ids=node_ids)

    def list_staff(self) -> list[StaffMember]:
        raise _todo("list_staff")

    def list_jobs(self, status: str | None = None) -> list[Job]:
        raise _todo("list_jobs")

    def get_current_plan(self) -> Plan | None:
        raise _todo("get_current_plan")

    def propose_plan(self, job_ids: list[str] | None = None) -> Proposal:
        raise _todo("propose_plan")

    def propose_replan(self, event: ReplanEvent) -> Proposal:
        raise _todo("propose_replan")

    def get_proposal(self, plan_id: str) -> Proposal:
        raise _todo("get_proposal")

    def apply_plan(self, plan_id: str) -> Plan:
        raise _todo("apply_plan")

    def compare_swap(self, staff_id: str, job_a: str, job_b: str) -> SwapComparison:
        raise _todo("compare_swap")
