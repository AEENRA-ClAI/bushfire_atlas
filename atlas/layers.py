"""Full geometry from data_library's map_layers/<source_name>.geojson, read-only.

Green carries a bbox; the polygon itself lives in the source's layer file, each feature's
properties carrying the green row key as `row_key` (the bushfire green contract). The app only
ever READS a layer, and only for the members of the one event a person opened.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Dict, List, Optional, Tuple

from .green import safe_name
from .records import Record

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _norm(key: str) -> str:
    return _NON_ALNUM.sub("", key or "")


def key_variants(rec: Record) -> List[str]:
    """The row key in the renderings a writer might use for the timestamp.

    UNVERIFIED: the hub's exact rendering is set by data_library _bushfire_geo.py, not landed
    when this was written. Comparing with punctuation stripped makes '|' vs '_' and '-' vs ''
    the same; the T/space and the trailing zero fraction are tried both ways."""
    base = f"{rec.source_name}{rec.source_record_id}"
    if rec.rec_vld_dts is None:
        return [_norm(base)]
    t = rec.rec_vld_dts
    stamps = {t.strftime("%Y-%m-%dT%H:%M:%S"), t.strftime("%Y-%m-%d %H:%M:%S"),
              t.strftime("%Y-%m-%dT%H:%M:%S.%f"), t.strftime("%Y-%m-%d %H:%M:%S.%f"),
              t.strftime("%Y-%m-%dT%H:%M:%S") + "000", t.strftime("%Y-%m-%d")}
    return sorted({_norm(base + s) for s in stamps} | {_norm(base + s + "+00:00") for s in stamps})


class LayerReader:
    def __init__(self, settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[Tuple[float, int], Dict[str, dict]]] = {}

    def _index(self, source_name: str) -> Tuple[str, Optional[Dict[str, dict]]]:
        """(note, {normalised row_key: feature}) for a source, or a note saying why there is none."""
        if not safe_name(source_name):
            return "not a source name", None
        path = os.path.join(self.settings.map_layers_root, f"{source_name}.geojson")
        if not os.path.isfile(path):
            return f"no map layer for {source_name} (map_layers/{source_name}.geojson)", None
        st = os.stat(path)
        stamp = (st.st_mtime, st.st_size)
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == stamp:
                return "", cached[1]
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                return f"map layer for {source_name} could not be read: {exc}", None
            index = {}
            for feat in data.get("features") or []:
                props = feat.get("properties") or {}
                if props.get("row_key") and feat.get("geometry"):
                    index[_norm(str(props["row_key"]))] = feat
            self._cache[path] = (stamp, index)
            return "", index

    def features_for(self, members: List[Record]) -> Tuple[List[dict], Dict[str, str]]:
        """The layer features of an event's members, and a note per source that has none."""
        features: List[dict] = []
        notes: Dict[str, str] = {}
        for rec in members:
            if rec.geom_type not in ("polygon", "multipolygon", "line"):
                continue
            note, index = self._index(rec.source_name)
            if index is None:
                notes[rec.source_name] = note
                continue
            feat = next((index[k] for k in key_variants(rec) if k in index), None)
            if feat is None:
                notes.setdefault(rec.source_name,
                                 "some members' shapes are not in the map layer; their bbox is shown")
                continue
            features.append({"type": "Feature", "geometry": feat["geometry"],
                             "properties": {"row_key": rec.key, "source_name": rec.source_name,
                                            "record_kind": rec.record_kind}})
        return features, notes
