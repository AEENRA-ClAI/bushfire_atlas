"""One source record, as the linker sees it.

A green row of any bushfire source becomes a `Record`. The agency's own id rides along as
PROVENANCE (`source_record_id`) and is never compared with another record's id: records are
linked by place and time only (data_library D30).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .vocabulary import BOX_GEOMS

# The contract's standard columns (data_library bushfire green contract). A green source that
# carries all of these is read with no app change; one missing any is reported as not read.
STANDARD_COLUMNS = (
    "source_name", "jurisdiction", "country_iso3", "source_agency", "source_record_id",
    "record_kind", "geom_type", "lon", "lat", "radius_m",
    "bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat", "h3_r7", "loc_precision_m",
    "time_start_utc", "time_end_utc", "warning_level", "warning_level_source", "status",
    "status_source", "incident_type", "incident_type_source", "size_ha", "rec_vld_dts",
)


def _num(value: Any) -> float:
    """A float, or NaN for a blank / None / non-number. Never 0 for a missing value."""
    if value is None:
        return math.nan
    try:
        f = float(value)
    except (TypeError, ValueError):
        return math.nan
    return f if math.isfinite(f) else math.nan


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def to_utc(value: Any) -> Optional[datetime]:
    """A timezone-aware UTC datetime, or None for NaT / blank / unparseable.

    Green's datetime64[ns] columns are naive UTC; a pandas Timestamp, a datetime and an ISO
    string are all accepted so a hotspot adapter can hand over the source's own string."""
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):          # pandas Timestamp (NaT has no valid value)
        try:
            if value != value:                   # NaT
                return None
            value = value.to_pydatetime()
        except (ValueError, TypeError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(s)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def row_key(source_name: str, source_record_id: str, rec_vld_dts: Optional[datetime]) -> str:
    """The green row key the contract names for map_layers features:
    source_name + source_record_id + rec_vld_dts. UNVERIFIED: the hub's exact rendering is set by
    data_library pipelines/_bushfire_geo.py, which has not landed; layers.py matches loosely."""
    stamp = rec_vld_dts.strftime("%Y-%m-%dT%H:%M:%S") if rec_vld_dts else ""
    return f"{source_name}|{source_record_id}|{stamp}"


@dataclass
class Record:
    source_name: str
    jurisdiction: str
    source_agency: str
    source_record_id: str          # PROVENANCE ONLY, never a join key
    record_kind: str
    geom_type: str
    lon: float
    lat: float
    radius_m: float
    bbox: tuple                    # (min_lon, min_lat, max_lon, max_lat), NaNs when absent
    loc_precision_m: float
    time_start: Optional[datetime]
    time_end: Optional[datetime]
    warning_level: str
    warning_level_source: str
    status: str
    status_source: str
    incident_type: str
    incident_type_source: str
    size_ha: float
    rec_vld_dts: Optional[datetime]

    @property
    def key(self) -> str:
        return row_key(self.source_name, self.source_record_id, self.rec_vld_dts)

    @property
    def has_point(self) -> bool:
        return (math.isfinite(self.lon) and math.isfinite(self.lat)
                and -90 <= self.lat <= 90 and -180 <= self.lon <= 180)

    @property
    def has_box(self) -> bool:
        return all(math.isfinite(v) for v in self.bbox)

    @property
    def is_box(self) -> bool:
        """Is this record's extent its bbox (a polygon, line or raster cell)?"""
        return self.geom_type in BOX_GEOMS and self.has_box

    @property
    def placed(self) -> bool:
        """Can the record be put on the map at all?"""
        return self.is_box or self.has_point

    @property
    def window(self) -> Optional[tuple]:
        """(start, end) in UTC, or None when the source gave no time at all.

        Start is the source's own start, else its rec_vld_dts. An open end (NaT) is the last
        time the source vouched for the record: the later of start and rec_vld_dts."""
        start = self.time_start or self.rec_vld_dts
        if start is None:
            return None
        end = self.time_end
        if end is None:
            end = max(start, self.rec_vld_dts) if self.rec_vld_dts else start
        return (start, max(start, end))

    def provenance(self) -> dict:
        """Everything a person needs to find this record at its source."""
        return {
            "row_key": self.key,
            "source_name": self.source_name,
            "source_agency": self.source_agency,
            "source_record_id": self.source_record_id,
            "jurisdiction": self.jurisdiction,
            "record_kind": self.record_kind,
            "geom_type": self.geom_type,
            "lon": _json_num(self.lon), "lat": _json_num(self.lat),
            "radius_m": _json_num(self.radius_m),
            "bbox": [_json_num(v) for v in self.bbox] if self.has_box else None,
            "loc_precision_m": _json_num(self.loc_precision_m),
            "time_start_utc": iso(self.time_start), "time_end_utc": iso(self.time_end),
            "rec_vld_dts": iso(self.rec_vld_dts),
            "warning_level": self.warning_level, "warning_level_source": self.warning_level_source,
            "status": self.status, "status_source": self.status_source,
            "incident_type": self.incident_type, "incident_type_source": self.incident_type_source,
            "size_ha": _json_num(self.size_ha),
        }


def _json_num(v: float) -> Optional[float]:
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def record_from_row(row: Mapping[str, Any]) -> Record:
    """A green row in the contract's columns -> Record. Blank controlled terms read 'unknown'."""
    return Record(
        source_name=_text(row.get("source_name")),
        jurisdiction=_text(row.get("jurisdiction")).upper(),
        source_agency=_text(row.get("source_agency")),
        source_record_id=_text(row.get("source_record_id")),
        record_kind=_text(row.get("record_kind")).lower(),
        geom_type=_text(row.get("geom_type")).lower() or "none",
        lon=_num(row.get("lon")), lat=_num(row.get("lat")),
        radius_m=_num(row.get("radius_m")),
        bbox=(_num(row.get("bbox_min_lon")), _num(row.get("bbox_min_lat")),
              _num(row.get("bbox_max_lon")), _num(row.get("bbox_max_lat"))),
        loc_precision_m=_num(row.get("loc_precision_m")),
        time_start=to_utc(row.get("time_start_utc")),
        time_end=to_utc(row.get("time_end_utc")),
        warning_level=_text(row.get("warning_level")).lower() or "unknown",
        warning_level_source=_text(row.get("warning_level_source")),
        status=_text(row.get("status")).lower() or "unknown",
        status_source=_text(row.get("status_source")),
        incident_type=_text(row.get("incident_type")).lower() or "unknown",
        incident_type_source=_text(row.get("incident_type_source")),
        size_ha=_num(row.get("size_ha")),
        rec_vld_dts=to_utc(row.get("rec_vld_dts")),
    )
