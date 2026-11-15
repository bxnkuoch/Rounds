"""Domain API (/api): places, map geometry, staff, jobs, plans, routes, clock.

Thin: every route calls RoundsServices, the same functions the agent's tools
call (AGENTS.md §3.1). KeyError -> 404, ValueError -> 409 (state conflict:
stale/already applied) or 422 (bad input).

Applying a plan here is the human-in-the-UI path (a person clicks Approve on
the plan card). It's how the app keeps working when the agent is unavailable;
the agent itself can only apply through its interrupt_on approval.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.domain import Job, Place, Plan, Proposal, Route, StaffMember
from app.services.rounds import RoundsServices
from app.synthetic import ROLE_FOR_KIND
from app.synthetic.generator import PATIENT_ROOM

router = APIRouter(prefix="/api", tags=["rounds"])


def get_services(request: Request) -> RoundsServices:
    svc = request.app.state.services
    if svc is None:
        raise HTTPException(503, "building nav graph not loaded; run tools/matterport_export (see README)")
    return svc


def _call(fn, *args, conflict: bool = False, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except ValueError as e:
        raise HTTPException(409 if conflict else 422, str(e))


# ---- building -----------------------------------------------------------------

class MapNode(BaseModel):
    id: str
    x: float
    y: float
    floor_id: str | None
    room_id: str | None


class MapRoom(BaseModel):
    id: str
    label: str | None
    floor_id: str | None
    min_x: float
    min_y: float
    max_x: float
    max_y: float


class MapPlace(BaseModel):
    id: str
    name: str
    x: float
    y: float
    node_id: str


class BuildingMap(BaseModel):
    """2D floor-plan geometry (meters, z-up; x/y are the floor plane)."""
    model_id: str | None
    attribution: dict
    nodes: list[MapNode]
    edges: list[tuple[str, str]]
    rooms: list[MapRoom]
    places: list[MapPlace]


class Meta(BaseModel):
    scenario_label: str
    now: datetime
    shift_start: datetime
    shift_end: datetime
    unavailable_staff_ids: list[str]
    job_kinds: dict[str, str]  # kind -> role


@router.get("/meta")
def meta(svc: RoundsServices = Depends(get_services)) -> Meta:
    staff = svc.list_staff()
    return Meta(scenario_label=svc.scenario_label, now=svc.now,
                shift_start=min(s.shift_start for s in staff), shift_end=max(s.shift_end for s in staff),
                unavailable_staff_ids=svc.unavailable_staff_ids(), job_kinds=ROLE_FOR_KIND)


@router.get("/map")
def building_map(svc: RoundsServices = Depends(get_services)) -> BuildingMap:
    g = svc.graph
    return BuildingMap(
        model_id=g.source.get("model_id"),
        attribution=g.source.get("attribution", {}),
        nodes=[MapNode(id=n.id, x=n.x, y=n.y, floor_id=n.floor_id, room_id=n.room_id)
               for n in sorted(g.nodes.values(), key=lambda n: n.id)],
        edges=sorted({tuple(sorted((a, b))) for a, nbrs in g.adjacency.items() for b in nbrs}),
        rooms=[MapRoom(id=r.id, label=r.label, floor_id=r.floor_id, min_x=r.min_xyz[0], min_y=r.min_xyz[1],
                       max_x=r.max_xyz[0], max_y=r.max_xyz[1]) for r in sorted(g.rooms.values(), key=lambda r: r.id)],
        places=[MapPlace(id=p.id, name=p.name, x=p.x, y=p.y, node_id=p.node_id)
                for p in sorted(g.places.values(), key=lambda p: p.id)],
    )


@router.get("/places")
def places(svc: RoundsServices = Depends(get_services)) -> list[Place]:
    return svc.list_places()


@router.get("/routes")
def route(from_place_id: str, to_place_id: str, svc: RoundsServices = Depends(get_services)) -> Route:
    return _call(svc.route_between, from_place_id, to_place_id)


# ---- staff and jobs -----------------------------------------------------------

@router.get("/staff")
def staff(svc: RoundsServices = Depends(get_services)) -> list[StaffMember]:
    return svc.list_staff()


@router.get("/jobs")
def jobs(status: str | None = None, svc: RoundsServices = Depends(get_services)) -> list[Job]:
    return _call(svc.list_jobs, status)


class JobIn(BaseModel):
    kind: str
    pickup_place_id: str
    dropoff_place_id: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    priority: int = 3
    service_minutes: int | None = Field(default=None, gt=0, le=240)


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, svc: RoundsServices = Depends(get_services)) -> Job:
    """Dispatch inbox: a structured new request. Then notify the agent with
    POST /agent/threads/{id}/events {"kind": "job_added", "job_id": ...}."""
    return _call(svc.create_job, **body.model_dump())


STAT_KINDS = ("breathing_treatment", "iv_start", "transport")
STAT_DESTINATIONS = ("Main Entrance", "Ambulatory Care Lounge", "Assessment Room 1", "Assessment Room 2")


@router.post("/jobs/simulate-stat", status_code=201)
def simulate_stat(svc: RoundsServices = Depends(get_services)) -> Job:
    """Demo button: a SYNTHETIC priority-1 request due in 20 minutes, in a
    seeded-random patient room. Deterministic for a given number of jobs."""
    rng = random.Random(len(svc.list_jobs()))
    rooms = sorted((p for p in svc.list_places() if PATIENT_ROOM.match(p.name)), key=lambda p: p.id)
    if not rooms:
        raise HTTPException(409, "building has no patient rooms")
    kind = rng.choice(STAT_KINDS)
    dropoff = None
    if kind == "transport":
        dests = sorted((p for p in svc.list_places() if p.name in STAT_DESTINATIONS), key=lambda p: p.id)
        dropoff = rng.choice(dests).id if dests else None
        if dropoff is None:
            kind = "breathing_treatment"
    return _call(svc.create_job, kind, rng.choice(rooms).id, dropoff, earliest=svc.now,
                 latest=svc.now + timedelta(minutes=20), priority=1)


# ---- plans --------------------------------------------------------------------

class ProposeIn(BaseModel):
    job_ids: list[str] | None = None


@router.get("/plans/current")
def current_plan(svc: RoundsServices = Depends(get_services)) -> Plan | None:
    return svc.get_current_plan()


@router.post("/plans/propose")
def propose(body: ProposeIn | None = None, svc: RoundsServices = Depends(get_services)) -> Proposal:
    return _call(svc.propose_plan, body.job_ids if body else None)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, svc: RoundsServices = Depends(get_services)) -> Proposal:
    return _call(svc.get_proposal, plan_id)


@router.post("/plans/{plan_id}/apply")
def apply(plan_id: str, svc: RoundsServices = Depends(get_services)) -> Plan:
    return _call(svc.apply_plan, plan_id, conflict=True)


# ---- simulated clock (demo) -----------------------------------------------------

class ClockIn(BaseModel):
    now: datetime


@router.post("/clock")
def set_clock(body: ClockIn, svc: RoundsServices = Depends(get_services)) -> Meta:
    svc.set_now(body.now)
    return meta(svc)
