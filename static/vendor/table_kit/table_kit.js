/* =============================================================================
 * table_kit.js — ONE table behaviour for every app in the fleet (owner 2026-09-26).
 *
 * CANONICAL HOME: toolbox library/ui/table_kit/. Every app carries a CHECKED-OUT copy
 * (toolbox scripts/checkout.py, bundle `table_kit`) — do not edit it in an app; edit it
 * here and check it out again. Vanilla, no dependencies, no build step, no network,
 * no inline <script> or eval — so it runs under a `script-src 'self'` CSP and offline.
 *
 * What it does to every <table> on the page (including ones a script draws later):
 *
 *   0. NEVER MORE THAN ABOUT TWO SCREENS. A long table pages (50 rows; on a phone as
 *      many cards as fit in two screens, measured — 2 to 8) with Prev / Next / Show all. Filter, sort, "Select all" and CSV still
 *      cover every matching row, not only the page on screen. data-tk-page="N" sets
 *      the page size per table, "0" turns paging off.
 *
 *   1. FILTER · SORT · SELECT. A search box over every column (a space is AND, a comma
 *      is OR, "quotes" keep a phrase inside ONE cell), click any heading to sort (again
 *      to reverse; numbers as numbers, blanks always last), a tick box per row with
 *      select-shown / clear, a live "n of N" count, and a CSV of the ticked or shown rows.
 *
 *   2. THREE LAYOUTS, chosen by the table's OWN width, not the screen's. That is what
 *      makes split screen work: an iPad in split view, or a desktop window dragged
 *      narrow, gets the layout that fits the space the table actually has.
 *        wide    — the ordinary table.
 *        medium  — the table scrolls sideways INSIDE its own box (never the page), the
 *                  first column stays put, and an edge fade says there is more.
 *        narrow  — every row becomes a CARD: label on the left, value on the right,
 *                  nothing wider than the screen. Sort moves to a dropdown, because
 *                  there are no headings to tap.
 *
 *   3. THE PAGE NEVER SCROLLS SIDEWAYS BECAUSE OF A TABLE. The fault on phones was a
 *      table wider than the page: the page's background shrank to the phone while the
 *      table stayed desktop-wide and floated past it, and the page panned in every
 *      direction. Every table is put in its own scroll box, and any flex/grid parent
 *      that would have stretched to the table's width is allowed to shrink.
 *
 * Opting a table in or out (attributes on the <table>):
 *   data-tk="off"      leave this table completely alone.
 *   data-tk="managed"  another engine already filters/sorts/selects it (a paged server
 *                      grid): keep the responsive layout, add no toolbar.
 *   data-tk="lite"     search + sort, no tick boxes (a short list inside a card).
 *   data-tk-cards="never" | "always"   pin the narrow layout.
 *   data-sort-value="…" on a <td>      what to sort by when the text is not it.
 *   WIDTH vs DEPTH, per column (set on the column's <th>; owner 2026-09-26):
 *     data-tk-narrow="hide"   a column that matters on a wide screen but not in a phone
 *                             card: hidden in cards (still filtered, sorted, exported).
 *     data-tk-scroll          a long-text column (a dialogue, a transcript excerpt): in
 *                             a card it is ALWAYS shown, never folded, full width, in
 *                             its own bounded box that scrolls inside — so a scene sits
 *                             above its dialogue and the page stays short.
 *   An app that already draws its own tick-box column (the first column, a checkbox
 *   and nothing else in the heading and every cell) keeps it: the kit adopts it as
 *   THE tick column (class tk-pick) instead of adding a second.
 *   A table with no header row, or fewer than 2 body rows, gets only the responsive box.
 *
 * Tables already managed by a known engine are detected and treated as "managed":
 *   [data-server] (movie_maker server grids), and anything matching
 *   window.TABLE_KIT_MANAGED (a CSS selector an app may set before this script loads).
 *
 * Events: a `tablekit:select` CustomEvent on the table whenever the ticks change,
 * detail = { rows: [<tr>…] }. table.tableKit.selected() returns the ticked rows.
 * =========================================================================== */
