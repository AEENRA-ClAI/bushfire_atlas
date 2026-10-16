"""Reading green and the routes, through the Flask app a real run uses. SIMULATED green
(scripts/make_fixture.py writes it); MEASURED in the sense that the real routes ran on it.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from app import create_app
from atlas import green as green_mod
from atlas.config import load_settings
from atlas.green import in_australia
from scripts.make_fixture import QFD, write_fixture

NOW = datetime(2026, 1, 10, 6, 0, tzinfo=timezone.utc)
END = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def settings_for(root, **kw):
    os.environ.pop("BUSHFIRE_SOURCES", None)
    s = load_settings()
    return replace(s, data_root=str(root), scan_seconds=0.0, **kw)


@pytest.fixture
def fixture_root(tmp_path):
    write_fixture(str(tmp_path), NOW)
    return tmp_path


@pytest.fixture
def client(fixture_root):
    return create_app(settings_for(fixture_root)).test_client()


def fires(client, **params):
    params.setdefault("end", END)
    r = client.get("/api/fires", query_string=params)
    return r.status_code, r.get_json()


# ── honest empty: four different sentences ──────────────────────────────────────────────

def test_no_data_mounted(tmp_path):
    c = create_app(settings_for(tmp_path / "absent")).test_client()
    status, body = fires(c)
    assert status == 200 and body["state"] == "no_data_mounted"
    assert "No data mounted" in body["message"] and body["events"] == []
    health = c.get("/healthz")
    assert health.status_code == 200
    assert health.get_json()["data_mounted"] is False


def test_mounted_without_green(tmp_path):
    status, body = fires(create_app(settings_for(tmp_path)).test_client())
    assert body["state"] == "no_green" and "no ext_data/green" in body["message"]


def test_green_without_a_bushfire_source(tmp_path):
    d = tmp_path / "ext_data" / "green" / "Fao_Prices" / "Prices"
    d.mkdir(parents=True)
    pd.DataFrame([{"country_iso3": "AUS", "value": 1.0}]).to_parquet(d / "x.parquet")
    status, body = fires(create_app(settings_for(tmp_path)).test_client())
    assert body["state"] == "no_sources" and body["sources"] == []


def test_no_fires_in_the_window_names_the_newest_record(client):
    status, body = fires(client, end="2025-06-01T00:00:00Z", hours=24)
    assert body["state"] == "ok" and body["events"] == []
    assert body["message"].startswith("No fires in this window")
    assert "newest record is from 2026-01-10" in body["message"]


def test_filtered_out_is_its_own_sentence(client):
    status, body = fires(client, jurisdiction="WA")
    assert body["events"] == [] and body["message"].startswith("No fires match these filters")


def test_an_unreadable_source_is_reported_not_dropped(fixture_root):
    bad = fixture_root / "ext_data" / "green" / QFD / "BushfireAlert" / "zz_broken.parquet"
    bad.write_bytes(b"not a parquet file")
    status, body = fires(create_app(settings_for(fixture_root)).test_client())
    qfd = next(s for s in body["sources"] if s["source_name"] == QFD)
    assert qfd["state"] == "read" and "unreadable" in qfd["note"]


def test_a_contract_source_missing_columns_is_not_read(tmp_path):
    d = tmp_path / "ext_data" / "green" / "Fixture_Half" / "Half"
    d.mkdir(parents=True)
    pd.DataFrame([{"source_name": "Fixture_Half", "record_kind": "incident",
                   "geom_type": "point", "source_record_id": "1"}]).to_parquet(d / "x.parquet")
    status, body = fires(create_app(settings_for(tmp_path)).test_client())
    assert body["state"] == "sources_unread"
    assert "missing contract columns" in body["sources"][0]["note"]


def test_without_pyarrow_every_source_says_why(fixture_root, monkeypatch):
    def no_pyarrow():
        raise green_mod.ParquetUnavailable("pyarrow is not installed here, so no green can be read")
    monkeypatch.setattr(green_mod, "_pq", no_pyarrow)
    status, body = fires(create_app(settings_for(fixture_root)).test_client())
    assert body["state"] == "sources_unread"
    assert all("pyarrow is not installed" in s["note"] for s in body["sources"])


# ── the fixture's fires ─────────────────────────────────────────────────────────────────

def test_discovery_finds_every_contract_source_and_firms_and_skips_the_rest(client):
    status, body = fires(client)
    names = {s["source_name"]: s for s in body["sources"]}
    assert set(names) == {QFD, "Fixture_NswIncidents", "Nasa_Firms"}
    assert names["Nasa_Firms"]["kind"] == "hotspot"
    # Timor and California detections are not Australia.
    assert names["Nasa_Firms"]["rows"] == 3


def test_the_border_fire_is_one_cross_border_event(client):
    status, body = fires(client)
    assert status == 200 and body["state"] == "ok"
    border = [e for e in body["events"] if e["cross_border"]]
    assert len(border) == 1
    e = border[0]
    assert e["jurisdictions"] == ["AUS", "NSW", "QLD"]
    assert e["warning_level"] == "watch_and_act"
    assert e["record_kinds"] == {"hotspot": 2, "incident": 2, "warning": 1}
    assert e["size_ha_stated"] == 1450.0
    # The fire 30 km away and the western grass fire are their own events.
    assert body["counts"]["events_shown"] == 3


def test_filters_choose_events_without_cutting_them(client):
    _, body = fires(client, kind="hotspot", level="watch_and_act")
    assert len(body["events"]) == 1 and body["events"][0]["member_count"] == 5
    _, body = fires(client, jurisdiction="NSW")
    assert [e["cross_border"] for e in body["events"]] == [True]


def test_bad_query_is_refused_with_its_name(client):
    r = client.get("/api/fires", query_string={"level": "red"})
    assert r.status_code == 400 and "level='red'" in r.get_json()["message"]


def test_event_detail_lists_every_record_with_its_agency_id_and_shape(client):
    _, body = fires(client)
    border = next(e for e in body["events"] if e["cross_border"])
    r = client.get(f"/api/fires/{border['event_id']}", query_string={"end": END})
    assert r.status_code == 200
    d = r.get_json()
    ids = sorted(m["source_record_id"] for m in d["members"])
    assert "QFD-0001" in ids and "NSW-77" in ids and len(ids) == 5
    assert {m["source_agency"] for m in d["members"]} >= {"Queensland Fire Department",
                                                         "Fixture NSW agency"}
    # QFD-0001's polygon comes from map_layers, matched by its green row key.
    assert len(d["geometry"]["features"]) == 1
    assert d["geometry"]["features"][0]["geometry"]["type"] == "Polygon"
    assert not border["event_id"].count("QFD") and not border["event_id"].count("NSW")


def test_event_outside_the_window_is_named_not_found(client):
    r = client.get("/api/fires/20200101T0000Z_1.000S_1.000E", query_string={"end": END})
    assert r.status_code == 404 and r.get_json()["state"] == "not_in_window"


def test_explicit_source_list_limits_the_read(fixture_root):
    s = replace(settings_for(fixture_root), sources=(QFD,))
    _, body = fires(create_app(s).test_client())
    assert [x["source_name"] for x in body["sources"]] == [QFD]


def test_firms_day_partitions_outside_the_window_are_not_opened(fixture_root, monkeypatch):
    opened = []
    real = green_mod.GreenReader._rows

    def spy(self, path, columns):
        opened.append(path)
        return real(self, path, columns)
    monkeypatch.setattr(green_mod.GreenReader, "_rows", spy)
    fires(create_app(settings_for(fixture_root)).test_client(),
          end="2025-06-01T00:00:00Z", hours=24)
    assert not any("acq_date=" in p for p in opened)


@pytest.mark.parametrize("lon,lat,inside", [
    (151.2, -33.9, True),      # Sydney
    (147.3, -42.9, True),      # Hobart
    (130.8, -12.5, True),      # Darwin
    (130.9, -11.5, True),      # Tiwi Islands
    (125.6, -8.6, False),      # Dili
    (124.0, -10.2, False),     # Kupang, West Timor
    (174.8, -41.3, False),     # Wellington
    (float("nan"), -30.0, False),
])
def test_in_australia(lon, lat, inside):
    assert in_australia(lon, lat) is inside


# ── the page ────────────────────────────────────────────────────────────────────────────

def test_page_loads_only_its_own_assets(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "http://" not in html and "https://" not in html
    for path in ("vendor/map_kit/leaflet/leaflet.js", "vendor/map_kit/map_kit.js",
                 "vendor/table_kit/table_kit.js", "atlas.js"):
        assert path in html
        assert client.get("/static/" + path).status_code == 200
    assert html.count("<table") == html.count("data-table")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
