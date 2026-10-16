"""Every knob, read from the environment first, then a real baked default (fleet rule F4).

No secret is read here: the app needs none. Each default names where its value comes from.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# The hub's data root as Janet's container sees it: deploy/docker-compose.yml mounts the
# data_library store read-only at /library, and every library-backed app on the box reads
# EXTERNAL_DATA_ROOT=/library (janet_lite deploy/config/apps.example.yaml). Green is then
# <root>/ext_data/green/<Source>/... and polygons are <root>/map_layers/<source>.geojson.
DEFAULT_DATA_ROOT = "/library"

# 8624: the first port free in janet_lite's apps.example.yaml on 2026-10-16 (8622 is the
# health app, 8623 slumber), inside the 8611-8630 range Caddy serves over TLS at port + 100
# (janet_lite config.py), so https is 8724.
DEFAULT_PORT = 8624
DEFAULT_HOST = "127.0.0.1"

# Linker defaults. These are JUDGEMENTS, not measurements (needs_verification): they are the
# owner's to tune once real feeds are linked, and every one is an env var for that reason.
#   3000 m: two records whose shapes come within 3 km are one fire. A VIIRS hotspot pixel is
#           375 m across and a running fire front moves kilometres in hours, so tighter splits
#           one fire; two separate fires 30 km apart stay apart at this distance.
#   24 h:   two records whose time windows come within a day of each other can be one fire.
#   5000 m: the reach given to a point whose loc_precision_m is unknown (NaN). A point with an
#           unknown precision is treated as roughly locality-level rather than exact.
DEFAULT_LINK_DISTANCE_M = 3000.0
DEFAULT_LINK_GAP_HOURS = 24.0
DEFAULT_UNKNOWN_PRECISION_M = 5000.0
# The default view: events seen in the last 72 hours.
DEFAULT_WINDOW_HOURS = 72.0
# How long a scan of green for bushfire sources is reused before green is listed again.
DEFAULT_SCAN_SECONDS = 300.0


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name}={raw!r} is not a number") from exc


def _default_state_dir() -> str:
    # Outside the code checkout (a re-clone must not wipe state). Janet always sets
    # APP_STATE_DIR=/data/app_state/<id>/ (janet_lite CLAUDE.md rule 1); this is for a laptop run.
    return str(Path.home() / ".local" / "state" / "bushfire_atlas")


@dataclass(frozen=True)
class Settings:
    data_root: str
    host: str
    port: int
    state_dir: str
    link_distance_m: float
    link_gap_hours: float
    unknown_precision_m: float
    window_hours: float
    scan_seconds: float
    # Optional explicit list of green source names. Empty = discover every source in green
    # that carries the bushfire contract's columns, so a new state's pipeline needs no change here.
    sources: tuple

    @property
    def green_root(self) -> str:
        return os.path.join(self.data_root, "ext_data", "green")

    @property
    def map_layers_root(self) -> str:
        return os.path.join(self.data_root, "map_layers")


def load_settings() -> Settings:
    raw_sources = os.environ.get("BUSHFIRE_SOURCES", "")
    return Settings(
        data_root=os.environ.get("EXTERNAL_DATA_ROOT", "").strip() or DEFAULT_DATA_ROOT,
        host=os.environ.get("HOST", "").strip() or DEFAULT_HOST,
        port=int(_float("PORT", DEFAULT_PORT)),
        state_dir=os.environ.get("APP_STATE_DIR", "").strip() or _default_state_dir(),
        link_distance_m=_float("BUSHFIRE_LINK_DISTANCE_M", DEFAULT_LINK_DISTANCE_M),
        link_gap_hours=_float("BUSHFIRE_LINK_GAP_HOURS", DEFAULT_LINK_GAP_HOURS),
        unknown_precision_m=_float("BUSHFIRE_UNKNOWN_PRECISION_M", DEFAULT_UNKNOWN_PRECISION_M),
        window_hours=_float("BUSHFIRE_WINDOW_HOURS", DEFAULT_WINDOW_HOURS),
        scan_seconds=_float("BUSHFIRE_SCAN_SECONDS", DEFAULT_SCAN_SECONDS),
        sources=tuple(s.strip() for s in raw_sources.split(",") if s.strip()),
    )
