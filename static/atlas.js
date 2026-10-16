/* bushfire_atlas page. Everything comes from this app's own /api; nothing else is fetched.
 * Text from the sources is put on the page with textContent only, never as HTML: an agency's
 * words are data. The server does the linking and the judgements; this file draws. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var LEVEL_COLOUR = {
    emergency_warning: "--lvl-emergency", watch_and_act: "--lvl-watch", advice: "--lvl-advice",
    information: "--lvl-info", none: "--lvl-none", unknown: "--lvl-none"
  };
  var STATE_TEXT = {
    no_data_mounted: "No data mounted.",
    no_green: "No green layer published yet.",
    no_sources: "No bushfire source in green yet.",
    sources_unread: "Sources found, none could be read."
  };

  function colour(level) {
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue(LEVEL_COLOUR[level] || "--lvl-none").trim();
    return v || "#888";
  }
  function words(s) { return String(s || "").replace(/_/g, " "); }
  // "2026-10-16T02:08:06Z" -> "2026-10-16 02:08" (minutes are enough to read a fire by).
  function short(iso) { return iso ? iso.slice(0, 16).replace("T", " ") : "—"; }
  function cell(tr, text, sortValue) {
    var td = document.createElement("td");
    td.textContent = text == null || text === "" ? "—" : String(text);
    if (sortValue != null) td.setAttribute("data-sort-value", sortValue);
    tr.appendChild(td);
    return td;
  }
  function pill(td, level) {
    td.textContent = "";
    var s = document.createElement("span");
    s.className = "pill lvl-" + level;
    s.textContent = words(level);
    td.appendChild(s);
  }

  // ── the map ────────────────────────────────────────────────────────────────────────────
  var map = window.MapKit ? window.MapKit.create($("map"), { center: [-27, 134], zoom: 4 }) : null;
  var eventLayer = null, detailLayer = null;
  if (!map) {
    $("map").hidden = true;
    var n = $("map-note");
    n.hidden = false;
    n.textContent = "The map could not load (its vendored Leaflet is missing); the tables below still work.";
  }

  function drawEvents(events) {
    if (!map) return;
    if (eventLayer) map.removeLayer(eventLayer);
    eventLayer = window.MapKit.pins(map, events, {
      color: function (e) { return colour(e.warning_level); },
      radius: function (e) { return Math.min(14, 5 + Math.log2(1 + e.member_count) * 2); },
      popup: function (e) {
        var d = document.createElement("div");
        d.textContent = words(e.warning_level) + " · " + e.jurisdictions.join(", ") +
          (e.cross_border ? " · cross-border" : "") + " · " + e.member_count + " record(s)";
        return d;
      }
    });
    eventLayer.eachLayer(function (m) {
      var e = m._mapKitPoint;
      if (e && e.cross_border) m.setStyle({ color: colour("emergency_warning"), weight: 3 });
      m.on("click", function () { openEvent(e.event_id); });
    });
    if (events.length) window.MapKit.fit(map, eventLayer, 9);
  }

  function drawDetail(body) {
    if (!map) return;
    if (detailLayer) map.removeLayer(detailLayer);
    var L = window.L, grp = L.featureGroup();
    var c = colour(body.event.warning_level);
    var drawn = {};
    (body.geometry.features || []).forEach(function (f) {
      drawn[f.properties.row_key] = true;
      grp.addLayer(L.geoJSON(f, { style: { color: c, weight: 2, fillOpacity: 0.15 } }));
    });
    body.members.forEach(function (m) {
      if (drawn[m.row_key]) return;
      if (m.bbox && ["polygon", "multipolygon", "line", "raster_cell"].indexOf(m.geom_type) >= 0) {
        grp.addLayer(L.rectangle([[m.bbox[1], m.bbox[0]], [m.bbox[3], m.bbox[2]]],
          { color: c, weight: 1, dashArray: "4 3", fillOpacity: 0.08 }));
      } else if (m.lat != null && m.lon != null) {
        var r = m.geom_type === "circle" ? m.radius_m : m.loc_precision_m;
        if (r) grp.addLayer(L.circle([m.lat, m.lon], { radius: r, color: c, weight: 1, fillOpacity: 0.1 }));
        grp.addLayer(L.circleMarker([m.lat, m.lon], { radius: 4, color: "#fff", weight: 1,
          fillColor: c, fillOpacity: 1 }));
      }
    });
    detailLayer = grp.addTo(map);
    window.MapKit.fit(map, grp, 11);
  }

  // ── the query ──────────────────────────────────────────────────────────────────────────
  function query() {
    var p = new URLSearchParams();
    var back = Number($("f-end").value);
    var end = new Date(Date.now() + back * 3600 * 1000);
    if (back !== 0) p.set("end", end.toISOString().replace(/\.\d+Z$/, "Z"));
    p.set("hours", $("f-hours").value);
    ["jurisdiction", "level", "kind"].forEach(function (k) {
      var v = $("f-" + k).value;
      if (v) p.set(k, v);
    });
    $("f-end-label").textContent = back === 0 ? "now" : short(end.toISOString());
    return p;
  }

  function showState(body) {
    var el = $("state");
    el.className = "state state-" + body.state;
    var head = STATE_TEXT[body.state];
    el.textContent = head ? head + " " + body.message : (body.message || "");
    el.hidden = !el.textContent;
  }

  function fillEvents(events) {
    var tb = $("events").querySelector("tbody");
    tb.textContent = "";
    events.forEach(function (e) {
      var tr = document.createElement("tr");
      tr.tabIndex = 0;
      var idCell = cell(tr, "");
      idCell.textContent = "";
      var a = document.createElement("a");
      a.href = "#" + e.event_id;
      a.textContent = e.event_id;
      idCell.appendChild(a);
      pill(cell(tr, ""), e.warning_level);
      cell(tr, words(e.status));
      cell(tr, e.jurisdictions.join(", ") + (e.cross_border ? " (cross-border)" : ""));
      cell(tr, short(e.first_seen_utc), e.first_seen_utc);
      cell(tr, short(e.last_seen_utc), e.last_seen_utc);
      cell(tr, e.member_count);
      cell(tr, e.sources.join(", "));
      tr.addEventListener("click", function (ev) { ev.preventDefault(); openEvent(e.event_id); });
      tb.appendChild(tr);
    });
    $("event-count").textContent = events.length ? "(" + events.length + ")" : "";
  }

  function fillSources(sources) {
    var tb = $("sources").querySelector("tbody");
    tb.textContent = "";
    if (!sources.length) {
      var tr = document.createElement("tr");
      var td = cell(tr, "No source to list: see the message above.");
      td.colSpan = 6;
      tb.appendChild(tr);
      return;
    }
    sources.forEach(function (s) {
      var tr = document.createElement("tr");
      cell(tr, s.source_name);
      cell(tr, s.kind);
      cell(tr, s.state === "read" ? "read" : "not read");
      cell(tr, s.rows);
      cell(tr, short(s.latest_utc), s.latest_utc || "");
      cell(tr, s.note);
      tb.appendChild(tr);
    });
  }

  var last = null;
  function load() {
    var p = query();
    last = p;
    fetch("api/fires?" + p.toString(), { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (body) {
        if (p !== last) return;                 // a newer query is on its way
        showState(body);
        fillEvents(body.events || []);
        fillSources(body.sources || []);
        drawEvents(body.events || []);
        $("link-distance").textContent = body.link ? body.link.distance_m : "—";
        $("link-gap").textContent = body.link ? body.link.gap_hours : "—";
        $("link-index").textContent = body.link ? body.link.index : "—";
        if (location.hash.length > 1) openEvent(decodeURIComponent(location.hash.slice(1)));
      })
      .catch(function (err) {
        var el = $("state");
        el.className = "state state-error";
        el.textContent = "Could not reach this app's /api/fires: " + err;
      });
  }

  function openEvent(id) {
    var p = query();
    fetch("api/fires/" + encodeURIComponent(id) + "?" + p.toString())
      .then(function (r) { return r.json(); })
      .then(function (body) {
        var box = $("detail");
        box.hidden = false;
        $("detail-id").textContent = id;
        if (body.state !== "ok") {
          $("detail-summary").textContent = body.message;
          $("members").querySelector("tbody").textContent = "";
          $("detail-geom").hidden = true;
          return;
        }
        if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
        var e = body.event;
        $("detail-summary").textContent = words(e.warning_level) + " · " + words(e.status) +
          " · " + e.jurisdictions.join(", ") + (e.cross_border ? " · reported by more than one state" : "") +
          " · seen " + short(e.first_seen_utc) + " to " + short(e.last_seen_utc) + " UTC · " +
          e.member_count + " source record(s)" +
          (e.size_ha_stated != null ? " · largest stated size " + e.size_ha_stated + " ha" : "");
        var notes = Object.keys(body.geometry_notes || {}).map(function (k) {
          return k + ": " + body.geometry_notes[k];
        });
        $("detail-geom").hidden = !notes.length;
        $("detail-geom").textContent = notes.join(" · ");
        var tb = $("members").querySelector("tbody");
        tb.textContent = "";
        body.members.forEach(function (m) {
          var tr = document.createElement("tr");
          cell(tr, m.source_name);
          cell(tr, m.source_agency);
          cell(tr, m.source_record_id);
          cell(tr, m.jurisdiction);
          cell(tr, words(m.record_kind));
          pill(cell(tr, ""), m.warning_level);
          cell(tr, m.warning_level_source);
          cell(tr, words(m.status) + (m.status_source ? " (" + m.status_source + ")" : ""));
          cell(tr, short(m.time_start_utc), m.time_start_utc || "");
          cell(tr, short(m.time_end_utc), m.time_end_utc || "");
          cell(tr, m.geom_type);
          cell(tr, m.loc_precision_m != null ? Math.round(m.loc_precision_m) : "");
          cell(tr, m.size_ha);
          tb.appendChild(tr);
        });
        drawDetail(body);
        box.scrollIntoView({ behavior: "smooth", block: "start" });
      });
  }

  var hours = document.body.getAttribute("data-window-hours");
  if (hours && $("f-hours").querySelector('option[value="' + hours + '"]')) $("f-hours").value = hours;
  var timer = null;
  function soon() { clearTimeout(timer); timer = setTimeout(load, 250); }
  ["f-end", "f-hours", "f-jurisdiction", "f-level", "f-kind"].forEach(function (id) {
    $(id).addEventListener(id === "f-end" ? "input" : "change", soon);
  });
  load();
})();
