# Linking records into fire events (D30)

*"Can we standardize on geospatial data instead of ids"* (owner, data_library D30, 2026-10-15).
Each state's agency numbers its incidents its own way, and a fire that crosses a border is two
incidents with two ids. So the app links records by **where** and **when**, and keeps each
agency's id only to show where a record came from.

## The rule (`atlas/linker.py`)

Two records are the same fire when both of these hold:

- **Place.** Their shapes come within `BUSHFIRE_LINK_DISTANCE_M` (3000 m) of each other.
  - A point is a circle of its `loc_precision_m`.
  - A point whose precision is unknown is a circle of `BUSHFIRE_UNKNOWN_PRECISION_M` (5000 m).
  - A circle record is its `radius_m`.
  - A polygon, line or raster cell is its green bbox.

  So the reach grows with how imprecise each record is. A FIRMS hotspot's precision is half its
  pixel's diagonal (`scan_km`, `track_km`).
- **Time.** Their windows overlap, or come within `BUSHFIRE_LINK_GAP_HOURS` (24 h) of each other.
  - A window runs from the source's start to its end.
  - When the source gives no start, the window starts at `rec_vld_dts`.
  - An open end is the latest time the source vouched for the record.

Linking is transitive. Every record is kept. A record that cannot take part is counted, never
dropped quietly:

- a record with no location is **unplaced**;
- a record with no time is **untimed**;
- a fire-danger rating or a statistic describes an area, not a fire, so it is **not an event**.

**The coarse index** proposes candidate pairs, and the exact gap decides.

- With the `h3` package installed, the index is H3 at resolution 7 (the contract's `h3_r7`).
- Without it, the index is a 0.05° lat/lon grid.
- A shape too big to index (over about 100 km) is compared with every record directly.

The tests run every case through both indexes and require the same events.

**Event id.** The id is built from the earliest member's start time (to the minute) and its
place (to 3 decimals), e.g. `20261015T1008Z_28.560S_151.970E`. It never contains an agency's id.
Two distinct fires with the same id get `-2`, `-3` in a stable order.

**An event shows:**

- its members;
- its jurisdictions, flagged **cross-border** when more than one STATE reports it (`AUS`, a
  national feed such as FIRMS, is not a state);
- when it was first and last seen;
- the highest controlled warning level (emergency_warning > watch_and_act > advice > information
  > none > unknown);
- the latest known status;
- the largest size an agency stated.

**Filters choose events and never cut them.** Linking runs on every record in the window before
any filter. A filter for "hotspot" shows the events that include a hotspot, with all their other
records.

## Evidence

- SIMULATED: `tests/test_linker.py` covers these constructed cases:
  - an NSW point and a VIC polygon of the same fire on the Murray, linked and flagged
    cross-border;
  - two fires 30 km apart, kept apart;
  - a Tasmanian 10 km circle that gathers the hotspots within reach and not the one 22 km away;
  - time gaps, transitive chains, an unknown precision, a 300 km polygon beyond the index;
  - stable ids, and H3 and the grid giving the same events.

  A mutation check was run: the tests fail when the place test, the time test, the state-only
  cross-border rule, the unknown-precision reach or the index footprint is broken.
- MEASURED: `scripts/browser_check.py` and `tests/test_green_and_app.py` run the real app on the
  constructed store (`scripts/make_fixture.py`).

## UNVERIFIED

- **Not yet run on real feeds.** No real bushfire green existed when this was written. The
  Qfd_BushfireAlert pipeline was a scaffold, so the first live run is the first real test.
- **The row key format.** The `row_key` that joins a `map_layers` feature to its green row is
  rendered by data_library's `pipelines/_bushfire_geo.py`, which had not landed. `atlas/layers.py`
  compares keys with punctuation stripped and tries the common timestamp renderings. Confirm it
  against the first real layer file.
- **The link distance, gap and unknown reach are judgements**, not measurements. Tune them on
  real fires.
- **Bboxes are coarse.** A polygon is compared as its bbox, so a large, irregular burnt area can
  catch a separate fire that sits inside its box but outside its edge.
- **Transitive chains can over-merge.** A dense line of hotspots between two fires joins them.
- **Placing FIRMS detections.** The app decides which detections are in Australia with a box,
  less Timor and the Lesser Sundas (`atlas/green.py in_australia`). A detection on PNG's south
  coast near Daru (about 9.1° S) can still get in.
