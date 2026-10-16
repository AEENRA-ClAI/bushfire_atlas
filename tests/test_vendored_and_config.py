"""Offline-first and the knobs: the kits are the toolbox's checked-out copies, nothing the page
loads lives elsewhere, and every setting has a baked default an env var can override."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from atlas import config
from atlas.layers import _norm, key_variants
from atlas.records import record_from_row, row_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    """The lock's hash: toolbox scripts/checkout.py _sha256 (CRLF -> LF for text, raw binary)."""
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_kits_match_the_toolbox_checkout_lock():
    """A local edit to a checked-out kit is a pending deletion (toolbox CLAUDE.md): fail on it."""
    with open(os.path.join(ROOT, ".toolbox", "checkout.lock.json"), encoding="utf-8") as fh:
        lock = json.load(fh)
    checked = 0
    for name in ("map_kit", "table_kit"):
        bundle = lock["bundles"][name]
        assert bundle["path"] == f"static/vendor/{name}"
        for entry in bundle["files"]:
            path = os.path.join(ROOT, bundle["path"], entry["file"])
            assert os.path.isfile(path), f"{path} missing: run the toolbox checkout"
            assert _sha(path) == entry["sha256"], f"{path} edited here: edit it in the toolbox"
            checked += 1
    assert checked >= 5


def test_own_static_code_calls_nothing_outside_this_app():
    for name in ("atlas.js", "atlas.css"):
        with open(os.path.join(ROOT, "static", name), encoding="utf-8") as fh:
            text = fh.read()
        assert not re.search(r"https?://", text), f"{name} names an external address"
    with open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8") as fh:
        assert not re.search(r"https?://", fh.read())


def test_settings_have_baked_defaults(monkeypatch):
    for var in ("EXTERNAL_DATA_ROOT", "PORT", "HOST", "APP_STATE_DIR", "BUSHFIRE_SOURCES",
                "BUSHFIRE_LINK_DISTANCE_M", "BUSHFIRE_LINK_GAP_HOURS"):
        monkeypatch.delenv(var, raising=False)
    s = config.load_settings()
    assert s.data_root == "/library"
    assert s.green_root == os.path.join("/library", "ext_data", "green")
    assert s.map_layers_root == os.path.join("/library", "map_layers")
    assert s.port == 8622 and s.host == "127.0.0.1"
    assert s.state_dir.endswith(os.path.join(".local", "state", "bushfire_atlas"))
    assert (s.link_distance_m, s.link_gap_hours) == (3000.0, 24.0)
    assert s.sources == ()


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("EXTERNAL_DATA_ROOT", "/mnt/x")
    monkeypatch.setenv("PORT", "8640")
    monkeypatch.setenv("APP_STATE_DIR", "/data/app_state/bushfire-atlas")
    monkeypatch.setenv("BUSHFIRE_SOURCES", "Qfd_BushfireAlert, Nasa_Firms")
    monkeypatch.setenv("BUSHFIRE_LINK_DISTANCE_M", "1500")
    s = config.load_settings()
    assert (s.data_root, s.port, s.state_dir) == ("/mnt/x", 8640, "/data/app_state/bushfire-atlas")
    assert s.sources == ("Qfd_BushfireAlert", "Nasa_Firms")
    assert s.link_distance_m == 1500.0


def test_row_key_matches_common_renderings():
    t = datetime(2026, 1, 4, 3, 0, tzinfo=timezone.utc)
    rec = record_from_row({"source_name": "Qfd_BushfireAlert", "source_record_id": "QF-1",
                           "rec_vld_dts": t, "record_kind": "warning", "geom_type": "polygon"})
    variants = set(key_variants(rec))
    for written in ("Qfd_BushfireAlert|QF-1|2026-01-04T03:00:00",
                    "Qfd_BushfireAlert_QF-1_2026-01-04 03:00:00",
                    "Qfd_BushfireAlert+QF-1+2026-01-04T03:00:00+00:00",
                    row_key("Qfd_BushfireAlert", "QF-1", t)):
        assert _norm(written) in variants, written
    assert _norm("Qfd_BushfireAlert|QF-2|2026-01-04T03:00:00") not in variants
