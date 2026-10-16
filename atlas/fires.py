"""The /api/fires answer: read green for a time window, link it, filter the events.

Linking runs on every record in the window before any filter, so an event is always whole: a
filter chooses which events to show, it never cuts a record out of one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

from .green import OK, GreenReader
from .linker import Event, LinkParams, link
from .records import iso, to_utc
from .vocabulary import JURISDICTIONS, RECORD_KINDS, WARNING_LEVELS

MAX_WINDOW_HOURS = 24 * 366


class BadQuery(ValueError):
    """A query parameter the app cannot use; the message names it."""


@dataclass(frozen=True)
class Query:
    end: datetime
    hours: float
    jurisdictions: Tuple[str, ...] = ()
    levels: Tuple[str, ...] = ()
    kinds: Tuple[str, ...] = ()

    @property
    def start(self) -> datetime:
        return self.end - timedelta(hours=self.hours)


def _terms(raw: Optional[str], allowed: Iterable[str], name: str, upper=False) -> Tuple[str, ...]:
    if not raw:
        return ()
    allowed = tuple(allowed)
    out = []
    for t in raw.split(","):
        t = t.strip().upper() if upper else t.strip().lower()
        if not t:
            continue
        if t not in allowed:
            raise BadQuery(f"{name}={t!r} is not one of {', '.join(allowed)}")
        out.append(t)
    return tuple(dict.fromkeys(out))


def parse_query(args, default_hours: float, now: Optional[datetime] = None) -> Query:
    """Query from request args. The window ends at `end` (default: now) and spans `hours`."""
    now = now or datetime.now(timezone.utc)
    end = now
    if args.get("end"):
        end = to_utc(args.get("end"))
        if end is None:
            raise BadQuery(f"end={args.get('end')!r} is not an ISO date-time")
    hours = default_hours
    if args.get("hours"):
        try:
            hours = float(args.get("hours"))
        except ValueError as exc:
            raise BadQuery(f"hours={args.get('hours')!r} is not a number") from exc
        if not 0 < hours <= MAX_WINDOW_HOURS:
            raise BadQuery(f"hours must be between 0 and {MAX_WINDOW_HOURS}")
    return Query(end=end, hours=hours,
                 jurisdictions=_terms(args.get("jurisdiction"), JURISDICTIONS, "jurisdiction",
                                      upper=True),
                 levels=_terms(args.get("level"), WARNING_LEVELS, "level"),
                 kinds=_terms(args.get("kind"), RECORD_KINDS, "kind"))


def _matches(event: Event, q: Query) -> bool:
    if not (event.first_seen <= q.end and event.last_seen >= q.start):
        return False
    if q.jurisdictions and not set(q.jurisdictions) & set(event.jurisdictions):
        return False
    if q.levels and event.warning_level not in q.levels:
        return False
    if q.kinds and not {m.record_kind for m in event.members} & set(q.kinds):
        return False
    return True


def params_from(settings) -> LinkParams:
    return LinkParams(link_distance_m=settings.link_distance_m,
                      gap_hours=settings.link_gap_hours,
                      unknown_precision_m=settings.unknown_precision_m)


class FireService:
    def __init__(self, settings, reader: Optional[GreenReader] = None):
        self.settings = settings
        self.reader = reader or GreenReader(settings)

    def _linked(self, q: Query):
        params = params_from(self.settings)
        green = self.reader.read(q.start, q.end, timedelta(hours=params.gap_hours))
        result = link(green.records, params) if green.state == OK else None
        return green, result, params

    def fires(self, q: Query) -> dict:
        green, result, params = self._linked(q)
        body = {
            "state": green.state,
            "message": green.message,
            "data_root": self.settings.data_root,
            "window": {"start_utc": iso(q.start), "end_utc": iso(q.end), "hours": q.hours},
            "filters": {"jurisdiction": list(q.jurisdictions), "level": list(q.levels),
                        "kind": list(q.kinds)},
            "link": {"distance_m": params.link_distance_m, "gap_hours": params.gap_hours,
                     "unknown_precision_m": params.unknown_precision_m,
                     "index": result.index_kind if result else "none"},
            "sources": [s.to_dict() for s in green.sources],
            "events": [],
            "counts": {},
        }
        if result is None:
            return body
        in_window = [e for e in result.events
                     if e.first_seen <= q.end and e.last_seen >= q.start]
        shown = [e for e in in_window if _matches(e, q)]
        body["events"] = [e.summary() for e in shown]
        body["counts"] = {
            "records_read": sum(s["rows"] for s in body["sources"]),
            "records_linked": sum(len(e.members) for e in result.events),
            "events_in_window": len(in_window),
            "events_shown": len(shown),
            "unplaced": len(result.unplaced),
            "untimed": len(result.untimed),
            "not_events": len(result.not_events),
        }
        latest = [s.latest for s in green.sources if s.latest]
        body["latest_record_utc"] = iso(max(latest)) if latest else None
        body["message"] = _empty_message(body, in_window, shown)
        return body

    def event(self, event_id: str, q: Query, layers=None) -> Tuple[int, dict]:
        green, result, _ = self._linked(q)
        if result is None:
            return 404, {"state": green.state, "message": green.message}
        match = next((e for e in result.events if e.event_id == event_id), None)
        if match is None:
            return 404, {"state": "not_in_window",
                         "message": f"No event {event_id} among the records between "
                                    f"{iso(q.start)} and {iso(q.end)}. An event id comes from "
                                    f"its earliest record, so a window that starts later can "
                                    f"give the same fire a later id."}
        features, notes = layers.features_for(match.members) if layers else ([], {})
        return 200, {"state": OK, "event": match.summary(),
                     "members": [m.provenance() for m in match.members],
                     "geometry": {"type": "FeatureCollection", "features": features},
                     "geometry_notes": notes}


def _empty_message(body: dict, in_window: List[Event], shown: List[Event]) -> str:
    """Name WHICH empty it is: nothing read, nothing in the window, or everything filtered out."""
    if shown:
        return ""
    unread = [s["source_name"] for s in body["sources"] if s["state"] != "read"]
    tail = f" Not read: {', '.join(unread)}." if unread else ""
    if body["counts"]["records_read"] == 0:
        return ("No fires: every bushfire source in green was read and holds no records." + tail)
    if not in_window:
        latest = body.get("latest_record_utc") or "unknown"
        return (f"No fires in this window: {body['counts']['records_read']} records were read, "
                f"none between {body['window']['start_utc']} and {body['window']['end_utc']} "
                f"(the newest record is from {latest})." + tail)
    return (f"No fires match these filters: {len(in_window)} event(s) are in this window, "
            f"none with the chosen jurisdiction, warning level or record kind." + tail)
