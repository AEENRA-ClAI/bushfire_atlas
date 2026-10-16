/* map_kit — ONE offline map for the fleet (owner 2026-10-02: "There should already be a map in
 * the Smart Analyst" — so Janet's creator map is built on smart_analyst's, not beside it).
 *
 * What is shared, all of it local, nothing fetched at runtime:
 *   leaflet/        Leaflet 1.9.4 (BSD-2), never a CDN — the box blocks CDNs and banks do too
 *   world_land.js   Natural Earth 110m (public domain): WORLD_LAND, the dissolved coastline
 *                   (the FILL), and WORLD_COUNTRIES, the per-country rings (hairline BORDERS)
 *   map_kit.js      this file: the local basemap + graticule smart_analyst's map_layers.js
 *                   draws, as one reusable call, and a pin helper
 *
 * Load order: leaflet/leaflet.css, leaflet/leaflet.js, world_land.js, map_kit.js. Then
 *   const map = MapKit.create(el, {center: [20, 0], zoom: 2});
 *   MapKit.pins(map, points, {color: p => "#e8a33d", popup: p => html, radius: 6});
 * A missing Leaflet is answered with `null` from create(), so the app can show its own
 * honest fallback rather than a blank box.
 *
 * Why the land is TWO layers (smart_analyst, 2026-09-18/19): the country rings were each
 * simplified independently, so a shared border was two lines with sea showing through the
 * sliver. The dissolved land fills with no stroke; the countries come back on top as hairlines.
 */
(function () {
  "use strict";

  function cssVar(name, dflt) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || dflt;
    } catch (e) { return dflt; }
  }

  function rings(name) {
    const v = window[name];
    return Array.isArray(v) ? v : [];
  }

  function fc(list) {
    return { type: "FeatureCollection",
             features: list.map(r => ({ type: "Feature", properties: {},
                                        geometry: { type: "Polygon", coordinates: [r] } })) };
  }

  /* The offline basemap: dissolved land as the fill, country hairlines on top. */
  function basemap(opts) {
    const L = window.L;
    const grp = L.layerGroup();
    const o = opts || {};
    const land = rings("WORLD_LAND").length ? rings("WORLD_LAND") : rings("WORLD_COUNTRIES");
    if (!land.length) return grp;          // no geometry bundled — the graticule still orients
    grp.addLayer(L.geoJSON(fc(land), {
      pane: o.pane || "mapKitBase", interactive: false,
      style: { stroke: false, fillColor: o.land || cssVar("--surface-2", "#ece4d6"),
               fillOpacity: 1 },
    }));
    const borders = rings("WORLD_COUNTRIES");
    if (borders.length && borders !== land) {
      grp.addLayer(L.geoJSON(fc(borders), {
        pane: o.pane || "mapKitBase", interactive: false,
        style: { color: o.border || cssVar("--border", "#c9bda8"), weight: 0.6,
                 opacity: 0.55, fill: false },
      }));
    }
    return grp;
  }

  /* Lines of latitude / longitude, redrawn to the view (decorative; never blocks the map). */
  function graticule(map) {
    const L = window.L;
    let grp = null;
    const col = cssVar("--border", "#C2CBDC");
    const redraw = () => {
      try {
        if (grp) map.removeLayer(grp);
        const b = map.getBounds();
        if (!b || !b.isValid()) return;
        grp = L.layerGroup();
        const span = b.getEast() - b.getWest();
        const step = span > 60 ? 10 : span > 15 ? 5 : 1;
        const opts = { color: col, weight: 1, opacity: 0.35, interactive: false,
                       pane: "mapKitBase" };
        for (let x = Math.floor(b.getWest() / step) * step; x <= Math.ceil(b.getEast()); x += step)
          L.polyline([[b.getSouth(), x], [b.getNorth(), x]], opts).addTo(grp);
        for (let y = Math.floor(b.getSouth() / step) * step; y <= Math.ceil(b.getNorth()); y += step)
          L.polyline([[y, b.getWest()], [y, b.getEast()]], opts).addTo(grp);
        grp.addTo(map);
      } catch (e) { /* decorative */ }
    };
    redraw();
    map.on("moveend zoomend", redraw);
  }

  /* A Leaflet map on the offline basemap, or null when Leaflet is not loaded. */
  function create(el, opts) {
    const L = window.L;
    if (!L || !el) return null;
    const o = opts || {};
    const map = L.map(el, { worldCopyJump: true, minZoom: 1, maxZoom: o.maxZoom || 12,
                            zoomControl: true, attributionControl: false });
    map.createPane("mapKitBase").style.zIndex = 200;
    el.style.background = o.sea || cssVar("--map-sea", cssVar("--surface", "#dfe8ee"));
    basemap(o).addTo(map);
    graticule(map);
    map.setView(o.center || [20, 0], o.zoom || 2);
    return map;
  }

  /* Circle pins. points: [{lat, lon, ...}]; opts.color(p) / opts.popup(p) / opts.radius(p).
   * A point without a usable coordinate is skipped — never placed at 0,0. Returns the layer. */
  function pins(map, points, opts) {
    const L = window.L;
    const o = opts || {};
    const grp = L.featureGroup();
    (points || []).forEach((p, i) => {
      const lat = Number(p.lat), lon = Number(p.lon);
      if (!isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
      const r = typeof o.radius === "function" ? o.radius(p) : (o.radius || 6);
      const m = L.circleMarker([lat, lon], {
        radius: r, weight: 1, color: "#fff", fillOpacity: 0.9,
        fillColor: typeof o.color === "function" ? o.color(p) : (o.color || "#e8a33d"),
      });
      if (o.popup) m.bindPopup(o.popup(p, i));
      m._mapKitPoint = p;
      grp.addLayer(m);
    });
    grp.addTo(map);
    return grp;
  }

  /* Fit the view to a layer's points, with a floor so one pin does not zoom to a street. */
  function fit(map, layer, maxZoom) {
    try {
      const b = layer.getBounds();
      if (b && b.isValid()) map.fitBounds(b.pad(0.2), { maxZoom: maxZoom || 6 });
    } catch (e) { /* empty layer — keep the world view */ }
  }

  window.MapKit = { create, basemap, graticule, pins, fit };
})();
