# -*- coding: utf-8 -*-
"""Read the fault ledger and say what keeps going wrong, and whose it is.

    python .toolbox/instincts/fault_report.py
    python .toolbox/instincts/fault_report.py --repo Herdity --json

The ledger (`fault_ledger.json`) is the record; this is the read of it a session actually looks
at. Worst first: a class that has bitten at or above the promotion threshold and still has NO
detector is the headline, because that is a fault the fleet keeps paying for with nothing
standing in its way.

It REPORTS and never writes. Stdlib only, honest-empty (no ledger -> nothing, exit 0): a memory
layer must never be the thing that breaks a session.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def load(path: str | None = None) -> dict:
    """The ledger, or {} — never raises."""
    p = path or os.path.join(_HERE, "fault_ledger.json")
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def promote_at(ledger: dict) -> int:
    try:
        return int(ledger.get("promotion_ladder", {}).get("promote_at", 3))
    except (TypeError, ValueError):
        return 3


def rank(ledger: dict, repo: str = "") -> list[dict]:
    """Classes worst-first: needs-a-mechanism before watched before closed, then by count.

    `repo` filters to classes with an occurrence in that repo (or fleet-wide ones), so a spoke
    can ask "what keeps biting ME" without reading the other four repos' history.
    """
    out = []
    for c in ledger.get("classes", []) or []:
        if not isinstance(c, dict):
            continue
        occ = [o for o in (c.get("occurrences") or []) if isinstance(o, dict)]
        if repo:
            if not any(o.get("repo") in (repo, "fleet") for o in occ):
                continue
        n = len(occ)
        needs = n >= promote_at(ledger) and not c.get("detector") and c.get("status") != "closed"
        out.append({**c, "n": n, "needs_mechanism": needs})
    # sort: needs-mechanism first, then most-bitten, then id (stable and reproducible)
    out.sort(key=lambda c: (not c["needs_mechanism"], -c["n"], c.get("id", "")))
    return out


def render(ledger: dict, repo: str = "") -> str:
    rows = rank(ledger, repo)
    if not rows:
        return ""
    thr = promote_at(ledger)
    n_occ = sum(r["n"] for r in rows)
    scope = f" in {repo}" if repo else ""
    lines = [f"## Recurring faults{scope} — {len(rows)} classes, {n_occ} recorded occurrences",
             ""]
    needs = [r for r in rows if r["needs_mechanism"]]
    if needs:
        lines += [f"**{len(needs)} at or past the promotion threshold ({thr}) with NO mechanism.** "
                  "These are what the fleet keeps paying for:", ""]
    for r in rows:
        mark = "🔴" if r["needs_mechanism"] else ("🟡" if r.get("status") != "closed" else "✅")
        det = r.get("detector") or ("— none" if r.get("status") != "closed" else "")
        lines.append(f"{mark} {r.get('id','?')}  ×{r['n']}  {r.get('title','')}")
        lines.append(f"     owner: {r.get('owner','UNROUTED')}   detector: {det}")
        if r.get("note"):
            lines.append(f"     note: {r['note']}")
    unc = ledger.get("unclassified") or []
    lines += ["", f"Unclassified faults on file: {len(unc)}"
                  + ("  (a taxonomy's blind spot is only visible if it is counted)" if unc else "")]
    if needs:
        lines += ["", "Next: the owning specialist builds the mechanism, then the fault-analyst "
                      "closes the class naming it — and the gate-auditor checks it bites."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--repo", default="", help="only classes that have bitten this repo")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ledger = load(args.ledger)
    if not ledger:
        print("no fault ledger found — nothing to report", file=sys.stderr)
        return 0
    if args.json:
        json.dump(rank(ledger, args.repo), sys.stdout, indent=2)
        print()
        return 0
    text = render(ledger, args.repo)
    print(text if text else "the fault ledger holds no classes yet")
    return 0


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(main())
