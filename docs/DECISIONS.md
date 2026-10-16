# Decisions

The owner's decisions that shape this app. They were taken in data_library and are recorded
there in `docs/DECISIONS.md`. Each row here says how the app keeps it.

| id | date | decision | how this app keeps it | source |
|---|---|---|---|---|
| D27 | 2026-10-15 | "Just Australia … make a list of the sources, all of them". The bushfire build covers every Australian source. Global fire datasets are parked; FIRMS already covers hotspots | The app reads Australian jurisdictions only. A worldwide feed (FIRMS) is cut to Australia before it is linked (`atlas/green.py in_australia`) | data_library docs/DECISIONS.md D27 |
| D28 | 2026-10-15 | "Every source": a pipeline for every machine-readable Australian bushfire source | The app finds its sources by looking: any green folder carrying the contract's columns is read, so each new pipeline appears with no change here | data_library D28 |
| D29 | 2026-10-15 | The bushfire app is a new app repo that reads the hub's green and is run by Janet | This repo. It is read-only over green (a spoke), runs under Janet (`docs/janet_app_spec.json`), and never fetches a source | data_library D29 |
| D30 | 2026-10-15 | "Can we standardize on geospatial data instead of ids". Records are linked by place and time; ids are provenance only | `atlas/linker.py`. An event id comes from its earliest member's place and time, and an agency id is shown, never compared | data_library D30; docs/features/linking.md |
| D31 | 2026-10-16 | "Yes, 15 min": the live feeds are polled every 15 minutes | The polling is the hub's. The app re-reads a green file when its mtime changes and re-lists green every `BUSHFIRE_SCAN_SECONDS` (300 s) | data_library D31 |
