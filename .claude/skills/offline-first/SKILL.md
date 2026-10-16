---
description: The build-and-review discipline for the deployed box — which blocks CDNs, has no cloud, and may be air-gapped. Vendor EVERY third-party asset locally (never a CDN script, stylesheet, font, map tile, or runtime fetch), treat the self-hosted local brain as the ONLY model (degrade honest-empty when it's down), make no external network call at runtime in a consumer app, and fall back gracefully when an optional external resource is absent. Use when building, changing, or reviewing anything the box actually serves — a page, a map, a chart, a reader, an LLM call. Enforces vendored assets, no-CDN, local-brain-only, honest-empty degradation, and offline-provable behaviour.
---

# Offline-first — the box has no internet, prove it still works

**Owner:** `teams/harness-optimizer` — accountable that a feature runs on an air-gapped box exactly as it does on a networked laptop: nothing it needs leaves the machine, and everything optional degrades to a labelled empty state instead of a blank or a hang.

The deployed box blocks CDNs (banks block them too), often has no cloud reachability, and may
be fully air-gapped. A feature that "works on my laptop" because it quietly pulls a script, a
font, or a model from the internet is **broken on the box** — and the failure is invisible: a
blank widget, a spinner that never resolves, an empty-looking panel that is actually a dead
fetch. Offline-first is the rule that a thing the box serves depends on **nothing beyond the
box** to render its core, and names every optional extra as optional.

## The rules
1. **Vendor every third-party asset.** Map library, chart library, fonts, icons, basemap
   outlines — copied INTO the app and served from it, pinned to a version, with its licence.
   **Never a CDN** `<script src>`, `<link href>`, `@font-face` URL, or map-tile URL. A CDN is
   a runtime dependency on the internet; the box doesn't have one.
2. **The local brain is the only model.** Every LLM call goes to the self-hosted brain (Ollama
   over the LAN) through the one shared client — **never a cloud model, never a hand-rolled
   HTTP call, never a key.** When the brain is down the call returns honest-empty (""), not an
   error and not a fallback to some cloud endpoint.
3. **No external fetch at runtime in a consumer app.** A spoke reads shared green + the
   dossiers (local, read-only) and derives its answer. It does not scrape, probe, geocode, or
   call an API at request time. Any external resolution the answer needs was done **at
   author-time by the hub** and shipped as a local sidecar (the hub has network; the box
   doesn't) — the app reads the sidecar as a local read.
4. **Draw the fallback locally.** Where an external resource is genuinely optional — external
   map tiles, a live feed — it is **off by default**, gated behind an explicit opt-in env flag,
   and there is a locally-drawn fallback that renders when it's absent (land outlines instead of
   tiles, a graticule instead of a grid). A watchdog that sees zero external responses falls
   back on its own; an air-gapped box degrades, it never blanks.
5. **Honest-empty over blank.** Every reader and widget degrades to a **labelled** empty state
   with a note ("not connected", "brain offline", "no tiles — showing local basemap") — never a
   blank box a viewer can't tell from a bug.

## Reviewing a change for offline-safety
- Grep the diff for `http`, `cdn`, `fonts.googleapis`, `unpkg`, `jsdelivr`, tile URLs, and any
  cloud-LLM host. Each hit is guilty until shown to be vendored or hub-author-time only.
- Ask of each asset: **if the box had no internet right now, would this render?** If the answer
  needs the network, it's not done — vendor it or move it to author-time.
- Ask of each LLM call: does it go through the shared brain client, and what does it return when
  the brain is down? If the answer is "an exception" or "a cloud fallback", fix it.
- Ask of each panel: what does a viewer see when the source isn't connected? A labelled empty
  state passes; a blank or a spinner fails.

## Honesty guards
- **Vendored, not linked.** An asset the box serves lives in the app, pinned + licensed. A CDN
  reference is a bug even if it works on the laptop today.
- **Local brain or nothing.** No cloud model, ever — degrade honest-empty when the local brain
  is unreachable; the deterministic reads still answer.
- **Author-time is the hub's job.** External resolution (geocoding, enrichment, LLM authoring)
  happens once on the networked hub and ships as a local sidecar — the consumer app never
  fetches at runtime (Rules 2, 6, 12 of the data library).
- **Prove it offline.** The bar is "renders its core with the network unplugged," not "works
  here." If you can't demonstrate that, you haven't met the rule.

## What to hand back
The list of third-party assets the change introduces and where each is vendored (path +
version + licence), confirmation that every LLM call goes through the shared brain client and
its brain-down behaviour, any external resource named with its opt-in flag AND its local
fallback, and the offline check: what a viewer sees for each panel with the network unplugged.
