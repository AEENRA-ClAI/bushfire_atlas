"""The linker on constructed records. All SIMULATED: no real fire is in these tests.

Each case is run twice: through the H3 index (when h3 is installed) and through the lat/lon
grid fallback, and both must give the same events.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from atlas import geo
from atlas.linker import LinkParams, link
from atlas.records import record_from_row

T0 = datetime(2026, 1, 4, 3, 0, tzinfo=timezone.utc)


def rec(source, sid, jur, kind, geom, lon=math.nan, lat=math.nan, hours=0.0, end_hours=None,
        radius=math.nan, bbox=None, precision=None, level="none", status="unknown", size=math.nan):
    if bbox is None and math.isfinite(lon):
        r = radius if geom == "circle" else 0.0
        dlat = (0 if math.isnan(r) else r) / 111_320
        bbox = (lon - dlat, lat - dlat, lon + dlat, lat + dlat)
    bbox = bbox or (math.nan,) * 4
    if precision is None:
        precision = radius if geom == "circle" else 0.0
    start = T0 + timedelta(hours=hours)
    return record_from_row({
        "source_name": source, "jurisdiction": jur, "source_agency": f"{jur} agency",
        "source_record_id": sid, "record_kind": kind, "geom_type": geom,
        "lon": lon, "lat": lat, "radius_m": radius,
        "bbox_min_lon": bbox[0], "bbox_min_lat": bbox[1],
        "bbox_max_lon": bbox[2], "bbox_max_lat": bbox[3],
        "loc_precision_m": precision, "time_start_utc": start,
        "time_end_utc": None if end_hours is None else T0 + timedelta(hours=end_hours),
        "warning_level": level, "status": status, "size_ha": size, "rec_vld_dts": start,
    })


@pytest.fixture(params=["h3", "grid"])
def params(request):
    if request.param == "h3" and geo._load_h3() is None:
        pytest.skip("h3 is not installed here; the grid run covers the linker")
    return LinkParams(use_h3=(request.param == "h3"))


def ids(result):
    return sorted(sorted(m.source_record_id for m in e.members) for e in result.events)


def test_nsw_point_and_vic_polygon_on_the_border_are_one_fire(params):
    # The Murray at Corryong: NSW reports a point just north of the river, VIC a burnt-area
    # polygon whose box reaches the river. Different agencies, different ids, one fire.
    nsw = rec("Fixture_Nsw", "NSW-123", "NSW", "incident", "point", lon=147.90, lat=-36.18,
              hours=0, precision=200.0, level="advice", status="going")
    vic = rec("Fixture_Vic", "VIC-ABC-9", "VIC", "warning", "polygon", lon=147.88, lat=-36.24,
              bbox=(147.82, -36.29, 147.94, -36.19), precision=6000.0, hours=2,
              level="watch_and_act", status="going")
    result = link([nsw, vic], params)
    assert ids(result) == [["NSW-123", "VIC-ABC-9"]]
    event = result.events[0]
    assert event.cross_border is True
    assert event.jurisdictions == ["NSW", "VIC"]
    assert event.warning_level == "watch_and_act"
    assert event.first_seen == T0 and event.last_seen == T0 + timedelta(hours=2)


def test_two_fires_30_km_apart_stay_two(params):
    a = rec("Qfd_BushfireAlert", "Q1", "QLD", "incident", "point", lon=151.95, lat=-28.55)
    # 0.27 degrees of latitude is about 30 km.
    b = rec("Qfd_BushfireAlert", "Q2", "QLD", "incident", "point", lon=151.95, lat=-28.82)
    assert geo.haversine_m(151.95, -28.55, 151.95, -28.82) == pytest.approx(30_000, rel=0.01)
    result = link([a, b], params)
    assert ids(result) == [["Q1"], ["Q2"]]
    assert all(not e.cross_border for e in result.events)


def test_tasmanian_10_km_circle_gathers_points_inside_it_and_not_beyond(params):
    # TAS reports a fire as a 10 km circle (a locality, not a point).
    circle = rec("Fixture_Tas", "TAS-1", "TAS", "incident", "circle", lon=146.80, lat=-41.80,
                 radius=10_000.0, level="advice")
    inside = rec("Nasa_Firms", "hot-1", "AUS", "hotspot", "point", lon=146.88, lat=-41.85,
                 hours=1, precision=265.0)          # about 8 km from the centre
    edge = rec("Nasa_Firms", "hot-2", "AUS", "hotspot", "point", lon=146.80, lat=-41.69,
               hours=1, precision=265.0)           # about 12 km: within 10 km + 3 km
    far = rec("Nasa_Firms", "hot-3", "AUS", "hotspot", "point", lon=146.80, lat=-41.60,
              hours=1, precision=265.0)            # about 22 km: a different fire
    result = link([circle, inside, edge, far], params)
    assert ids(result) == [["TAS-1", "hot-1", "hot-2"], ["hot-3"]]
    tas = next(e for e in result.events if len(e.members) == 3)
    assert tas.jurisdictions == ["AUS", "TAS"]
    assert tas.cross_border is False                 # AUS (a national feed) is not a state


def test_same_place_far_apart_in_time_is_two_fires(params):
    a = rec("Qfd_BushfireAlert", "Q1", "QLD", "incident", "point", lon=150.0, lat=-25.0, hours=0)
    b = rec("Qfd_BushfireAlert", "Q2", "QLD", "incident", "point", lon=150.0, lat=-25.0,
            hours=24 * 10)
    assert ids(link([a, b], params)) == [["Q1"], ["Q2"]]


def test_time_gap_is_configurable(params):
    a = rec("S", "A", "QLD", "incident", "point", lon=150.0, lat=-25.0, hours=0)
    b = rec("S", "B", "QLD", "incident", "point", lon=150.0, lat=-25.0, hours=30)
    assert ids(link([a, b], params)) == [["A"], ["B"]]                   # default gap 24 h
    wide = LinkParams(gap_hours=48, use_h3=params.use_h3)
    assert ids(link([a, b], wide)) == [["A", "B"]]


def test_open_ended_window_overlaps_a_later_record_within_its_span(params):
    a = rec("S", "A", "NSW", "incident", "point", lon=150.0, lat=-33.0, hours=0, end_hours=100)
    b = rec("S", "B", "NSW", "incident", "point", lon=150.0, lat=-33.0, hours=90)
    assert ids(link([a, b], params)) == [["A", "B"]]


def test_chain_links_transitively(params):
    # Three hotspots 2.5 km apart in a line: A-B and B-C link, so A and C are one fire.
    pts = [rec("Nasa_Firms", c, "AUS", "hotspot", "point", lon=150.0, lat=-30.0 - i * 0.0225)
           for i, c in enumerate("ABC")]
    assert ids(link(pts, params)) == [["A", "B", "C"]]


def test_unknown_precision_uses_the_configured_reach(params):
    a = rec("S", "A", "WA", "incident", "point", lon=116.0, lat=-31.0, precision=math.nan)
    b = rec("S", "B", "WA", "incident", "point", lon=116.0, lat=-31.07, precision=0.0)  # ~7.8 km
    assert ids(link([a, b], params)) == [["A", "B"]]       # 5 km reach + 3 km distance
    tight = LinkParams(unknown_precision_m=0.0, use_h3=params.use_h3)
    assert ids(link([a, b], tight)) == [["A"], ["B"]]


def test_big_polygon_beyond_the_index_still_links(params):
    # A 300 km burnt-area box is compared directly (too big to index); a point inside links.
    box = rec("Fixture_Ga", "GA-1", "NSW", "burnt_area", "polygon", lon=149.0, lat=-35.0,
              bbox=(147.5, -36.5, 150.5, -33.5), precision=200_000.0)
    pt = rec("S", "P", "NSW", "incident", "point", lon=149.9, lat=-34.1, hours=3)
    assert ids(link([box, pt], params)) == [["GA-1", "P"]]


def test_every_record_is_kept_and_sorted_into_its_place():
    placed = rec("S", "A", "QLD", "incident", "point", lon=150.0, lat=-25.0)
    nowhere = rec("S", "B", "QLD", "incident", "area_code")
    untimed = rec("S", "C", "QLD", "incident", "point", lon=150.0, lat=-25.0)
    untimed.time_start = untimed.rec_vld_dts = None
    danger = rec("S", "D", "QLD", "fire_danger", "point", lon=150.0, lat=-25.0)
    result = link([placed, nowhere, untimed, danger])
    assert ids(result) == [["A"]]
    assert [r.source_record_id for r in result.unplaced] == ["B"]
    assert [r.source_record_id for r in result.untimed] == ["C"]
    assert [r.source_record_id for r in result.not_events] == ["D"]


def test_event_id_comes_from_the_earliest_member_place_and_time_not_an_agency_id(params):
    early = rec("Fixture_Vic", "VIC-ZZZ", "VIC", "incident", "point", lon=147.9, lat=-36.2,
                hours=0)
    late = rec("Fixture_Nsw", "NSW-AAA", "NSW", "incident", "point", lon=147.91, lat=-36.2,
               hours=5)
    first = link([early, late], params).events[0].event_id
    assert first == "20260104T0300Z_36.200S_147.900E"
    assert "VIC" not in first and "NSW" not in first
    # Same records in another order, and the agency ids changed: the same id.
    early.source_record_id, late.source_record_id = "renamed-1", "renamed-2"
    assert link([late, early], params).events[0].event_id == first


def test_events_sharing_an_anchor_get_distinct_stable_ids(params):
    a = rec("S1", "A", "QLD", "incident", "point", lon=150.0, lat=-25.0)
    b = rec("S2", "B", "QLD", "incident", "point", lon=150.0001, lat=-25.0)
    # Same minute, same place to 3 decimals, but forced apart by a zero link distance.
    apart = LinkParams(link_distance_m=0.0, use_h3=params.use_h3)
    a.loc_precision_m = b.loc_precision_m = 0.0
    got = sorted(e.event_id for e in link([a, b], apart).events)
    assert got == ["20260104T0300Z_25.000S_150.000E", "20260104T0300Z_25.000S_150.000E-2"]
    assert got == sorted(e.event_id for e in link([b, a], apart).events)


def test_highest_warning_level_and_latest_status():
    a = rec("S", "A", "NSW", "warning", "point", lon=150.0, lat=-33.0, hours=0,
            level="emergency_warning", status="going")
    b = rec("S", "B", "NSW", "warning", "point", lon=150.0, lat=-33.0, hours=6,
            level="advice", status="contained")
    c = rec("S", "C", "NSW", "warning", "point", lon=150.0, lat=-33.0, hours=8,
            level="unknown", status="unknown")
    e = link([a, b, c]).events[0]
    assert e.warning_level == "emergency_warning"
    assert e.latest_known("status") == "contained"


def test_h3_and_grid_give_the_same_events_on_a_mixed_scene():
    if geo._load_h3() is None:
        pytest.skip("h3 is not installed here")
    scene = [
        rec("N", "n1", "NSW", "incident", "point", lon=147.90, lat=-36.18, precision=200.0),
        rec("V", "v1", "VIC", "warning", "polygon", lon=147.88, lat=-36.24,
            bbox=(147.82, -36.29, 147.94, -36.19), hours=1),
        rec("T", "t1", "TAS", "incident", "circle", lon=146.8, lat=-41.8, radius=10_000.0),
        rec("F", "f1", "AUS", "hotspot", "point", lon=146.88, lat=-41.85, precision=265.0),
        rec("F", "f2", "AUS", "hotspot", "point", lon=146.80, lat=-41.60, precision=265.0),
        rec("Q", "q1", "QLD", "incident", "point", lon=151.95, lat=-28.55),
        rec("Q", "q2", "QLD", "incident", "point", lon=151.95, lat=-28.82),
    ]
    by_h3 = link(scene, LinkParams(use_h3=True))
    by_grid = link(scene, LinkParams(use_h3=False))
    assert by_h3.index_kind == "h3" and by_grid.index_kind == "grid"
    assert ids(by_h3) == ids(by_grid)
    assert [e.event_id for e in by_h3.events] == [e.event_id for e in by_grid.events]
