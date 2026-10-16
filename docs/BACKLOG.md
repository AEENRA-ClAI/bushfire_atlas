# Backlog

The next steps, in order.

| id | item | depends on |
|---|---|---|
| BA1 | First live run: Qfd_BushfireAlert green lands in data_library, and the app shows real Queensland events on the box. Check the row key against the real `map_layers/Qfd_BushfireAlert.geojson` (docs/features/linking.md UNVERIFIED) | data_library builds Qfd_BushfireAlert from its discovery run |
| BA2 | Each state's source arrives as data_library builds it (NSW RFS, VIC, WA, SA, TAS, ACT, NT, and the GA burnt-area extents). No app change is expected; confirm each by its row in the Sources table | data_library's bushfire build (D28) |
| BA3 | The 15-minute live poll is in data_library (D31), not here. Once it runs, check how fresh the newest record is against the poll | data_library D31 |
| BA4 | Tune the link distance, gap and unknown reach on real fires: count events that should have merged and events that should not | BA1 |
| BA5 | Compare polygons by their real geometry from `map_layers`, not the bbox, when the bbox test over-merges | BA1, real polygons |
| BA6 | Subscribe to the toolbox `instincts` bundle, for the fleet session workflow, merge guard and handover tools | toolbox manifest change |
| BA7 | A "fire danger" layer for ratings, which are not events today and are only counted | a fire_danger source in green |
| BA8 | Place a FIRMS detection by state polygon, not a box; this would also close the gap at PNG's south coast | a vendored state boundary layer |
