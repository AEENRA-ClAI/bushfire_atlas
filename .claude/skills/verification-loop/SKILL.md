---
description: A grounded self-check pass run AFTER any LLM-authored or derived write - re-read the output against ONLY the source material, flag every claim the source doesn't support, and demand "not disclosed" over a plausible-but-unsourced statement. Use after authoring a dossier, an analysis, a sector narrative, a summary, or any generated/derived artifact before it ships; whenever a write needs to be trusted; or as the verify gate in a flow. Enforces claim-by-claim grounding, fail-closed (what you cannot confirm STANDS as a problem), findings as `- [SEVERITY] …`, and that the author is never the one who clears their own work.
---

# Verification loop — check the write against its source, fail closed

**Owner:** `teams/verifier` — the verify gate before a verdict; it does not hunt for new problems, it takes the output and tries to DISPROVE that every claim is sourced, and what it cannot disprove stands.

Anything the local brain writes, or any derived layer computes, looks confident whether or
not the source supports it. The verification loop is the pass that separates "we wrote this"
from "the source says this." It runs **after** the write and **before** it ships — re-reading
the output against ONLY the material it was built from. It is the app's grounding rule made
into a gate; smart_analyst reads **read-only** and the loop never edits the source, it judges
the output against it.

## What to do
1. **Fix the source set.** Name exactly what the write was allowed to draw from — the specific
   green rows, the dossier corpus, the RAG chunks. The loop reads THAT and nothing else. A
   claim justified by "general knowledge" is unsourced by definition.
2. **Go claim by claim.** Decompose the output into its individual factual claims — every
   figure, date, name, and asserted relationship. Treat each as a hypothesis to disprove.
3. **Find the support, or fail it.** For each claim, locate the source line that carries it —
   quote it. A claim you can point to a source for **passes**. A claim the source doesn't
   support, or that you cannot check, **fails** — the gate is fail-closed; a doubt is not a
   clearance.
4. **Demand "not disclosed" over the plausible completion.** The dangerous claim is the one
   that is *reasonable* but unsourced — a rounded figure, an inferred date, a "likely"
   attribution. These are the loop's main catch: they must be rewritten to "not disclosed" or
   dropped, never left standing because they sound right.
5. **Report, don't fix.** The loop flags; the author (or the derive step) repairs. The one who
   made the claim is not the one who clears it.

## The findings shape (pairs with the flows verify gate)
Emit one line per claim examined, so the gate can read it and fail closed on any blocker:

```
- [CRITICAL] "<the claim>" — no support in source; the dossier corpus does not state this.
- [HIGH] "$700M capex" — figure not in the source rows; plausible but unsourced → "not disclosed".
- [MEDIUM] "since 2019" — date inferred from phrasing, not stated; mark not disclosed.
- [OK] "<the claim>" — supported: <short quote from the source row / key>.
```

Severity is honest (critical / high / medium / low / ok). **Any unresolved CRITICAL or HIGH
fails the write** — it does not ship until repaired and re-run. Uncertainty never clears a
finding; what you cannot affirmatively confirm STANDS.

## Honesty guards
- **Fail closed.** "Probably fine", "can't check", "likely sourced" all resolve to STANDS, not
  cleared. The gate protects the reader, not the author's throughput.
- **Source-only.** Confirm claims against the named source set alone — never against the
  verifier's own knowledge, which would launder an unsourced claim into a passed one.
- **Grounding is the rule being enforced.** The whole loop exists to make "not disclosed" beat
  a plausible invention; a plausible-but-unsourced statement is a *failure*, not a pass.
- **Offline-first.** The check is a re-read against local material; it needs no network and no
  cloud model, and runs whether or not the brain that authored the write is up.
- **Separation of duties.** The author never clears their own output — the verifier is a
  distinct seat precisely so a finding survives a challenge it didn't write.

## What to hand back
The findings list (`- [SEVERITY] "<claim>" — <support or why it fails>`), the count of
unresolved CRITICAL/HIGH (the fail-closed verdict), and the specific rewrites demanded —
each plausible-but-unsourced claim marked for "not disclosed" or removal — so the write is
repaired and re-run, not shipped on assertion.
