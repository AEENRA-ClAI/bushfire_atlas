"""A polygon member joins its map-layer feature on the hub's own row_key.

The hub's blue layer truncates rec_vld_dts to the day, so a key rebuilt from it misses the
feature (MEASURED on the first live Qfd_BushfireAlert green, 2026-10-16). The shape below is the
live one: `source|id|time to the second`."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from atlas.layers import LayerReader
from atlas.records import record_from_row

HUB_KEY = "Qfd_BushfireAlert|WARN-11599|2026-10-16T04:37:49Z"


def _row(**kw):
    row = {"source_name": "Qfd_BushfireAlert", "source_record_id": "WARN-11599",
           "record_kind": "warning", "geom_type": "polygon", "jurisdiction": "QLD",
           "rec_vld_dts": datetime(2026, 10, 16, tzinfo=timezone.utc)}   # truncated to the day
    row.update(kw)
    return row


def _reader(tmp_path):
    layer = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"row_key": HUB_KEY},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[142.3, -10.9], [142.4, -10.9], [142.4, -10.8], [142.3, -10.9]]]}}]}
    (tmp_path / "Qfd_BushfireAlert.geojson").write_text(json.dumps(layer))
    return LayerReader(SimpleNamespace(map_layers_root=str(tmp_path)))


def test_hub_row_key_finds_the_shape(tmp_path):
    rec = record_from_row(_row(row_key=HUB_KEY))
    assert rec.key == HUB_KEY
    features, notes = _reader(tmp_path).features_for([rec])
    assert len(features) == 1 and notes == {}


def test_without_row_key_a_day_stamp_misses_and_says_so(tmp_path):
    features, notes = _reader(tmp_path).features_for([record_from_row(_row())])
    assert features == []
    assert "bbox is shown" in notes["Qfd_BushfireAlert"]
