"""Synthetic shift scenario on a real building's named places.

Everything this module creates is SYNTHETIC: staff, jobs, times and
priorities are generated from a seed, never taken from real patients or
staff. Ids start with "SYN-" and every Scenario carries a `label` saying so.
The places they point at are real (Matterport labels/tags), addressed by id.

Deterministic: the same graph + seed + date gives the same scenario.
Fields mirror the shared v0 contract (StaffMember, Job) so services can
convert 1:1.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.spatial.nav_graph import NavGraph, Place

SHIFT_START = time(7, 0)
SHIFT_HOURS = 8

ROLE_FOR_KIND = {
    "breathing_treatment": "respiratory_therapist",
    "ventilator_check": "respiratory_therapist",
    "iv_start": "iv_nurse",
    "line_placement": "iv_nurse",
    "transport": "transporter",
}
SERVICE_MINUTES = {
    "breathing_treatment": 15, "ventilator_check": 10, "iv_start": 20, "line_placement": 45, "transport": 10,
}
# Priority 1 = most urgent. Weights are synthetic: mostly routine, a few urgent, rarely STAT.
_PRIORITY_WEIGHTS = {1: 1, 2: 3, 3: 10}

PATIENT_ROOM = re.compile(r"^(Room \d+|Assessment Room \d+)$")
CLINICIAN_START = "Nurses Station"
TRANSPORTER_START = "Reception"
TRANSPORT_DESTINATIONS = ("Main Entrance", "Ambulatory Care Lounge", "Assessment Room 1", "Assessment Room 2")


@dataclass(frozen=True)
class SyntheticStaff:
    id: str
    role: str  # "transporter" | "respiratory_therapist" | "iv_nurse"
    start_place_id: str
    shift_start: datetime
    shift_end: datetime


@dataclass(frozen=True)
class SyntheticJob:
    id: str
    kind: str
    pickup_place_id: str
    dropoff_place_id: str | None
    earliest: datetime | None
    latest: datetime | None
    service_minutes: int
    priority: int
    status: str = "new"


@dataclass(frozen=True)
class Scenario:
    seed: int
    label: str
    shift_start: datetime
    shift_end: datetime
    staff: tuple[SyntheticStaff, ...]
    jobs: tuple[SyntheticJob, ...]


def _place_by_name(places: dict[str, Place], name: str) -> Place:
    # Names can repeat; pick the lowest id so the choice is stable.
    matches = sorted((p for p in places.values() if p.name == name), key=lambda p: p.id)
    if not matches:
        raise ValueError(f"building has no place named {name!r}")
    return matches[0]


def generate_scenario(graph: NavGraph, seed: int = 0, day: date = date(2026, 11, 15),
                      staff_per_role: int = 2, rt_jobs: int = 9, iv_jobs: int = 8,
                      transport_jobs: int = 6) -> Scenario:
    rng = random.Random(seed)
    places = graph.places
    rooms = sorted((p for p in places.values() if PATIENT_ROOM.match(p.name)), key=lambda p: p.id)
    if not rooms:
        raise ValueError("building has no patient rooms matching 'Room N' / 'Assessment Room N'")
    clinician_start = _place_by_name(places, CLINICIAN_START)
    transporter_start = _place_by_name(places, TRANSPORTER_START)
    destinations = [_place_by_name(places, n) for n in TRANSPORT_DESTINATIONS]

    start = datetime.combine(day, SHIFT_START)
    end = start + timedelta(hours=SHIFT_HOURS)

    def at(minutes: int) -> datetime:
        return start + timedelta(minutes=minutes)

    def priority() -> int:
        return rng.choices(list(_PRIORITY_WEIGHTS), weights=list(_PRIORITY_WEIGHTS.values()))[0]

    staff: list[SyntheticStaff] = []
    for role, code, place in (("respiratory_therapist", "RT", clinician_start),
                              ("iv_nurse", "IV", clinician_start),
                              ("transporter", "TR", transporter_start)):
        staff += [SyntheticStaff(f"SYN-{code}-{i}", role, place.id, start, end) for i in range(1, staff_per_role + 1)]

    jobs: list[SyntheticJob] = []

    def add(kind, pickup, dropoff, earliest, latest):
        jobs.append(SyntheticJob(f"SYN-J-{len(jobs) + 1:03d}", kind, pickup.id, dropoff.id if dropoff else None,
                                 earliest, latest, SERVICE_MINUTES[kind], priority()))

    shift_min = SHIFT_HOURS * 60
    for _ in range(rt_jobs):
        # Scheduled treatment: due at a 15-min slot, may be given 30 min either side.
        due = rng.randrange(30, shift_min - 60, 15)
        add(rng.choice(["breathing_treatment", "breathing_treatment", "ventilator_check"]),
            rng.choice(rooms), None, at(due - 30), at(due + 30))
    for _ in range(iv_jobs):
        # Consult: any time from the start of the shift, needed by a deadline (e.g. before meds/procedure).
        add(rng.choice(["iv_start", "iv_start", "line_placement"]),
            rng.choice(rooms), None, None, at(rng.randrange(60, shift_min - 60, 15)))
    for _ in range(transport_jobs):
        # Patient ready at `earliest`; must arrive at the destination within 30-60 min.
        ready = rng.randrange(0, shift_min - 90, 15)
        room = rng.choice(rooms)
        dest = rng.choice([d for d in destinations if d.id != room.id])
        add("transport", room, dest, at(ready), at(ready + rng.choice([30, 45, 60])))

    label = (f"SYNTHETIC scenario (seed={seed}): generated staff and jobs, not real patients or staff. "
             f"Places are real labels from Matterport model {graph.source.get('model_id', 'unknown')}.")
    return Scenario(seed, label, start, end, tuple(staff), tuple(jobs))
