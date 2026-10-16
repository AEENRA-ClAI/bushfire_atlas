"""The controlled terms the app reads, as data_library's catalog/bushfire_vocabulary.json
defines them (schema bushfire_vocabulary/v1). The app never maps an agency's raw term: the hub
does that in green, and keeps the raw term beside it in *_source.
"""
from __future__ import annotations

# Highest first. The three Australian Warning System tiers, then Queensland's below-Advice
# "Information", then a record that is not a warning, then a raw term nobody has mapped.
WARNING_LEVELS = ("emergency_warning", "watch_and_act", "advice", "information", "none", "unknown")
WARNING_RANK = {level: len(WARNING_LEVELS) - i for i, level in enumerate(WARNING_LEVELS)}

STATUSES = ("going", "contained", "controlled", "patrolled", "safe", "out", "unknown")
INCIDENT_TYPES = ("bushfire", "grass_fire", "planned_burn", "structure_fire", "other", "unknown")
RECORD_KINDS = ("incident", "warning", "fire_history", "burnt_area", "severity", "hotspot",
                "fire_danger", "statistic")
JURISDICTIONS = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT", "AUS")
STATES = tuple(j for j in JURISDICTIONS if j != "AUS")

# Kinds that describe a fire on the ground and so are linked into events. A fire-danger
# rating or a statistic is about an area, not a fire, and is counted but never made an event.
EVENT_KINDS = ("incident", "warning", "fire_history", "burnt_area", "severity", "hotspot")

# geom_type values whose extent is the green bbox rather than a point or circle.
BOX_GEOMS = ("polygon", "multipolygon", "line", "raster_cell")


def warning_rank(level: str) -> int:
    """Rank of a controlled warning level; a term outside the vocabulary ranks as 'unknown'."""
    return WARNING_RANK.get(level or "unknown", WARNING_RANK["unknown"])
