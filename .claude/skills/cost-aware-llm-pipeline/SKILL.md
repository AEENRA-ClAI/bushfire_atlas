---
description: Keep local-brain calls cheap, bounded, and skippable — batch where possible, cache by content hash, put the deterministic/data ground ABOVE any model prose (so a call that adds nothing is cheap to omit), prefer a smaller model + a better prompt over a bigger model (prompt beats model size on our data), bound context and fan-out, and always degrade honest-empty when the brain is unavailable. Use when designing a flow, a persona node, an author-time enrichment pass, a RAG step, or any repeated/bulk LLM call. Enforces batching, content-hash caching, ground-first output, smallest-model-that-works, bounded context, and honest-empty fallback.
---

# Cost-aware LLM pipeline — the cheapest call is the one you don't make

**Owner:** `teams/harness-optimizer` — accountable that a repeated LLM step stays cheap and bounded on one self-hosted GPU: the local brain is a shared, finite resource, and a flow that hammers it per-row without caching or batching starves everything else on the box.

The only model is the local brain — one box, one GPU, shared across the fleet. It is not
metered by a vendor, but it is **finite**: every needless call is latency and contention taken
from another flow. Cost-awareness here isn't a billing concern, it's throughput discipline —
make each call earn its place, and make the pipeline correct (and useful) even when the brain
is down.

## The moves (cheapest first)
1. **Ground before you prompt.** Compute the deterministic data digest FIRST — the green table
   inventory, the row counts, the dossier facts — and put it **above** any model prose in the
   output. Two wins: the answer carries the real data even if the model adds nothing, and a
   node that would only restate the ground can **skip the call entirely**. The model is the
   optional garnish on a grounded reading, never the reading itself.
2. **Cache by content hash.** Key every call on a hash of (system prompt + user prompt + model
   + source digest). Same inputs → same answer, served from cache, no call. Cache negative
   results too (an empty answer is a result). An author-time pass over hundreds of dossiers
   re-runs only the ones whose inputs changed.
3. **Batch where the shape allows.** One call over N grounded chunks beats N calls; embed in
   batches; fan a flow's independent nodes out concurrently but **bound the fan-out** so you
   don't queue fifty prompts at the one GPU at once.
4. **Smallest model that clears the bar.** Prompt beats model size on our data — a strict,
   well-shaped prompt takes a small model to the same hit-rate as a large one, and a
   synthesise-vs-abstain instruction is the whole difference in RAG. **Tune the prompt before
   reaching for a bigger model.** Pick the model with the eval grid, not by reputation.
5. **Bound the context.** Retrieve top-k and pass only those chunks — never the whole layer.
   A tighter, grounded context is cheaper AND more accurate than a big vague one; unbounded
   context is the silent cost.

## Designing a flow / node for cost
- Give each node a **data source** and let its deterministic digest stand as the answer's
  floor. A node with no model still completes carrying its reading.
- Make the persona prompt do the work: specific, grounded, abstain-friendly. A better prompt
  removes retries and lets a smaller model serve.
- Set the fail-closed verify gate to read the **ground**, so an empty/duplicative model answer
  is caught cheaply rather than re-generated hopefully.
- Never put an LLM call on a hot request path — author-time (hub, cached) or on explicit demand,
  not per page-load.

## Honesty guards
- **Ground above prose, always.** The deterministic reading is the load-bearing part; the model
  is optional. This is what makes a call skippable AND keeps the output honest.
- **Honest-empty when the brain is down.** Every call degrades to "" / the deterministic digest,
  never an error and never a cloud fallback. The pipeline produces its data reading regardless.
- **Cache is content-addressed, not time-based.** Re-run only what changed; an mtime or a
  blanket "refresh all" throws away the savings and hammers the GPU for nothing.
- **Measure model choice, don't assume it.** "It needs the big model" is a claim for the eval
  grid to settle, not a default — most of the time it doesn't.
- **Offline-first.** All of this runs on the box against local material; the brain is additive,
  bounded, and never on the critical path for a consumer read.

## What to hand back
The call budget for the step (how many calls, batched how, over what bounded context), the cache
key and what invalidates it, where the deterministic ground sits relative to the model prose (it
must be above), the model chosen and the eval evidence that a smaller one suffices, and the
brain-down behaviour of each call.
