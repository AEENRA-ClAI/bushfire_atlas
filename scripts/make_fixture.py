"""Write a CONSTRUCTED green store for trying the app and for its tests. SIMULATED data.

Nothing here is a real fire. The rows are shaped like the bushfire green contract (Qfd-shaped,
plus a second contract source to show a new source drops in) and like NASA FIRMS green, dated
relative to `--now` so the default 72-hour window shows them.

    python scripts/make_fixture.py --root /tmp/atlas_fixture
    EXTERNAL_DATA_ROOT=/tmp/atlas_fixture python app.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone

import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from atlas.records import STANDARD_COLUMNS, row_key

QFD = "Qfd_BushfireAlert"
NSW = "Fixture_NswIncidents"      # a made-up second state source: proves no app change is needed
FIRMS = "Nasa_Firms"


def std_row(**kw) -> dict:
    """One contract row; geometry columns derived the way the contract defines them."""
    row = {c: None for c in STANDARD_COLUMNS}
    row.update(country_iso3="AUS", warning_level="none", warning_level_source="",
               status="unknown", status_source="", incident_type="bushfire",
               incident_type_source="", size_ha=math.nan, radius_m=math.nan,
               time_end_utc=pd.NaT, h3_r7="")
    row.update(kw)
    lon, lat = row["lon"], row["lat"]
    if row["geom_type"] in ("point", "circle"):
        r = row["radius_m"] if row["geom_type"] == "circle" else 0.0
        dlat = r / 111_320.0
        dlon = r / (111_320.0 * math.cos(math.radians(lat)))
        row.update(bbox_min_lon=lon - dlon, bbox_min_lat=lat - dlat,
                   bbox_max_lon=lon + dlon, bbox_max_lat=lat + dlat)
        if row.get("loc_precision_m") is None:
            row["loc_precision_m"] = r
    else:
        row["loc_precision_m"] = row.get("loc_precision_m") or 111_320.0 * math.hypot(
            (row["bbox_max_lon"] - row["bbox_min_lon"]) * math.cos(math.radians(lat)),
            row["bbox_max_lat"] - row["bbox_min_lat"]) / 2
    if row["rec_vld_dts"] is None:
        row["rec_vld_dts"] = row["time_start_utc"]
    return row


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def build(now: datetime) -> dict:
    t = lambda hours: _naive(now - timedelta(hours=hours))   # noqa: E731
    qfd = [
        # A fire near the QLD/NSW border (Tenterfield area), reported by both states.
        std_row(source_name=QFD, jurisdiction="QLD", source_agency="Queensland Fire Department",
                source_record_id="QFD-0001", record_kind="warning", geom_type="polygon",
                lon=151.95, lat=-28.55, bbox_min_lon=151.90, bbox_min_lat=-28.60,
                bbox_max_lon=152.00, bbox_max_lat=-28.50, time_start_utc=t(20),
                warning_level="watch_and_act", warning_level_source="Watch and Act",
                status="going", status_source="Going", size_ha=1450.0),
        std_row(source_name=QFD, jurisdiction="QLD", source_agency="Queensland Fire Department",
                source_record_id="QFD-0002", record_kind="incident", geom_type="point",
                lon=151.97, lat=-28.56, time_start_utc=t(22),
                warning_level="information", warning_level_source="Information",
                status="going", status_source="Going"),
        # A separate fire about 30 km north-east, same hours: must NOT join the one above.
        std_row(source_name=QFD, jurisdiction="QLD", source_agency="Queensland Fire Department",
                source_record_id="QFD-0003", record_kind="incident", geom_type="point",
                lon=152.20, lat=-28.35, time_start_utc=t(18),
                warning_level="advice", warning_level_source="Advice",
                status="contained", status_source="Contained"),
        # A western Queensland grass fire, alone.
        std_row(source_name=QFD, jurisdiction="QLD", source_agency="Queensland Fire Department",
                source_record_id="QFD-0004", record_kind="incident", geom_type="point",
                lon=146.25, lat=-23.45, time_start_utc=t(6), incident_type="grass_fire",
                incident_type_source="Grass Fire", warning_level="emergency_warning",
                warning_level_source="Emergency Warning", status="going", status_source="Going"),
        # Old enough to fall outside a 72-hour window.
        std_row(source_name=QFD, jurisdiction="QLD", source_agency="Queensland Fire Department",
                source_record_id="QFD-0005", record_kind="incident", geom_type="point",
                lon=153.0, lat=-27.5, time_start_utc=t(24 * 9), status="out", status_source="Out"),
    ]
    nsw = [
        std_row(source_name=NSW, jurisdiction="NSW", source_agency="Fixture NSW agency",
                source_record_id="NSW-77", record_kind="incident", geom_type="point",
                lon=151.99, lat=-28.62, loc_precision_m=500.0, time_start_utc=t(19),
                warning_level="advice", warning_level_source="Advice",
                status="going", status_source="Out of control"),
    ]
    firms = []
    for i, (lon, lat, h) in enumerate([(151.96, -28.57, 12), (151.94, -28.54, 9),
                                       (146.26, -23.44, 4),
                                       (125.0, -9.5, 5),      # Timor: not Australia
                                       (-120.0, 38.0, 5)]):   # California: not Australia
        when = now - timedelta(hours=h)
        firms.append({
            "detection_key": f"VIIRS_SNPP|{lat}|{lon}|{when:%Y%m%d%H%M}",
            "latitude": lat, "longitude": lon,
            "acq_date": f"{when:%Y-%m-%d}", "acq_time": f"{when:%H%M}",
            "acq_datetime_utc": f"{when:%Y-%m-%dT%H:%M:00Z}",
            "bright_ti4": 340.0, "bright_ti5": 290.0, "frp_mw": 12.5,
            "scan_km": 0.39, "track_km": 0.36, "confidence_raw": "n", "confidence_band": "nominal",
            "daynight": "D", "satellite": "N", "instrument": "VIIRS", "product_version": "2.0NRT",
            "firms_source": "VIIRS_SNPP_NRT", "source_url": "fixture", "country_iso3": "",
            "needs_verification": True, "status_flag": "A", "rec_vld_dts": _naive(when),
        })
    return {"qfd": qfd, "nsw": nsw, "firms": firms}


def _frame(rows):
    df = pd.DataFrame(rows)
    for c in ("time_start_utc", "time_end_utc", "rec_vld_dts"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def write_fixture(root: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    data = build(now)
    green = os.path.join(root, "ext_data", "green")
    for source, folder, rows in ((QFD, "BushfireAlert", data["qfd"]),
                                 (NSW, "Incidents", data["nsw"])):
        d = os.path.join(green, source, folder)
        os.makedirs(d, exist_ok=True)
        _frame(rows).to_parquet(os.path.join(d, f"{source}_{folder}.parquet"), index=False)
    by_day: dict = {}
    for r in data["firms"]:
        by_day.setdefault(r["acq_date"], []).append(r)
    for day, rows in by_day.items():
        d = os.path.join(green, FIRMS, FIRMS, f"acq_date={day}")
        os.makedirs(d, exist_ok=True)
        _frame(rows).to_parquet(os.path.join(d, "part-0.parquet"), index=False)
    # A green source that is not about fire: discovery must pass over it.
    other = os.path.join(green, "Fao_Prices", "Prices")
    os.makedirs(other, exist_ok=True)
    pd.DataFrame([{"country_iso3": "AUS", "value": 1.0}]).to_parquet(
        os.path.join(other, "Fao_Prices.parquet"), index=False)
    # The polygon of QFD-0001, keyed by its green row key.
    poly = data["qfd"][0]
    layers = os.path.join(root, "map_layers")
    os.makedirs(layers, exist_ok=True)
    ring = [[151.90, -28.55], [151.95, -28.60], [152.00, -28.55], [151.95, -28.50],
            [151.90, -28.55]]
    rk = row_key(QFD, poly["source_record_id"],
                 pd.Timestamp(poly["rec_vld_dts"]).to_pydatetime().replace(tzinfo=timezone.utc))
    with open(os.path.join(layers, f"{QFD}.geojson"), "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"row_key": rk},
             "geometry": {"type": "Polygon", "coordinates": [ring]}}]}, fh)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a constructed bushfire green store (SIMULATED).")
    ap.add_argument("--root", required=True, help="the data root to create (EXTERNAL_DATA_ROOT)")
    ap.add_argument("--now", default=None, help="ISO time the rows are dated back from (default: now)")
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    write_fixture(args.root, now)
    print(f"fixture written under {args.root}")


if __name__ == "__main__":
    main()
