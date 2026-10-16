"""Shapes, distances and the coarse spatial index the linker uses. Pure Python.

A record's extent is one of two shapes:
  * a CIRCLE: a point or a circle record. Its radius is radius_m for a circle, and the record's
    loc_precision_m for a point (0 for an exact point; the configured reach when unknown).
  * a BOX: a polygon, line or raster cell, as the contract's WGS84 bbox (full polygons live in
    map_layers, not green).

The coarse index only proposes candidate pairs; the exact `gap_m` decides. It is H3 (resolution
7, the contract's h3_r7 grid) when the `h3` package is installed, and a plain lat/lon grid when it
is not. Both are tested to give the same events.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Set, Tuple

EARTH_RADIUS_M = 6_371_008.8          # IUGG mean Earth radius
M_PER_DEG_LAT = 111_320.0             # metres per degree of latitude (WGS84, mid-latitude)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


class Circle:
    __slots__ = ("lon", "lat", "r")

    def __init__(self, lon: float, lat: float, r: float):
        self.lon, self.lat, self.r = lon, lat, max(0.0, r)

    def bbox(self) -> Tuple[float, float, float, float]:
        dlat = self.r / M_PER_DEG_LAT
        dlon = self.r / (M_PER_DEG_LAT * max(0.05, math.cos(math.radians(self.lat))))
        return (self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat)

    def centre(self) -> Tuple[float, float]:
        return (self.lon, self.lat)

    def reach_m(self) -> float:
        return self.r


class Box:
    __slots__ = ("min_lon", "min_lat", "max_lon", "max_lat")

    def __init__(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float):
        self.min_lon, self.max_lon = sorted((min_lon, max_lon))
        self.min_lat, self.max_lat = sorted((min_lat, max_lat))

    def bbox(self) -> Tuple[float, float, float, float]:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    def centre(self) -> Tuple[float, float]:
        return ((self.min_lon + self.max_lon) / 2, (self.min_lat + self.max_lat) / 2)

    def reach_m(self) -> float:
        """Centre to corner: every point of the box is within this distance of its centre."""
        c = self.centre()
        return haversine_m(c[0], c[1], self.max_lon, self.max_lat)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _box_box_gap_m(a: Box, b: Box) -> float:
    dlon = max(0.0, max(a.min_lon, b.min_lon) - min(a.max_lon, b.max_lon))
    dlat = max(0.0, max(a.min_lat, b.min_lat) - min(a.max_lat, b.max_lat))
    if dlon == 0.0 and dlat == 0.0:
        return 0.0
    # Nearest edges: measure along the latitude band the two boxes share (or are closest at).
    lat = _clamp((a.min_lat + a.max_lat + b.min_lat + b.max_lat) / 4,
                 max(min(a.min_lat, b.min_lat), -89.0), min(max(a.max_lat, b.max_lat), 89.0))
    return math.hypot(dlon * M_PER_DEG_LAT * math.cos(math.radians(lat)), dlat * M_PER_DEG_LAT)


def gap_m(a, b) -> float:
    """The distance between two shapes' nearest edges, in metres (0 when they touch or overlap)."""
    if isinstance(a, Circle) and isinstance(b, Circle):
        return max(0.0, haversine_m(a.lon, a.lat, b.lon, b.lat) - a.r - b.r)
    if isinstance(a, Box) and isinstance(b, Box):
        return _box_box_gap_m(a, b)
    circle, box = (a, b) if isinstance(a, Circle) else (b, a)
    nearest_lon = _clamp(circle.lon, box.min_lon, box.max_lon)
    nearest_lat = _clamp(circle.lat, box.min_lat, box.max_lat)
    return max(0.0, haversine_m(circle.lon, circle.lat, nearest_lon, nearest_lat) - circle.r)


# ── the coarse index ───────────────────────────────────────────────────────────────────────

# H3 resolution 7: the contract's h3_r7. Its average hexagon edge is 1.406 km (H3 resolution
# table), so neighbouring cell centres are about 2.4 km apart and a ring of k cells reaches at
# least k * 2.1 km (the inner radius). 2000 m per ring is used, which errs wide.
H3_RES = 7
H3_RING_M = 2000.0
# A footprint bigger than this many rings (100 km) is not indexed: the record is compared with
# every other record directly. Big burnt-area boxes are few; indexing them would cost thousands
# of cells each.
H3_MAX_K = 50

# The fallback grid: 0.05 degrees (about 5.5 km of latitude). A footprint over GRID_MAX_CELLS
# cells is compared directly, as above.
GRID_DEG = 0.05
GRID_MAX_CELLS = 2500


def _load_h3():
    """The h3 module, or None. Imported lazily: the app runs without it."""
    try:
        import h3  # type: ignore
    except ImportError:
        return None
    return h3 if hasattr(h3, "latlng_to_cell") else None   # the v4 API only


class SpatialIndex:
    """Proposes candidate pairs: two shapes whose footprints share a cell.

    A footprint is the shape grown by half the link distance, so two shapes within the link
    distance always share at least one cell (the cell holding the midpoint of their gap)."""

    def __init__(self, link_distance_m: float, use_h3: bool = True):
        self.half = link_distance_m / 2.0
        self.h3 = _load_h3() if use_h3 else None
        self.kind = "h3" if self.h3 else "grid"
        self.cells: Dict[object, List[int]] = defaultdict(list)
        self.wide: List[int] = []
        self.count = 0

    def _h3_cells(self, shape) -> Iterable:
        lon, lat = shape.centre()
        k = int(math.ceil((shape.reach_m() + self.half) / H3_RING_M)) + 1
        if k > H3_MAX_K:
            return None
        home = self.h3.latlng_to_cell(lat, lon, H3_RES)
        return self.h3.grid_disk(home, k)

    def _grid_cells(self, shape) -> Iterable:
        min_lon, min_lat, max_lon, max_lat = shape.bbox()
        lat_mid = (min_lat + max_lat) / 2
        dlat = self.half / M_PER_DEG_LAT
        dlon = self.half / (M_PER_DEG_LAT * max(0.05, math.cos(math.radians(lat_mid))))
        x0, x1 = math.floor((min_lon - dlon) / GRID_DEG), math.floor((max_lon + dlon) / GRID_DEG)
        y0, y1 = math.floor((min_lat - dlat) / GRID_DEG), math.floor((max_lat + dlat) / GRID_DEG)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > GRID_MAX_CELLS:
            return None
        return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    def add(self, shape) -> int:
        idx = self.count
        self.count += 1
        cells = self._h3_cells(shape) if self.h3 else self._grid_cells(shape)
        if cells is None:
            self.wide.append(idx)
        else:
            for c in cells:
                self.cells[c].append(idx)
        return idx

    def candidate_pairs(self) -> Set[Tuple[int, int]]:
        pairs: Set[Tuple[int, int]] = set()
        for members in self.cells.values():
            n = len(members)
            for i in range(n):
                a = members[i]
                for j in range(i + 1, n):
                    b = members[j]
                    pairs.add((a, b) if a < b else (b, a))
        for a in self.wide:
            for b in range(self.count):
                if a != b:
                    pairs.add((a, b) if a < b else (b, a))
        return pairs
