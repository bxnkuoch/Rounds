"""Navigation graph built from a Matterport model export.

Input: the JSON written by tools/matterport_export (schema_version 1), with
z-up coordinates in meters. Nodes are Matterport scan points ("sweeps") and
edges are Matterport's sweep-to-sweep navigation links.

Edges are line-of-sight links between scan positions, not surveyed walking
paths. Weights are straight-line distances between the sweeps' floor
positions. Treat route lengths as approximate walking distances.

Everything here is deterministic. Routes and distances for the optimizer come
from this module, never from the LLM.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SCHEMA = 1
# Height above/below room bounds still counted as "in the room" (scan floor noise).
ROOM_Z_TOLERANCE_M = 0.5


class NoPathError(Exception):
    """Raised when two nodes are in disconnected parts of the graph."""


@dataclass(frozen=True)
class Node:
    id: str
    floor_id: str | None
    floor_sequence: int | None
    x: float
    y: float
    z: float
    room_id: str | None = None


@dataclass(frozen=True)
class Room:
    id: str
    label: str | None
    floor_id: str | None
    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]

    @property
    def footprint_area(self) -> float:
        return (self.max_xyz[0] - self.min_xyz[0]) * (self.max_xyz[1] - self.min_xyz[1])

    def contains(self, x: float, y: float, z: float) -> bool:
        (x0, y0, z0), (x1, y1, z1) = self.min_xyz, self.max_xyz
        return (x0 <= x <= x1 and y0 <= y <= y1
                and z0 - ROOM_Z_TOLERANCE_M <= z <= z1 + ROOM_Z_TOLERANCE_M)


@dataclass(frozen=True)
class Floor:
    id: str
    sequence: int
    name: str | None


@dataclass
class NavGraph:
    nodes: dict[str, Node]
    adjacency: dict[str, dict[str, float]]
    rooms: dict[str, Room] = field(default_factory=dict)
    floors: dict[str, Floor] = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    # sweep id -> reason it was not added as a node (reported, never silent)
    dropped: dict[str, str] = field(default_factory=dict)

    # ---- queries -----------------------------------------------------------

    def edge_length(self, a: str, b: str) -> float | None:
        return self.adjacency.get(a, {}).get(b)

    def nodes_in_room(self, room_id: str) -> list[str]:
        return sorted(n.id for n in self.nodes.values() if n.room_id == room_id)

    def nearest_node(self, x: float, y: float, floor_id: str | None = None) -> str:
        candidates = [n for n in self.nodes.values() if floor_id is None or n.floor_id == floor_id]
        if not candidates:
            raise KeyError(f"no nodes on floor {floor_id!r}")
        return min(candidates, key=lambda n: (math.hypot(n.x - x, n.y - y), n.id)).id

    def components(self) -> list[list[str]]:
        """Connected components, largest first."""
        seen: set[str] = set()
        comps: list[list[str]] = []
        for start in sorted(self.nodes):
            if start in seen:
                continue
            stack, comp = [start], []
            seen.add(start)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nxt in self.adjacency[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            comps.append(sorted(comp))
        return sorted(comps, key=lambda c: (-len(c), c[0]))

    # ---- routing -----------------------------------------------------------

    def _dist(self, a: str, b: str) -> float:
        na, nb = self.nodes[a], self.nodes[b]
        return math.dist((na.x, na.y, na.z), (nb.x, nb.y, nb.z))

    def shortest_path(self, start: str, goal: str) -> tuple[float, list[str]]:
        """A* over the graph. The heuristic is straight-line distance, which
        is admissible because every edge weight is a straight-line distance."""
        for n in (start, goal):
            if n not in self.nodes:
                raise KeyError(f"unknown node {n!r}")
        if start == goal:
            return 0.0, [start]

        g = {start: 0.0}
        came: dict[str, str] = {}
        # (f, tie-break counter, node) keeps ordering deterministic
        counter = 0
        heap = [(self._dist(start, goal), counter, start)]
        closed: set[str] = set()
        while heap:
            _, _, cur = heapq.heappop(heap)
            if cur == goal:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                return g[goal], path[::-1]
            if cur in closed:
                continue
            closed.add(cur)
            for nxt, w in sorted(self.adjacency[cur].items()):
                cand = g[cur] + w
                if cand < g.get(nxt, math.inf):
                    g[nxt] = cand
                    came[nxt] = cur
                    counter += 1
                    heapq.heappush(heap, (cand + self._dist(nxt, goal), counter, nxt))
        raise NoPathError(f"no path from {start!r} to {goal!r}")

    def _dijkstra(self, start: str) -> dict[str, float]:
        dist = {start: 0.0}
        heap = [(0.0, start)]
        while heap:
            d, cur = heapq.heappop(heap)
            if d > dist[cur]:
                continue
            for nxt, w in self.adjacency[cur].items():
                nd = d + w
                if nd < dist.get(nxt, math.inf):
                    dist[nxt] = nd
                    heapq.heappush(heap, (nd, nxt))
        return dist

    def distance_matrix(self, ids: list[str]) -> list[list[float]]:
        """Shortest-path distances (meters) between the given nodes, for the
        optimizer. Unreachable pairs are math.inf so callers must flag them."""
        for n in ids:
            if n not in self.nodes:
                raise KeyError(f"unknown node {n!r}")
        rows = []
        for a in ids:
            d = self._dijkstra(a)
            rows.append([d.get(b, math.inf) for b in ids])
        return rows


# ---- loading ---------------------------------------------------------------

def _xyz(v: dict | None) -> tuple[float, float, float] | None:
    if not v:
        return None
    return float(v["x"]), float(v["y"]), float(v["z"])


def _drop_reason(s: dict) -> str | None:
    if not s.get("enabled", True):
        return "disabled"
    if s.get("placement") == "unplaced":
        return "unplaced"
    if _xyz(s.get("floor_position")) is None:
        return "no_position"
    return None


def load_nav_graph(path: str | Path) -> NavGraph:
    doc = json.loads(Path(path).read_text())
    version = doc.get("schema_version")
    if version != SUPPORTED_SCHEMA:
        raise ValueError(f"unsupported schema_version {version!r} (expected {SUPPORTED_SCHEMA})")

    floors = {f["id"]: Floor(f["id"], int(f["sequence"]), f.get("name")) for f in doc.get("floors", [])}
    rooms: dict[str, Room] = {}
    for r in doc.get("rooms", []):
        b = r.get("bounds")
        if not b:
            continue
        rooms[r["id"]] = Room(r["id"], r.get("label"), r.get("floor_id"), _xyz(b["min"]), _xyz(b["max"]))

    dropped: dict[str, str] = {}
    raw_nodes: dict[str, Node] = {}
    for s in doc["sweeps"]:
        reason = _drop_reason(s)
        if reason:
            dropped[s["id"]] = reason
            continue
        x, y, z = _xyz(s["floor_position"])
        raw_nodes[s["id"]] = Node(s["id"], s.get("floor_id"), s.get("floor_sequence"), x, y, z)

    # Room assignment: smallest room footprint on the same floor that contains the node.
    nodes: dict[str, Node] = {}
    for n in raw_nodes.values():
        hits = [r for r in rooms.values() if r.floor_id == n.floor_id and r.contains(n.x, n.y, n.z)]
        room_id = min(hits, key=lambda r: (r.footprint_area, r.id)).id if hits else None
        nodes[n.id] = Node(n.id, n.floor_id, n.floor_sequence, n.x, n.y, n.z, room_id)

    # Undirected edges; links to dropped or unknown sweeps are ignored.
    adjacency: dict[str, dict[str, float]] = {nid: {} for nid in nodes}
    for s in doc["sweeps"]:
        a = s["id"]
        if a not in nodes:
            continue
        for b in s.get("neighbors", []):
            if b == a or b not in nodes:
                continue
            na, nb = nodes[a], nodes[b]
            w = math.dist((na.x, na.y, na.z), (nb.x, nb.y, nb.z))
            adjacency[a][b] = w
            adjacency[b][a] = w

    return NavGraph(nodes=nodes, adjacency=adjacency, rooms=rooms, floors=floors,
                    source=doc.get("source", {}), dropped=dropped)
