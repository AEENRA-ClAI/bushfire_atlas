"""The linker: green records -> fire events, by place and time, never by agency id (D30).

Two records belong to the same fire when BOTH hold:
  * PLACE: their shapes come within `link_distance_m` of each other. A point's shape is a circle
    of its loc_precision_m, a circle record's is its radius, a polygon's is its bbox. So the
    reach grows with how imprecise each record is.
  * TIME: their time windows overlap, or come within `gap_hours` of each other.

Linking is transitive (a chain of linked records is one event), and every source record is
kept. An event's id is derived from its EARLIEST member's place and time, so it is stable for
the same data and never carries an agency's id.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from .geo import Box, Circle, SpatialIndex, gap_m
from .records import Record, iso
from .vocabulary import EVENT_KINDS, STATES, warning_rank


@dataclass(frozen=True)
class LinkParams:
    link_distance_m: float = 3000.0
    gap_hours: float = 24.0
    unknown_precision_m: float = 5000.0
    use_h3: bool = True


def shape_of(rec: Record, params: LinkParams):
    """The record's extent as a Circle or a Box; None when it cannot be placed."""
    if rec.is_box:
        return Box(*rec.bbox)
    if not rec.has_point:
        return None
    if rec.geom_type == "circle" and math.isfinite(rec.radius_m):
        r = rec.radius_m
    elif math.isfinite(rec.loc_precision_m):
        r = rec.loc_precision_m
    else:
        r = params.unknown_precision_m
    return Circle(rec.lon, rec.lat, r)


def times_meet(a: tuple, b: tuple, gap: timedelta) -> bool:
    return a[0] <= b[1] + gap and b[0] <= a[1] + gap


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


@dataclass
class Event:
    event_id: str
    members: List[Record]
    shapes: list = field(repr=False, default_factory=list)

    @property
    def first_seen(self) -> datetime:
        return min(m.window[0] for m in self.members)

    @property
    def last_seen(self) -> datetime:
        return max(m.window[1] for m in self.members)

    @property
    def jurisdictions(self) -> List[str]:
        return sorted({m.jurisdiction for m in self.members if m.jurisdiction})

    @property
    def states(self) -> List[str]:
        return [j for j in self.jurisdictions if j in STATES]

    @property
    def cross_border(self) -> bool:
        """Do the agencies of more than one state report this fire?"""
        return len(self.states) > 1

    @property
    def warning_level(self) -> str:
        return max((m.warning_level for m in self.members), key=warning_rank,
                   default="unknown")

    def latest_known(self, attr: str) -> str:
        """The most recent member's value for a controlled term, skipping 'unknown'."""
        known = [m for m in self.members if getattr(m, attr) not in ("", "unknown")]
        if not known:
            return "unknown"
        return getattr(max(known, key=lambda m: (m.window[1], m.key)), attr)

    def bbox(self) -> tuple:
        boxes = [s.bbox() for s in self.shapes]
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def summary(self) -> dict:
        b = self.bbox()
        sizes = [m.size_ha for m in self.members if math.isfinite(m.size_ha)]
        anchor = _anchor(self.members)
        return {
            "event_id": self.event_id,
            "lon": round((b[0] + b[2]) / 2, 5), "lat": round((b[1] + b[3]) / 2, 5),
            "bbox": [round(v, 5) for v in b],
            "anchor": {"lon": anchor.lon, "lat": anchor.lat} if anchor.has_point else None,
            "first_seen_utc": iso(self.first_seen), "last_seen_utc": iso(self.last_seen),
            "jurisdictions": self.jurisdictions,
            "cross_border": self.cross_border,
            "warning_level": self.warning_level,
            "status": self.latest_known("status"),
            "incident_type": self.latest_known("incident_type"),
            # Only a size an agency STATED; the largest, since sizes grow as a fire runs.
            "size_ha_stated": max(sizes) if sizes else None,
            "record_kinds": dict(sorted(Counter(m.record_kind for m in self.members).items())),
            "sources": sorted({m.source_name for m in self.members}),
            "member_count": len(self.members),
        }


def _anchor(members: Sequence[Record]) -> Record:
    """The earliest member: the event's id comes from it. Ties break on place, then row key."""
    return min(members, key=lambda m: (m.window[0], round(m.lat, 6) if m.has_point else 0.0,
                                      round(m.lon, 6) if m.has_point else 0.0, m.key))


def _id_for(anchor: Record, shape) -> str:
    """'20261016T0300Z_27.470S_153.020E': the earliest member's start time and place."""
    lon, lat = (anchor.lon, anchor.lat) if anchor.has_point else shape.centre()
    ns = "S" if lat < 0 else "N"
    ew = "W" if lon < 0 else "E"
    return f"{anchor.window[0]:%Y%m%dT%H%MZ}_{abs(lat):.3f}{ns}_{abs(lon):.3f}{ew}"


@dataclass
class LinkResult:
    events: List[Event]
    unplaced: List[Record]       # an event kind with no usable location
    untimed: List[Record]        # an event kind with no time at all
    not_events: List[Record]     # a fire-danger rating or a statistic: about an area, not a fire
    index_kind: str = "none"


def link(records: Sequence[Record], params: Optional[LinkParams] = None) -> LinkResult:
    params = params or LinkParams()
    gap = timedelta(hours=params.gap_hours)
    linkable: List[Record] = []
    shapes: list = []
    unplaced, untimed, not_events = [], [], []
    for rec in records:
        if rec.record_kind not in EVENT_KINDS:
            not_events.append(rec)
            continue
        shape = shape_of(rec, params)
        if shape is None:
            unplaced.append(rec)
            continue
        if rec.window is None:
            untimed.append(rec)
            continue
        linkable.append(rec)
        shapes.append(shape)

    index = SpatialIndex(params.link_distance_m, use_h3=params.use_h3)
    for s in shapes:
        index.add(s)
    windows = [r.window for r in linkable]
    uf = _UnionFind(len(linkable))
    # Sorted, so the same input always links in the same order (the result does not depend on
    # it, but a reader debugging one link can reproduce it).
    for a, b in sorted(index.candidate_pairs()):
        if uf.find(a) == uf.find(b):
            continue
        if not times_meet(windows[a], windows[b], gap):
            continue
        if gap_m(shapes[a], shapes[b]) <= params.link_distance_m:
            uf.union(a, b)

    groups: Dict[int, List[int]] = {}
    for i in range(len(linkable)):
        groups.setdefault(uf.find(i), []).append(i)

    events: List[Event] = []
    for idxs in groups.values():
        members = [linkable[i] for i in idxs]
        anchor = _anchor(members)
        events.append(Event(event_id=_id_for(anchor, shapes[idxs[members.index(anchor)]]),
                            members=sorted(members, key=lambda m: (m.window[0], m.key)),
                            shapes=[shapes[i] for i in idxs]))
    # Two events can share an anchor place and minute only if they are distinct fires that
    # started together within ~100 m; a suffix keeps their ids apart, in a stable order.
    events.sort(key=lambda e: (e.event_id, e.members[0].key))
    seen: Counter = Counter()
    for e in events:
        seen[e.event_id] += 1
        if seen[e.event_id] > 1:
            e.event_id = f"{e.event_id}-{seen[e.event_id]}"
    # Most serious first, then the most recently seen.
    events.sort(key=lambda e: (-warning_rank(e.warning_level), -e.last_seen.timestamp(),
                               e.event_id))
    return LinkResult(events=events, unplaced=unplaced, untimed=untimed, not_events=not_events,
                      index_kind=index.kind)
