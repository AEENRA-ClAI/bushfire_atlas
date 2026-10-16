# bushfire_atlas — Claude Code Context

**One view of Australia's bushfire data.** Every state's live incidents and warnings, the
satellite hotspots and the fire history, linked into **fire events by place and time, never by an
agency's id** (data_library D30). It answers "Australia urgently needs a national bushfire
database" (The Conversation): shared metadata and a controlled vocabulary, so a resident on a
state border can tell whether a warning is a new fire or the one they were already watching.

A read-only **spoke** of data_library's green layer (D29), run by Janet on the box. Australia
only (D27).

@.toolbox/instincts/SESSION_WORKFLOW.md

## In this repo

- **Full suite (start and handover only):** `python scripts/gate.py`: compile, tests, the real
  Chromium check, kit drift. `--quick` runs compile and tests.
- **Between the two runs:** `python -m pytest tests/<file>.py -q`. For a page change, also
  `python scripts/browser_check.py --out <png>`.
- **Try it:** `python scripts/make_fixture.py --root <dir>` writes a constructed green store
  (SIMULATED); then `EXTERNAL_DATA_ROOT=<dir> python app.py`.
- **Dev packages:** `pip install -r requirements-dev.txt`.

## Rules every change keeps

1. **A spoke never fetches and never writes.** No source is fetched here, no green or map layer is
   written, nothing is written into the checkout. Fresher data is a subscription in data_library,
   not a scraper here.
2. **Place and time, never ids.** `source_record_id` is provenance only: shown, never compared.
   Event ids come from the earliest member's place and start time (`atlas/linker.py`).
3. **Read only the contract.** A green source is read through the bushfire contract's standard
   columns (`atlas/records.py STANDARD_COLUMNS`), so a new state's pipeline appears with no change
   here. A source outside the contract gets an adapter in `atlas/green.py ADAPTERS` (FIRMS today).
   The controlled terms are data_library's `catalog/bushfire_vocabulary.json`; the app never maps
   an agency's raw term itself.
4. **Honest empty.** "No data mounted", "no green", "no bushfire source", "source not read: why",
   "no fires in this window", "no fires match these filters" are different sentences
   (`atlas/green.py`, `atlas/fires.py`). Never a bare empty table.
5. **Offline.** Every asset is vendored: the map kit and the table kit are toolbox checkouts under
   `static/vendor/` (edit them in the toolbox, never here; `.toolbox/checkout.lock.json`). No CDN,
   no tiles, no runtime call outside the app. The CSP is `'self'`.
6. **Every knob has a baked default** (`atlas/config.py`): `EXTERNAL_DATA_ROOT` (`/library`),
   `PORT` (8624), `HOST`, `APP_STATE_DIR`, `BUSHFIRE_LINK_DISTANCE_M` (3000),
   `BUSHFIRE_LINK_GAP_HOURS` (24), `BUSHFIRE_UNKNOWN_PRECISION_M` (5000),
   `BUSHFIRE_WINDOW_HOURS` (72), `BUSHFIRE_SOURCES` (empty: discover). No secret is needed.
7. **Foreign text is data.** Agency text reaches the page through `textContent` only.
8. **Every `<table>` carries `data-table`** (the table kit).

## Index

| part | file |
|---|---|
| How records become events, and what is not yet verified | [docs/features/linking.md](docs/features/linking.md) |
| Running it under Janet | [README.md](README.md), [docs/janet_app_spec.json](docs/janet_app_spec.json) |
| Decisions | [docs/DECISIONS.md](docs/DECISIONS.md) |
| What is next | [docs/BACKLOG.md](docs/BACKLOG.md) |
