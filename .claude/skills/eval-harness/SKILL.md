---
description: Stand up a model × prompt evaluation grid over a VERIFIED reference set before trusting a prompt, a model choice, or a flow — three modes (delta = numeric extraction vs a known value, judge = grounded generation vs a curated reference, qa = a question set answered per entity), resumable per item, with honest metrics and prompt-vs-model attribution. Use when deciding "does this prompt actually work / is this model good enough / did that change help", when picking the smallest model that clears the bar, or when regression-testing a flow. Complements the flows agent-evaluator. Enforces a verified truth set, no leakage, grounded/local-brain-only scoring, resumability, and honest reporting.
---

# Eval harness — measure the prompt and the model, don't vouch for them

**Owner:** `teams/mle-reviewer` — accountable that "this prompt/model works" is a measured claim against a verified reference set, with the credit correctly assigned to the prompt or the model — not a vibe from reading a few outputs.

Whether a prompt or a model is good enough is a question with a number, and the number comes
from running it against material where the right answer is already known. The eval harness is
that grid — models on one axis, prompts on the other, a verified reference set underneath — so
a change to either is a measured delta, not an impression. It runs on the local brain (sweep
several local models in one pass), stays grounded, and never lets the thing under test see the
answer.

## The three modes
- **delta** — numeric extraction vs a **human-verified value**. Score the model's extracted
  figure against the known truth (exact / within-tolerance). This is the cleanest signal: a
  small verified gold set (a dozen rows) discriminates prompts and models sharply.
- **judge** — grounded generation vs a **curated reference** (a dossier, an analysis). The
  output is scored for faithfulness to the source, not fluency. The judge is **optional** — run
  collect-only (no judge model set) and score the outputs **in a chat** against the reference
  that already exists, so no cloud key is ever needed.
- **qa** — a fixed **question set** answered per entity, grounded in that entity's material,
  scored for correctness + honest-empty ("not disclosed" where the source is silent counts as
  right, an invented answer counts as wrong).

## Standing one up
1. **Pin the truth set.** A small, verified reference — a value, a curated write-up, a question
   bank with expected answers. Adding a dataset should be adding a **spec** (a registry entry),
   not code. The truth set is fixed before any model runs.
2. **Separate the axes.** Vary model and prompt independently so a result attributes to the
   right one. The headline finding on our data is that **prompt beats model size** — you only
   learn that if the grid can hold the model fixed and sweep the prompt.
3. **Resume per item.** Each (model, prompt, item) cell is checkpointed; a re-run skips done
   cells and fills only the gaps. A long sweep survives interruption.
4. **Score honestly.** delta = numeric hit-rate (and on the clean subset separately — don't let
   dirty rows hide a good prompt); judge = grounded faithfulness; qa = correct-including-honest-
   empty. Report the metric AND the n it's over.
5. **Attribute.** Read the grid down columns and across rows: which prompt lifted every model,
   which model a good prompt made unnecessary. That's the actionable output — "ship this prompt,
   the small model is fine."

## No leakage — the cardinal rule
The thing under test must never see the answer. The reference value is scored **against**, never
fed **into**, the prompt. A qa answer key is checked after generation, not shown before. A judge
scores an output it did not help write. Leakage turns a 95% into a lie; guard it like the verify
gate guards grounding.

## Honesty guards
- **Verified truth or no eval.** A grid over unverified "expected" answers measures agreement,
  not correctness. The reference must be human-checked.
- **Local brain only.** Sweep local models; the optional judge is optional precisely so the grid
  runs offline with no cloud key — collect-only + score-in-chat is a first-class mode.
- **Honest-empty is a right answer.** "Not disclosed" where the source is silent scores as
  correct; a plausible invention scores as wrong. The eval rewards grounding, matching the app's
  rule.
- **Report n and the metric, not a headline.** "77% over 14 rows" is honest; "works great" is
  not. Small n is fine — say it's small.
- **Complements the flow evaluator.** The flows agent-evaluator judges one run's output; this
  grid judges the prompt/model choice across many items. Use the grid to pick, the evaluator to
  gate.

## What to hand back
The truth set and mode used (delta / judge / qa) with its n, the model × prompt grid of scores,
the attribution (which prompt / which model to ship, and the evidence a smaller model suffices),
confirmation of no leakage, and any cells that failed or couldn't be scored — named, not
silently dropped.
