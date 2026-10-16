"""Reading data_library's green layer, read-only and honest-empty.

The app is a SPOKE: it never fetches a source and never writes green. It finds its sources by
looking, not by a list: every folder under <root>/ext_data/green whose parquet carries the
bushfire contract's standard columns is a bushfire source, so a new state's pipeline appears
here the day the hub writes its green. A source outside the contract is read through a named
adapter (only NASA FIRMS hotspots today).

Every outcome is named, never an empty list that could mean anything:
  no_data_mounted   the data root is not a directory on this machine
  no_green          the root is there but holds no ext_data/green
  no_sources        green is there but no folder in it is a bushfire source
  per source:  read (n rows) | not_read (why: no parquet engine, unreadable, missing columns)
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from .records import STANDARD_COLUMNS, Record, iso, record_from_row, to_utc

NO_DATA_MOUNTED, NO_GREEN, NO_SOURCES, OK = "no_data_mounted", "no_green", "no_sources", "ok"
READ, NOT_READ = "read", "not_read"

# A green folder name is a plain source name; anything else is never joined into a path.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def safe_name(name: str) -> bool:
    return bool(_SAFE_NAME.match(name or ""))


class ParquetUnavailable(RuntimeError):
    """pyarrow is not installed, so no green can be read on this machine."""


def _pq():
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:
        raise ParquetUnavailable(f"pyarrow is not installed here, so no green can be read "
                                 f"({exc})") from exc
    return pq


def parquet_files(folder: str) -> List[str]:
    out = []
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")))
        out.extend(os.path.join(dirpath, f) for f in sorted(files) if f.endswith(".parquet"))
    return out


# ── hotspot adapters: sources outside the contract ───────────────────────────────────────────

# Australia's extent for filtering a WORLDWIDE feed: the mainland, Tasmania and the Torres
# Strait islands (Natural Earth extents, rounded outwards). FIRMS leaves country blank on
# purpose (data_library Nasa_Firms.business_rules), so the app must place a detection itself.
AUS_BBOX = (112.0, -44.5, 154.5, -9.0)
# Inside that box but not Australia: Timor and the Lesser Sunda islands reach south to about
# 11 S west of 129.5 E, where no Australian land lies north of 11 S (Tiwi Islands are east of
# 130 E). REASONED from the map; PNG's south coast near Daru (about 9.1 S) can still leak in.
_NOT_AUS_WEST_OF_LON, _NOT_AUS_NORTH_OF_LAT = 129.5, -10.95


def in_australia(lon: float, lat: float) -> bool:
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return False
    min_lon, min_lat, max_lon, max_lat = AUS_BBOX
    if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
        return False
    return not (lon < _NOT_AUS_WEST_OF_LON and lat > _NOT_AUS_NORTH_OF_LAT)


FIRMS_COLUMNS = ("detection_key", "latitude", "longitude", "acq_datetime_utc", "scan_km",
                 "track_km", "confidence_band", "frp_mw", "satellite", "rec_vld_dts")
FIRMS_AGENCY = "NASA FIRMS (VIIRS)"


def firms_records(rows: List[dict], source_name: str) -> List[Record]:
    """NASA FIRMS green rows (data_library pipelines/Nasa_Firms.py COL_TYPES) -> hotspot Records.

    Derived from FIRMS's own columns, never invented: the point is its latitude/longitude, the
    time its acquisition instant, and the precision half the pixel's diagonal (scan x track km).
    A hotspot is national (AUS): FIRMS does not say which state a pixel is in."""
    out = []
    for row in rows:
        lon, lat = row.get("longitude"), row.get("latitude")
        try:
            lon, lat = float(lon), float(lat)
        except (TypeError, ValueError):
            continue
        if not in_australia(lon, lat):
            continue
        when = to_utc(row.get("acq_datetime_utc")) or to_utc(row.get("rec_vld_dts"))
        try:
            precision = math.hypot(float(row.get("scan_km")), float(row.get("track_km"))) * 500.0
        except (TypeError, ValueError):
            precision = math.nan
        rec = record_from_row({
            "source_name": source_name, "jurisdiction": "AUS", "source_agency": FIRMS_AGENCY,
            "source_record_id": row.get("detection_key"), "record_kind": "hotspot",
            "geom_type": "point", "lon": lon, "lat": lat,
            "bbox_min_lon": lon, "bbox_min_lat": lat, "bbox_max_lon": lon, "bbox_max_lat": lat,
            "loc_precision_m": precision, "time_start_utc": when, "time_end_utc": when,
            "warning_level": "none", "warning_level_source": "",
            "status": "unknown", "incident_type": "unknown",
            "rec_vld_dts": row.get("rec_vld_dts") or when,
        })
        out.append(rec)
    return out


@dataclass(frozen=True)
class Adapter:
    columns: Tuple[str, ...]
    to_records: Callable[[List[dict], str], List[Record]]
    # Partition folder key holding a date (key=YYYY-MM-DD): lets a read skip days outside the window.
    date_partition: str = ""


ADAPTERS: Dict[str, Adapter] = {
    "Nasa_Firms": Adapter(FIRMS_COLUMNS, firms_records, date_partition="acq_date"),
}


# ── finding and reading sources ─────────────────────────────────────────────────────────────

@dataclass
class SourceStatus:
    source_name: str
    kind: str                      # "standard" (the contract) | "hotspot" (an adapter)
    state: str = READ
    rows: int = 0
    note: str = ""
    folder: str = field(default="", repr=False)
    latest: Optional[datetime] = None      # the newest record time this source holds

    def to_dict(self) -> dict:
        return {"source_name": self.source_name, "kind": self.kind, "state": self.state,
                "rows": self.rows, "note": self.note, "latest_utc": iso(self.latest)}


@dataclass
class GreenRead:
    state: str
    message: str
    sources: List[SourceStatus]
    records: List[Record]


def _schema_names(path: str) -> List[str]:
    return list(_pq().read_schema(path).names)


def _in_date_window(path: str, key: str, start: datetime, end: datetime) -> bool:
    m = re.search(rf"(?:^|[\\/]){re.escape(key)}=(\d{{4}}-\d{{2}}-\d{{2}})(?:[\\/]|$)", path)
    if not m:
        return True                # not partitioned by day: read it, filter rows after
    try:
        day = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=start.tzinfo)
    except ValueError:
        return True
    return start - timedelta(days=1) <= day <= end + timedelta(days=1)


class GreenReader:
    """Finds the bushfire sources in green and reads them. Thread-safe; caches the folder scan
    for `scan_seconds` and each parquet file until its mtime or size changes."""

    def __init__(self, settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._scan: Optional[Tuple[float, List[SourceStatus]]] = None
        self._files: Dict[str, Tuple[Tuple[float, int], List[dict]]] = {}

    # The scan ---------------------------------------------------------------------------
    def discover(self) -> Tuple[str, str, List[SourceStatus]]:
        root, green = self.settings.data_root, self.settings.green_root
        if not os.path.isdir(root):
            return (NO_DATA_MOUNTED,
                    f"No data mounted: {root} is not a directory on this machine. Set "
                    f"EXTERNAL_DATA_ROOT to the data_library store (on Janet's box: /library).", [])
        if not os.path.isdir(green):
            return (NO_GREEN, f"The data root {root} is mounted but holds no ext_data/green, so "
                              f"no source has been published to it yet.", [])
        with self._lock:
            if self._scan and time.monotonic() - self._scan[0] < self.settings.scan_seconds:
                found = self._scan[1]
            else:
                found = self._scan_green(green)
                self._scan = (time.monotonic(), found)
        if not found:
            return (NO_SOURCES, f"Green is mounted at {green}, but no folder in it is a bushfire "
                                f"source yet (none carries the bushfire contract's columns).", [])
        return OK, "", [SourceStatus(s.source_name, s.kind, s.state, 0, s.note, s.folder)
                        for s in found]

    def _scan_green(self, green: str) -> List[SourceStatus]:
        wanted = set(self.settings.sources)
        found: List[SourceStatus] = []
        for name in sorted(os.listdir(green)):
            folder = os.path.join(green, name)
            if not os.path.isdir(folder) or not safe_name(name):
                continue
            if wanted and name not in wanted:
                continue
            adapter = ADAPTERS.get(name)
            files = parquet_files(folder)
            if not files:
                if wanted or adapter:
                    found.append(SourceStatus(name, "hotspot" if adapter else "standard",
                                              NOT_READ, 0, "no parquet in its green folder yet",
                                              folder))
                continue
            try:
                cols = set(_schema_names(files[0]))
            except ParquetUnavailable as exc:
                found.append(SourceStatus(name, "hotspot" if adapter else "standard",
                                          NOT_READ, 0, str(exc), folder))
                continue
            except (OSError, ValueError) as exc:
                if wanted or adapter:
                    found.append(SourceStatus(name, "hotspot" if adapter else "standard",
                                              NOT_READ, 0, f"unreadable: {exc}", folder))
                continue
            if adapter:
                missing = [c for c in adapter.columns if c not in cols]
                found.append(SourceStatus(name, "hotspot", NOT_READ if missing else READ, 0,
                                          f"missing columns: {', '.join(missing)}" if missing
                                          else "", folder))
            elif {"record_kind", "geom_type", "source_record_id"} <= cols:
                missing = [c for c in STANDARD_COLUMNS if c not in cols]
                found.append(SourceStatus(name, "standard", NOT_READ if missing else READ, 0,
                                          f"missing contract columns: {', '.join(missing)}"
                                          if missing else "", folder))
            elif wanted:
                found.append(SourceStatus(name, "standard", NOT_READ, 0,
                                          "named in BUSHFIRE_SOURCES but carries none of the "
                                          "bushfire contract's columns", folder))
        return found

    # The read ---------------------------------------------------------------------------
    def _rows(self, path: str, columns: Tuple[str, ...]) -> List[dict]:
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
        cached = self._files.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        pq = _pq()
        present = [c for c in columns if c in pq.read_schema(path).names]
        rows = pq.read_table(path, columns=present).to_pylist()
        self._files[path] = (stamp, rows)
        return rows

    def read(self, start: datetime, end: datetime, gap: timedelta) -> GreenRead:
        """Every bushfire record whose time window meets [start - gap, end + gap], plus every
        record with no time at all (so the caller can count them, honestly, as untimed)."""
        state, message, sources = self.discover()
        if state != OK:
            return GreenRead(state, message, sources, [])
        lo, hi = start - gap, end + gap
        records: List[Record] = []
        for src in sources:
            if src.state != READ:
                continue
            adapter = ADAPTERS.get(src.source_name)
            columns = adapter.columns if adapter else STANDARD_COLUMNS
            files = parquet_files(src.folder)
            if adapter and adapter.date_partition:
                files = [f for f in files if _in_date_window(f, adapter.date_partition, lo, hi)]
            rows: List[dict] = []
            failed: List[str] = []
            for f in files:
                try:
                    rows.extend(self._rows(f, columns))
                except ParquetUnavailable as exc:
                    failed = [str(exc)]
                    break
                except (OSError, ValueError) as exc:
                    failed.append(f"{os.path.basename(f)}: {exc}")
            if failed and not rows:
                src.state, src.note = NOT_READ, "; ".join(failed[:3])
                continue
            if failed:
                src.note = f"{len(failed)} of {len(files)} file(s) unreadable: {'; '.join(failed[:2])}"
            recs = (adapter.to_records(rows, src.source_name) if adapter
                    else [record_from_row(r) for r in rows])
            # One row per green key: a source folder that holds the union file and its
            # partitions must not double a record.
            seen = set()
            kept = []
            for r in recs:
                if r.key in seen:
                    continue
                seen.add(r.key)
                w = r.window
                if w is None or (w[0] <= hi and w[1] >= lo):
                    kept.append(r)
            src.rows = len(recs)
            ends = [w[1] for w in (r.window for r in recs) if w]
            src.latest = max(ends) if ends else None
            records.extend(kept)
        if all(s.state != READ for s in sources):
            return GreenRead("sources_unread", "Bushfire sources were found in green, but none "
                             "could be read: see each source's note.", sources, [])
        return GreenRead(OK, "", sources, records)