(function () {
  "use strict";
  if (window.TableKit) return;                       // loaded twice → one instance

  var NARROW = 600;      // a table box narrower than this becomes cards
  var SMALL_COLS = 4;    // …unless it has this many data columns or fewer and fits as a table
  var MIN_ROWS = 2;      // fewer body rows than this → no toolbar (nothing to sort)
  var CARD_FIELDS = 6;   // a card longer than this folds to its first fields until tapped
  // A page is at most about TWO SCREENS tall (owner 2026-09-26: "not more than like two
  // pages tall"), so a long table pages instead of scrolling forever. Cards are tall, so
  // they page sooner. data-tk-page="N" sets it per table; "0" turns paging off.
  var PAGE_ROWS = 50, PAGE_CARDS = 8;
  var busy = false;      // true while WE mutate the DOM, so the observer ignores it
  var observer = null;

  function each(list, fn) { Array.prototype.forEach.call(list || [], fn); }
  function cellText(td) {
    if (!td) return "";
    return (td.innerText != null ? td.innerText : td.textContent || "").replace(/\s+/g, " ").trim();
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  // MutationObserver callbacks are ASYNC, so a flag alone cannot hide our own edits:
  // the records are drained here, synchronously, before anyone else can see them.
  function mutate(fn) {
    // anything the APP changed before this moment is kept, not thrown away with ours
    if (observer && !busy) handle(observer.takeRecords());
    busy = true;
    try { return fn(); }
    finally { if (observer) observer.takeRecords(); busy = false; }
  }

  /* ------------------------------------------------------------ search grammar */
  // "a b, c" → [[a,b],[c]] : OR of AND-groups. A quoted "phrase" is one term.
  function parseQuery(q) {
    var groups = [], cur = [], tok = "", inQ = false;
    function push() { var t = tok.trim().toLowerCase(); if (t) cur.push(t); tok = ""; }
    for (var i = 0; i < q.length; i++) {
      var c = q.charAt(i);
      if (c === '"') { if (inQ) { push(); } else { push(); } inQ = !inQ; continue; }
      if (!inQ && c === ",") { push(); if (cur.length) groups.push(cur); cur = []; continue; }
      if (!inQ && /\s/.test(c)) { push(); continue; }
      tok += c;
    }
    push(); if (cur.length) groups.push(cur);
    return groups;
  }
  // row text joins cells with "\n", so a phrase (which has no newline) stays in one cell
  function matches(text, groups) {
    if (!groups.length) return true;
    for (var g = 0; g < groups.length; g++) {
      var ok = true;
      for (var t = 0; t < groups[g].length; t++) {
        if (text.indexOf(groups[g][t]) === -1) { ok = false; break; }
      }
      if (ok) return true;
    }
    return false;
  }

  /* -------------------------------------------------------------------- sorting */
  var NUM = /^[-+]?[$€£¥A-Z]{0,3}\s?[-+]?\d[\d,\s]*(\.\d+)?\s?(%|[a-zA-Z]{0,4})$/;
  function sortKey(td) {
    if (!td) return null;
    var raw = td.getAttribute("data-sort-value");
    var s = raw != null ? raw : cellText(td);
    if (s === "" || s === "—" || s === "-" || s === "–") return null;
    if (NUM.test(s)) {
      var n = parseFloat(s.replace(/[^\d.\-+]/g, ""));
      if (!isNaN(n)) return { n: n };
    }
    if (/^\d{4}-\d{2}(-\d{2})?/.test(s)) return { s: s };   // ISO dates sort as text
    return { s: s.toLowerCase() };
  }
  function compare(a, b) {
    if (a === null && b === null) return 0;
    if (a === null) return 1;                         // blanks last, both directions
    if (b === null) return -1;
    if (a.n !== undefined && b.n !== undefined) return a.n - b.n;
    if (a.n !== undefined) return -1;
    if (b.n !== undefined) return 1;
    return a.s.localeCompare(b.s, undefined, { numeric: true });
  }

  /* ----------------------------------------------------------------- CSV export */
  function csv(rows) {
    return "﻿" + rows.map(function (r) {
      return r.map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(",");
    }).join("\r\n");
  }
  function download(name, rows) {
    var blob = new Blob([csv(rows)], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob), a = el("a");
    a.href = url; a.download = (name || "table").replace(/[^\w.-]+/g, "_").slice(0, 60) + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  /* ------------------------------------------------------- the page-width guard */
  // A flex or grid item defaults to min-width:auto — it refuses to be narrower than
  // its content, so ONE wide table stretches every parent up to <body>. Let them shrink.
  function letAncestorsShrink(node) {
    var p = node.parentElement;
    while (p && p !== document.body && p !== document.documentElement) {
      var parent = p.parentElement;
      if (parent) {
        var d = getComputedStyle(parent).display;
        if (/flex|grid/.test(d) && getComputedStyle(p).minWidth === "auto") p.classList.add("tk-shrink");
      }
      p = parent;
    }
  }

  function scrollBoxFor(table) {
    var p = table.parentElement;
    if (p && p.classList.contains("tk-wrap")) return p;
    // an app's own scroll wrapper (the table is its only element child) is reused,
    // never nested — two sideways scrollers inside each other is what made tables
    // drift in every direction under a thumb.
    if (p && p !== document.body && p.children.length === 1) {
      var ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll") { p.classList.add("tk-wrap"); return p; }
    }
    var wrap = el("div", "tk-wrap");
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
    return wrap;
  }

  /* ------------------------------------------------------------------- one table */
  function headerRow(table) {
    var h = table.tHead;
    if (h && h.rows.length) return h.rows[h.rows.length - 1];
    // a table whose first body row is all <th> is a header too
    var b = table.tBodies[0];
    if (b && b.rows.length && b.rows[0].cells.length &&
        Array.prototype.every.call(b.rows[0].cells, function (c) { return c.tagName === "TH"; })) {
      return b.rows[0];
    }
    return null;
  }

  function Kit(table) {
    this.table = table;
    this.mode = (table.getAttribute("data-tk") || "").toLowerCase();
    var managedSel = window.TABLE_KIT_MANAGED;
    if (!this.mode && (table.hasAttribute("data-server") ||
        (managedSel && table.matches(managedSel)))) this.mode = "managed";
    this.sortCol = -1; this.sortDir = 1; this.query = "";
    this.box = scrollBoxFor(table);
    table.classList.add("tk");
    letAncestorsShrink(this.box);
    this.layout();
    this.refresh();
    var self = this;
    if (window.ResizeObserver) {
      new ResizeObserver(function () { self.layout(); }).observe(this.box);
    } else {
      window.addEventListener("resize", function () { self.layout(); });
    }
    this.ready = true;
    this.box.addEventListener("scroll", function () { self.edges(); }, { passive: true });
    // a row's tick (ours, or the app's own adopted column) keeps the count and tint true
    table.addEventListener("change", function (e) {
      var box = e.target, cell = box.closest && box.closest("td.tk-pick");
      if (!cell || box.type !== "checkbox") return;
      var tr = cell.parentElement;
      tr.classList.toggle("tk-ticked", box.checked);
      if (self.picking()) self.counts(true);
    });
    // the whole tick cell is the target, not just the 17px box inside it
    table.addEventListener("click", function (e) {
      var cell = e.target.closest && e.target.closest("td.tk-pick, th.tk-pick");
      if (!cell || e.target.tagName === "INPUT" || e.target.closest("label")) return;
      var box = cell.querySelector("input[type=checkbox]");
      if (box && !box.disabled) box.click();
    });
    // a folded card opens (and closes) with a tap anywhere on it that is not a control
    table.addEventListener("click", function (e) {
      if (!table.classList.contains("tk-cards")) return;
      if (e.target.closest("a,button,input,select,textarea,label,summary,[contenteditable]")) return;
      var tr = e.target.closest("tr.tk-long");
      if (tr && table.contains(tr)) tr.classList.toggle("tk-open");
    });
  }

  Kit.prototype.head = function () { return headerRow(this.table); };
  Kit.prototype.bodyRows = function () {
    var head = this.head(), out = [];
    each(this.table.tBodies, function (tb) {
      each(tb.rows, function (tr) { if (tr !== head) out.push(tr); });
    });
    return out;
  };
  Kit.prototype.full = function () {
    return this.mode !== "managed" && this.head() && this.bodyRows().length >= MIN_ROWS;
  };
  Kit.prototype.picking = function () { return this.full() && this.mode !== "lite"; };

  // the column names, as the header reads — WITHOUT our tick-box column
  Kit.prototype.names = function () {
    var head = this.head(); if (!head) return [];
    var names = [];
    each(head.cells, function (th) {
      if (th.classList.contains("tk-pick")) return;
      // an app's own sort arrows in the heading are not part of the column's NAME
      // textContent, not innerText: innerText follows CSS (text-transform, a hidden
      // <thead>), so the same heading read "Film" on one table and "FILM" on another
      var span = th.colSpan || 1, t = (th.textContent || "").replace(/\s+/g, " ").trim().replace(/\s*[▲▼△▽↑↓↕⇅⬆⬇]+\s*$/, "");
      for (var i = 0; i < span; i++) names.push(t);
    });
    return names;
  };

  // label every cell with its column name — the narrow layout prints it beside the value
  // An app that draws its OWN tick-box column (a managed table) gets it recognised as
  // one, so card labels line up and the fold does not count it as a field.
  function tickOnly(cell) {
    if (!cell) return false;
    var boxes = cell.querySelectorAll("input[type=checkbox]");
    return boxes.length <= 1 && cellText(cell) === "" &&
      cell.querySelectorAll("*").length === boxes.length;
  }
  Kit.prototype.adoptOwnPicks = function () {
    var first = this.bodyRows()[0];
    if (first && first.cells[0] && first.cells[0].hasAttribute("data-tk-own")) return;  // ours
    var head = this.head(), rows = this.bodyRows().filter(function (tr) {
      var own = tr.cells.length === 1 && (tr.cells[0].colSpan || 1) > 1;
      return !own;
    });
    if (!head || !rows.length || !head.cells.length) return;
    var h0 = head.cells[0];
    if (!tickOnly(h0)) return;
    if (!rows.every(function (tr) { var c = tr.cells[0]; return c && c.querySelector("input[type=checkbox]") && tickOnly(c); })) return;
    h0.classList.add("tk-pick");
    rows.forEach(function (tr) { tr.cells[0].classList.add("tk-pick"); });
    this.ownPicks = true;       // the app's column IS the tick column: never add a second
  };

  // What KIND each column is, read from its cells (owner 2026-10-12: "the spacing on different
  // table columns"): every filled cell a number → tk-num (the clean look right-aligns it in
  // tabular figures); every cell only buttons / drop-downs with no words of its own → tk-act
  // (kept narrow, at the row's end). Classes only, on the cells and the heading: any look may
  // use them, and a page without the clean look shows no change.
  var CONTROL = "button, select, a.btn, input:not([type=checkbox]):not([type=radio])";
  function onlyControls(td) {
    if (!td.querySelector(CONTROL)) return false;
    var copy = td.cloneNode(true);
    each(copy.querySelectorAll(CONTROL), function (el) { el.remove(); });
    return !(copy.textContent || "").replace(/[\s·|]/g, "");
  }
  Kit.prototype.kinds = function (ncols) {
    var rows = this.bodyRows().filter(function (tr) { return !tr.classList.contains("tk-note"); });
    var cols = [];
    rows.forEach(function (tr) {
      var c = 0;
      each(tr.cells, function (td) {
        if (td.classList.contains("tk-pick")) return;
        var k = cols[c] || (cols[c] = { num: 0, act: 0, other: 0 });
        if ((td.colSpan || 1) > 1) k.other++;
        else if (onlyControls(td)) k.act++;
        else {
          var key = sortKey(td);
          if (key === null) { /* blank: says nothing */ }
          else if (key.n !== undefined) k.num++;
          else k.other++;
        }
        c += td.colSpan || 1;
      });
    });
    var kind = cols.map(function (k) {
      if (!k) return "";
      if (k.num && !k.other && !k.act) return "tk-num";
      if (k.act && !k.other && !k.num) return "tk-act";
      return "";
    });
    var mark = function (cells) {
      var c = 0;
      each(cells, function (cell) {
        if (cell.classList.contains("tk-pick")) return;
        cell.classList.toggle("tk-num", kind[c] === "tk-num");
        cell.classList.toggle("tk-act", kind[c] === "tk-act");
        c += cell.colSpan || 1;
      });
    };
    var head = this.head();
    if (head) mark(head.cells);
    rows.forEach(function (tr) { mark(tr.cells); });
  };

  Kit.prototype.label = function () {
    var names = this.names(), pick = this.picking();
    this.table.classList.toggle("tk-has-pick", !!this.table.querySelector("tbody td.tk-pick"));
    // A row that is ONE cell across the whole table is a note, not a data row. Right
    // after a data row it is that row's DETAIL (an accordion, a notes line): it moves
    // with its row when sorted and hides with it when filtered. With no row above it
    // (an empty-state message) it stands alone. data-tk-detail marks one explicitly.
    var parent = null;
    this.bodyRows().forEach(function (tr) {
      var own = Array.prototype.filter.call(tr.cells, function (c) { return !c.classList.contains("tk-pick"); });
      var note = tr.hasAttribute("data-tk-detail") || (own.length === 1 && (own[0].colSpan || 1) > 1);
      tr.classList.toggle("tk-note", note);
      if (note) { tr._tkParent = parent; tr.classList.toggle("tk-attached", !!parent); }
      else { tr._tkParent = null; tr.classList.remove("tk-attached"); parent = tr; }
    });
    // per-column width-vs-depth flags from the heading
    var flags = [], head = this.head(), fi = 0;
    if (head) each(head.cells, function (th) {
      if (th.classList.contains("tk-pick")) return;
      var span = th.colSpan || 1;
      for (var k = 0; k < span; k++) flags[fi + k] = {
        hide: (th.getAttribute("data-tk-narrow") || "").toLowerCase() === "hide",
        scroll: th.hasAttribute("data-tk-scroll")
      };
      fi += span;
    });
    var self = this;
    this.bodyRows().forEach(function (tr) {
      if (tr.classList.contains("tk-note")) return;
      var c = 0;
      each(tr.cells, function (td) {
        if (td.classList.contains("tk-pick")) return;
        var f = flags[c] || {};
        td.classList.toggle("tk-narrow-hide", !!f.hide);
        td.classList.toggle("tk-scroll", !!f.scroll || td.hasAttribute("data-tk-scroll"));
        c += td.colSpan || 1;
      });
    });
    this.kinds(flags.length);
    this.bodyRows().forEach(function (tr) {
      // a column hidden in cards, or always shown, does not count toward the fold
      var fields = Array.prototype.filter.call(tr.cells, function (td) {
        return !td.classList.contains("tk-pick") && !td.classList.contains("tk-narrow-hide") && !td.classList.contains("tk-scroll");
      }).length;
      if (fields > CARD_FIELDS && !tr.classList.contains("tk-note")) {
        tr.classList.add("tk-long"); tr.setAttribute("data-tk-more", String(fields - CARD_FIELDS));
      } else { tr.classList.remove("tk-long"); tr.removeAttribute("data-tk-more"); }
      var i = 0;
      each(tr.cells, function (td) {
        if (td.classList.contains("tk-pick")) return;
        var n = names[i] || "";
        if (!td.hasAttribute("data-label") || td.getAttribute("data-tk-label") === "1") {
          if (n) { td.setAttribute("data-label", n); td.setAttribute("data-tk-label", "1"); }
        }
        i += td.colSpan || 1;
      });
    });
  };

  Kit.prototype.layout = function () {
    var t = this.table, pin = (t.getAttribute("data-tk-cards") || "").toLowerCase();
    var w = this.box.clientWidth || (this.box.parentElement || {}).clientWidth || 0;
    var cards = pin === "always" || (pin !== "never" && !!this.head() && w > 0 && w < NARROW);
    // A SHORT table stays a table (owner 2026-09-26: "its only 3 things and its spread over
    // several lines … it could be a table instead"). A trait/value list turned into one card
    // per row took three lines a row; so did the animal card's trait · EBV · acc · %ile. With SMALL_COLS or fewer data columns it goes to cards
    // only when it genuinely cannot fit across the box as a table.
    // It is measured with its cells allowed to WRAP (tk-tight): an app stylesheet that sets
    // cells nowrap (Herdity) would otherwise make a long trait name push a 4-column table
    // off the edge and back into cards.
    var tight = false;
    if (cards && pin !== "always" && this.dataColumns() <= SMALL_COLS && this.fitsAsTable()) {
      cards = false; tight = true;
    }
    if (tight !== t.classList.contains("tk-tight")) t.classList.toggle("tk-tight", tight);
    if (cards !== t.classList.contains("tk-cards")) {
      t.classList.toggle("tk-cards", cards);
      this.box.classList.toggle("tk-wrap-cards", cards);
      // Re-page on EVERY layout flip once the table is set up. The old guard asked
      // "does it have a pager yet", so a table first laid out inside a hidden sub-tab
      // (width 0 → not cards → 50 rows fit → no pager) never re-paged when revealed
      // (Herdity: Recommended crosses stayed 25 rows tall on a phone).
      this.cardH = 0;
      if (this.ready) { this.page = 0; this.paginate(); }
    }
    if (this.tools) this.tools.classList.toggle("tk-tools-cards", cards);
    this.edges();
  };

  // columns a reader sees: not our tick column, not one the app hides on a phone
  Kit.prototype.dataColumns = function () {
    var head = this.head(), n = 0;
    if (!head) return 0;
    each(head.cells, function (th) {
      if (th.classList.contains("tk-pick")) return;
      if ((th.getAttribute("data-tk-narrow") || "").toLowerCase() === "hide") return;
      n += th.colSpan || 1;
    });
    return n;
  };
  // measured, never guessed: lay it out as a table for a moment and see if it overflows
  Kit.prototype.fitsAsTable = function () {
    var t = this.table, b = this.box, was = t.classList.contains("tk-cards");
    var tight = t.classList.contains("tk-tight");
    if (was) { t.classList.remove("tk-cards"); b.classList.remove("tk-wrap-cards"); }
    if (!tight) t.classList.add("tk-tight");
    var fits = b.scrollWidth <= b.clientWidth + 1;
    if (!tight) t.classList.remove("tk-tight");
    if (was) { t.classList.add("tk-cards"); b.classList.add("tk-wrap-cards"); }
    return fits;
  };

  Kit.prototype.edges = function () {
    var b = this.box, over = !this.table.classList.contains("tk-cards") && b.scrollWidth > b.clientWidth + 1;
    b.classList.toggle("tk-overflow", over);
    var right = over && b.scrollLeft + b.clientWidth < b.scrollWidth - 1;
    b.classList.toggle("tk-more-right", right);
    b.classList.toggle("tk-more-left", over && b.scrollLeft > 1);
    // A fade alone is invisible on a low-contrast palette (Herdity's cream-on-cream):
    // a 9-column table read as one column. Say in words how many are off to the right.
    var hidden = 0, head = this.head();
    if (right && head) {
      var edge = b.getBoundingClientRect().right - 4;
      each(head.cells, function (th) { if (th.getBoundingClientRect().left >= edge) hidden++; });
    }
    var hint = this.moreHint;
    if (hidden > 0) {
      var self = this;
      if (!hint || !hint.isConnected) {
        hint = this.moreHint = el("button", "tk-more-cols"); hint.type = "button";
        hint.addEventListener("click", function () { b.scrollBy({ left: b.clientWidth * 0.8, behavior: "smooth" }); });
        mutate(function () { b.parentNode.insertBefore(hint, b); });
      }
      var txt = hidden + (hidden === 1 ? " more column →" : " more columns →");
      if (hint.textContent !== txt) hint.textContent = txt;
      hint.hidden = false;
    } else if (hint) { hint.hidden = true; }
  };

  // (re)build what depends on the rows — called on load and whenever the body changes
  Kit.prototype.refresh = function () {
    var self = this;
    mutate(function () {
      self.adoptOwnPicks();
      if (self.picking() && !self.ownPicks) self.addPicks();
      self.label();
      if (self.full()) { self.addTools(); self.bindHeads(); }
      else if (self.tools) { self.tools.remove(); self.tools = null; }
      self.cache = null;
      self.apply();
    });
    this.layout();
  };

  Kit.prototype.addPicks = function () {
    var self = this, head = this.head();
    if (head && !head.querySelector(".tk-pick")) {
      var th = el(head.cells[0] && head.cells[0].tagName === "TD" ? "td" : "th", "tk-pick");
      th.setAttribute("data-tk-own", "1");
      var all = el("input"); all.type = "checkbox";
      all.setAttribute("aria-label", "Select every row on this page");
      all.addEventListener("change", function () { self.tickShown(all.checked, true); });
      th.appendChild(all); head.insertBefore(th, head.firstChild);
      this.headBox = all;
    }
    this.bodyRows().forEach(function (tr) {
      if (tr.querySelector(":scope > .tk-pick")) return;
      // a single full-width cell ("no rows yet") is a message, not a row
      if (tr.cells.length === 1 && (tr.cells[0].colSpan || 1) > 1) { tr.cells[0].colSpan += 1; tr.classList.add("tk-note"); return; }
      var td = el("td", "tk-pick"), box = el("input");
      td.setAttribute("data-tk-own", "1");
      box.type = "checkbox"; box.setAttribute("aria-label", "Select this row");
      // no name attribute: a form this table sits in never submits our ticks
      td.appendChild(box); tr.insertBefore(td, tr.firstChild);
    });
  };

  Kit.prototype.addTools = function () {
    if (this.tools) return;
    var self = this, lite = this.mode === "lite";
    // an app that swapped the <table> inside its own wrapper leaves our old toolbar
    // behind: remove it, but keep what was typed in it
    var stale = this.box.previousElementSibling;
    if (stale && stale.classList.contains("tk-more-cols")) stale = stale.previousElementSibling;
    if (stale && stale.classList.contains("tk-tools")) {
      var old = stale.querySelector(".tk-search");
      if (old) this.query = old.value;
      stale.remove();
    }
    var tools = el("div", "tk-tools");
    var search = el("input", "tk-search");
    search.type = "search";
    search.placeholder = "Filter… (space = and, comma = or)";
    search.setAttribute("aria-label", "Filter every column of this table");
    search.value = this.query || "";
    var t;
    search.addEventListener("input", function () {
      clearTimeout(t); t = setTimeout(function () { self.query = search.value; self.apply(); }, 120);
    });
    tools.appendChild(search);

    // sort dropdown — the only way to sort once the headings are gone (cards)
    var sort = el("select", "tk-sort");
    sort.setAttribute("aria-label", "Sort by");
    tools.appendChild(sort);
    sort.addEventListener("change", function () {
      var v = sort.value;
      if (v === "") { self.sortCol = -1; self.apply(); return; }
      var p = v.split(":"); self.sortBy(+p[0], +p[1]);
    });
    this.sortSelect = sort;

    var count = el("span", "tk-count");
    count.setAttribute("aria-live", "polite");
    tools.appendChild(count);
    this.countEl = count;

    if (!lite) {
      var sel = el("span", "tk-sel");
      var bAll = el("button", "tk-btn", "Select all"); bAll.type = "button";
      var bNone = el("button", "tk-btn", "Clear"); bNone.type = "button";
      bAll.addEventListener("click", function () { self.tickShown(true); });
      bNone.addEventListener("click", function () { self.tickAll(false); });
      sel.appendChild(bAll); sel.appendChild(bNone);
      tools.appendChild(sel);
    }
    var dl = el("button", "tk-btn", "CSV"); dl.type = "button";
    dl.title = "Download the ticked rows, or every shown row when none is ticked";
    dl.addEventListener("click", function () { self.exportCsv(); });
    tools.appendChild(dl);
    this.csvBtn = dl;

    // toolbar first, then the "N more columns" hint, then the table
    var before = this.moreHint && this.moreHint.isConnected ? this.moreHint : this.box;
    this.box.parentNode.insertBefore(tools, before);
    this.tools = tools;
    this.fillSort();
  };

  Kit.prototype.fillSort = function () {
    var s = this.sortSelect; if (!s) return;
    var names = this.names(), cur = this.sortCol + ":" + this.sortDir;
    s.textContent = "";
    var o = el("option", null, "Sort: as listed"); o.value = ""; s.appendChild(o);
    names.forEach(function (n, i) {
      if (!n) return;
      [[1, " ↑"], [-1, " ↓"]].forEach(function (d) {
        var op = el("option", null, n + d[1]); op.value = i + ":" + d[0]; s.appendChild(op);
      });
    });
    s.value = this.sortCol >= 0 ? cur : "";
  };

  Kit.prototype.bindHeads = function () {
    var self = this, head = this.head(); if (!head) return;
    var i = 0;
    each(head.cells, function (th) {
      if (th.classList.contains("tk-pick")) return;
      var col = i; i += th.colSpan || 1;
      if (th.getAttribute("data-tk-bound") === "1" || th.hasAttribute("data-nosort")) return;
      th.setAttribute("data-tk-bound", "1");
      th.classList.add("tk-sortable");
      th.tabIndex = 0;
      th.setAttribute("title", "Sort by this column");
      function go() { self.sortBy(col, self.sortCol === col ? -self.sortDir : 1); }
      th.addEventListener("click", function (e) { if (e.target.closest("a,button,input,select")) return; go(); });
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });
  };

  Kit.prototype.sortBy = function (col, dir) { this.sortCol = col; this.sortDir = dir; this.apply(); };

  Kit.prototype.cellAt = function (tr, col) {
    var i = 0, found = null;
    each(tr.cells, function (td) {
      if (found || td.classList.contains("tk-pick")) return;
      var span = td.colSpan || 1;
      if (col >= i && col < i + span) found = td;
      i += span;
    });
    return found;
  };

  Kit.prototype.apply = function () {
    var self = this, rows = this.bodyRows();
    if (!this.full()) { this.edges(); return; }
    if (!this.cache || this.cache.length !== rows.length) {
      this.cache = rows.map(function (tr) {
        var parts = [];
        each(tr.cells, function (td) { if (!td.classList.contains("tk-pick")) parts.push(cellText(td).toLowerCase()); });
        return parts.join("\n");
      });
    }
    var groups = parseQuery(this.query || "");
    var shown = 0;
    mutate(function () {
      rows.forEach(function (tr, i) {
        if (tr.classList.contains("tk-note")) return;
        var ok = matches(self.cache[i], groups);
        tr.classList.toggle("tk-hidden", !ok);
        if (ok) shown++;
      });
      // a detail row follows its row; a lone note (an empty-state message) always shows
      rows.forEach(function (tr) {
        if (tr.classList.contains("tk-note"))
          tr.classList.toggle("tk-hidden", !!(tr._tkParent && tr._tkParent.classList.contains("tk-hidden")));
      });
      if (self.sortCol >= 0) {
        var col = self.sortCol, dir = self.sortDir, details = [], lone = [];
        var keyed = [];
        rows.forEach(function (tr, i) {
          if (!tr.classList.contains("tk-note")) keyed.push({ tr: tr, k: sortKey(self.cellAt(tr, col)), i: i, kids: [] });
        });
        rows.forEach(function (tr) {
          if (!tr.classList.contains("tk-note")) return;
          if (tr._tkParent) details.push(tr); else lone.push(tr);
        });
        details.forEach(function (tr) {
          for (var k = 0; k < keyed.length; k++) if (keyed[k].tr === tr._tkParent) { keyed[k].kids.push(tr); return; }
          lone.push(tr);
        });
        keyed.sort(function (a, b) {
          if (a.k === null || b.k === null) return compare(a.k, b.k) || a.i - b.i;
          return (compare(a.k, b.k) * dir) || a.i - b.i;
        });
        var tb = self.table.tBodies[0];
        lone.forEach(function (tr) { tb.appendChild(tr); });
        keyed.forEach(function (o) { tb.appendChild(o.tr); o.kids.forEach(function (d) { tb.appendChild(d); }); });
        self.cache = null;
      }
      var head = self.head(), j = 0;
      if (head) each(head.cells, function (th) {
        if (th.classList.contains("tk-pick")) return;
        var c = j; j += th.colSpan || 1;
        if (c === self.sortCol) th.setAttribute("aria-sort", self.sortDir > 0 ? "ascending" : "descending");
        else th.removeAttribute("aria-sort");
      });
    });
    if (this.sortSelect) this.sortSelect.value = this.sortCol >= 0 ? this.sortCol + ":" + this.sortDir : "";
    this.shown = shown;
    var key = (this.query || "") + "|" + this.sortCol + "|" + this.sortDir;
    if (key !== this.lastKey) { this.page = 0; this.lastKey = key; }
    this.paginate();
    this.counts(false);
    this.edges();
  };

  Kit.prototype.pageSize = function () {
    var attr = this.table.getAttribute("data-tk-page");
    if (attr != null && attr !== "" && !isNaN(+attr)) return Math.max(0, +attr);
    // A short table kept as a table on a narrow box (tk-tight) wraps its cells, so a row can
    // be two or three lines: page it by MEASURED row height too, to about two screens.
    if (this.table.classList.contains("tk-tight")) {
      var rows = this.dataRows().filter(function (tr) { return tr.offsetHeight > 0; }).slice(0, 12);
      var h = 0; each(rows, function (tr) { h += tr.offsetHeight; });
      if (rows.length && h > 0) {
        var room = 2 * (window.innerHeight || 800) - 320;
        return Math.max(4, Math.min(PAGE_ROWS, Math.floor(room / (h / rows.length))));
      }
      return PAGE_ROWS;
    }
    if (!this.table.classList.contains("tk-cards")) return PAGE_ROWS;
    // Cards: as many as fit in about two screens, MEASURED — a card with a long
    // description runs ~370px, so "8 cards" alone was 4+ screens (movie_maker).
    if (this.cardH > 0) {
      var budget = 2 * (window.innerHeight || 800) - 320;   // the toolbar and pager
      return Math.max(2, Math.min(PAGE_CARDS, Math.floor(budget / this.cardH)));
    }
    return PAGE_CARDS;
  };

  // the average height of the cards on screen (folded as shown), measured once per layout
  Kit.prototype.measureCards = function () {
    if (!this.table.classList.contains("tk-cards")) { this.cardH = 0; return false; }
    var shown = this.dataRows().filter(function (tr) {
      return !tr.classList.contains("tk-hidden") && !tr.classList.contains("tk-paged");
    }).slice(0, 4);
    if (!shown.length) return false;
    var h = 0;
    shown.forEach(function (tr) { h += tr.getBoundingClientRect().height + 10; });
    var avg = h / shown.length;
    if (!(avg > 0) || Math.abs(avg - (this.cardH || 0)) < 24) return false;
    this.cardH = avg;
    return true;
  };

  // show one page of the MATCHING rows; filter, sort, select and CSV still cover them all
  Kit.prototype.paginate = function () {
    var self = this;
    if (!this.full()) { if (this.pager) { this.pager.remove(); this.pager = null; } return; }
    var size = this.showAll ? 0 : this.pageSize();
    var matching = this.dataRows().filter(function (tr) { return !tr.classList.contains("tk-hidden"); });
    var pages = size > 0 ? Math.max(1, Math.ceil(matching.length / size)) : 1;
    if (!this.page || this.page < 0) this.page = 0;
    if (this.page > pages - 1) this.page = pages - 1;
    var from = size > 0 ? this.page * size : 0, to = size > 0 ? from + size : matching.length;
    mutate(function () {
      var on = {};
      self.dataRows().forEach(function (tr, i) { tr.classList.remove("tk-paged"); });
      matching.forEach(function (tr, i) { if (i < from || i >= to) tr.classList.add("tk-paged"); });
      self.bodyRows().forEach(function (tr) {
        if (tr.classList.contains("tk-note") && tr._tkParent)
          tr.classList.toggle("tk-paged", tr._tkParent.classList.contains("tk-paged"));
      });
      var needed = (size > 0 && matching.length > size) || (self.showAll && matching.length > self.pageSize());
      if (!needed) { if (self.pager) { self.pager.remove(); self.pager = null; } return; }
      if (!self.pager || !self.pager.isConnected) {
        var pg = el("div", "tk-pager");
        pg.setAttribute("role", "navigation");
        pg.setAttribute("aria-label", "Pages of this table");
        var prev = el("button", "tk-btn tk-prev", "‹ Prev"); prev.type = "button";
        var info = el("span", "tk-page-info"); info.setAttribute("aria-live", "polite");
        var next = el("button", "tk-btn tk-next", "Next ›"); next.type = "button";
        var all = el("button", "tk-btn tk-all"); all.type = "button";
        prev.addEventListener("click", function () { self.page--; self.paginate(); self.toTop(); });
        next.addEventListener("click", function () { self.page++; self.paginate(); self.toTop(); });
        all.addEventListener("click", function () { self.showAll = !self.showAll; self.page = 0; self.paginate(); if (!self.showAll) self.toTop(); });
        pg.appendChild(prev); pg.appendChild(info); pg.appendChild(next); pg.appendChild(all);
        self.box.parentNode.insertBefore(pg, self.box.nextSibling);
        self.pager = pg;
      }
      var q = function (c) { return self.pager.querySelector(c); };
      q(".tk-prev").disabled = self.showAll || self.page <= 0;
      q(".tk-next").disabled = self.showAll || self.page >= pages - 1;
      q(".tk-prev").hidden = q(".tk-next").hidden = !!self.showAll;
      q(".tk-page-info").textContent = self.showAll
        ? "All " + matching.length
        : (from + 1) + "–" + Math.min(to, matching.length) + " of " + matching.length;
      q(".tk-all").textContent = self.showAll ? "Show pages" : "Show all";
    });
    if (!this.measuring && this.measureCards()) {
      this.measuring = true;
      try { this.paginate(); } finally { this.measuring = false; }
    }
  };

  // after a page turn, bring the table's top back into view (not the page's)
  Kit.prototype.toTop = function () {
    var top = (this.tools || this.box).getBoundingClientRect().top;
    if (top < 0 && window.scrollBy) window.scrollBy(0, top - 8);
  };

  Kit.prototype.dataRows = function () {
    return this.bodyRows().filter(function (tr) { return !tr.classList.contains("tk-note"); });
  };
  Kit.prototype.selected = function () {
    return this.dataRows().filter(function (tr) {
      var b = tr.querySelector(":scope > .tk-pick input"); return b && b.checked;
    });
  };
  // every row the filter matches (all pages) — or, with onlyPage, the page on screen
  Kit.prototype.tickShown = function (on, onlyPage) {
    this.dataRows().forEach(function (tr) {
      if (tr.classList.contains("tk-hidden")) return;
      if (onlyPage && tr.classList.contains("tk-paged")) return;
      var b = tr.querySelector(":scope > .tk-pick input");
      if (b) { b.checked = on; tr.classList.toggle("tk-ticked", on); }
    });
    this.counts(true);
  };
  Kit.prototype.tickAll = function (on) {
    this.dataRows().forEach(function (tr) {
      var b = tr.querySelector(":scope > .tk-pick input");
      if (b) { b.checked = on; tr.classList.toggle("tk-ticked", on); }
    });
    this.counts(true);
  };

  Kit.prototype.counts = function (fire) {
    var total = this.dataRows().length;
    var shown = this.shown == null ? total : this.shown;
    var sel = this.picking() ? this.selected().length : 0;
    if (this.countEl) {
      this.countEl.textContent = (shown === total ? total + " rows" : shown + " of " + total + " rows") +
        (sel ? " · " + sel + " ticked" : "");
    }
    if (this.csvBtn) this.csvBtn.textContent = sel ? "CSV (" + sel + " ticked)" : "CSV";
    if (this.headBox) {
      var visible = this.dataRows().filter(function (tr) { return !tr.classList.contains("tk-hidden") && !tr.classList.contains("tk-paged"); });
      var on = visible.filter(function (tr) { var b = tr.querySelector(":scope > .tk-pick input"); return b && b.checked; }).length;
      this.headBox.checked = visible.length > 0 && on === visible.length;
      this.headBox.indeterminate = on > 0 && on < visible.length;
    }
    if (fire) {
      var ev;
      try { ev = new CustomEvent("tablekit:select", { detail: { rows: this.selected() } }); }
      catch (e) { ev = document.createEvent("CustomEvent"); ev.initCustomEvent("tablekit:select", false, false, { rows: this.selected() }); }
      this.table.dispatchEvent(ev);
    }
  };

  Kit.prototype.exportCsv = function () {
    var self = this, sel = this.selected();
    var rows = sel.length ? sel : this.dataRows().filter(function (tr) { return !tr.classList.contains("tk-hidden"); });
    var out = [this.names()];
    rows.forEach(function (tr) {
      var r = [];
      each(tr.cells, function (td) { if (!td.classList.contains("tk-pick")) r.push(cellText(td)); });
      out.push(r);
    });
    var cap = this.table.caption ? cellText(this.table.caption) : "";
    var title = cap || (document.querySelector("h1") || {}).innerText || document.title || "table";
    download(title, out);
  };

  /* ------------------------------------------------------------ the page sweep */
  function enhance(table) {
    if (!table || table.nodeName !== "TABLE") return null;
    if ((table.getAttribute("data-tk") || "").toLowerCase() === "off") return null;
    if (table.closest("[data-tk-off]")) return null;
    if (table.tableKit) return table.tableKit;
    if (!table.isConnected) return null;
    // a table nested inside another table's cell is part of that cell's content
    if (table.parentElement && table.parentElement.closest("table")) return null;
    var kit;
    mutate(function () { kit = new Kit(table); });
    table.tableKit = kit;
    return kit;
  }
  function scan(root) {
    each((root || document).querySelectorAll("table"), function (t) { enhance(t); });
  }

  // tables drawn later by an app's own script — new tables, and redrawn bodies
  var pending = [], timer = null;
  function flush() {
    timer = null;
    var todo = pending; pending = [];
    var seen = [];
    todo.forEach(function (n) {
      if (!n.isConnected) return;
      if (n.nodeName === "TABLE" && !n.tableKit) { enhance(n); return; }
      var t = n.nodeName === "TABLE" ? n : n.closest && n.closest("table");
      if (t && t.tableKit && seen.indexOf(t) === -1) { seen.push(t); t.tableKit.refresh(); }
      else if (t && !t.tableKit) enhance(t);
      else if (n.querySelectorAll) scan(n);
    });
  }
  function watch() {
    if (!window.MutationObserver) return;
    observer = new MutationObserver(handle);
    observer.observe(document.body, { childList: true, subtree: true });
  }
  function handle(records) {
      if (busy) return;
      records.forEach(function (r) {
        var t = r.target;
        if (t.nodeType !== 1) return;
        // our own toolbar/ticks never count as a change
        if (t.closest && t.closest(".tk-tools")) return;
        // any change inside a table (a redrawn body, an updated cell) refreshes that table
        var inTable = t.closest && t.closest("table");
        if (inTable) { pending.push(inTable); return; }
        each(r.addedNodes, function (n) {
          if (n.nodeType === 1 && (n.nodeName === "TABLE" || (n.querySelector && n.querySelector("table")))) pending.push(n);
        });
      });
      if (pending.length && !timer) timer = setTimeout(flush, 30);
  }

  function start() { scan(document); watch(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  window.TableKit = {
    enhance: enhance, scan: scan, parseQuery: parseQuery, matches: matches,
    NARROW: NARROW, version: 1
  };
})();
