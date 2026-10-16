# -*- coding: utf-8 -*-
"""Inject the fleet's learned instincts at session start.

Self-contained (stdlib only) and shipped INSIDE the `instincts` checkout bundle, so an app's
SessionStart hook runs the checked-out copy:

    python .toolbox/instincts/inject.py --scope smart_analyst

It reads `instincts.json` beside it, keeps the instincts scoped to this app (or "all") whose
confidence clears the threshold, and prints the top few as a compact markdown block for the session
to start with. Honest-empty: no store, or nothing above the bar, prints nothing (exit 0) — a memory
layer must never be the thing that breaks a session.

Env knobs (mirrors the ECC shape):
    INSTINCT_CONFIDENCE_THRESHOLD   float, default 0.7 — only inject instincts at/above this
    MAX_INJECTED_INSTINCTS          int,   default 6   — cap what a session starts with
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _threshold() -> float:
    try:
        return float(os.environ.get("INSTINCT_CONFIDENCE_THRESHOLD", "0.7"))
    except ValueError:
        return 0.7


#: How many instincts the SessionStart block prints. 7, not 6, since 2026-09-15: the set of
#: 0.95-confidence entries reached SIX, so a cap of six excluded every 0.90 entry outright — the
#: fake-time-axis warning fell out the moment one more 0.95 was added, which is the cap silently
#: deciding what the fleet remembers rather than confidence deciding it. The env var stays as the
#: override, but the DEFAULT is what a SessionStart hook actually gets (hub Rule 12b: an
#: automation has no environment), so the default is the number that matters.
#: 8 since 2026-10-03: `stored-text-is-data-not-instructions` (the owner's security rule) took a
#: new slot rather than evicting a 0.90 entry from every scope.
_DEFAULT_CAP = 8


def _cap() -> int:
    try:
        return max(0, int(os.environ.get("MAX_INJECTED_INSTINCTS", str(_DEFAULT_CAP))))
    except ValueError:
        return _DEFAULT_CAP


def load(path: str | None = None) -> list[dict]:
    """The instincts list, or [] — never raises (a memory layer degrades to empty)."""
    p = path or os.path.join(_HERE, "instincts.json")
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = data.get("instincts") if isinstance(data, dict) else None
    return out if isinstance(out, list) else []


def select(instincts: list[dict], *, scope: str = "", threshold: float | None = None,
           cap: int | None = None) -> list[dict]:
    """The instincts to inject: in scope (this app or 'all'), at/above the confidence bar, the most
    confident first, capped. Pure and deterministic."""
    thr = _threshold() if threshold is None else threshold
    lim = _cap() if cap is None else cap
    picked = []
    for it in instincts:
        if not isinstance(it, dict):
            continue
        try:
            conf = float(it.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < thr:
            continue
        scopes = it.get("scope") or ["all"]
        if isinstance(scopes, str):                 # tolerate a malformed string scope (robustness)
            scopes = [scopes]
        if scope and "all" not in scopes and scope not in scopes:
            continue
        picked.append({**it, "confidence": conf})
    picked.sort(key=lambda i: i["confidence"], reverse=True)
    return picked[:lim] if lim else picked


def eligible(instincts: list[dict], *, scope: str = "",
             threshold: float | None = None) -> list[dict]:
    """Every in-scope instinct at or above the bar — the same set `select` picks from, UNCAPPED.

    Exists so the cap can be REPORTED rather than applied in silence. `select(…, cap=0)` is the
    same thing and reads as a magic number at the call site.
    """
    return select(instincts, scope=scope, threshold=threshold, cap=0)


def render(picked: list[dict], n_eligible: int | None = None) -> str:
    """The SessionStart block. When `n_eligible` says more cleared the bar than fitted, the
    block SAYS SO.

    THE CAP HAD BEEN SILENTLY DECIDING WHAT THE FLEET REMEMBERS, twice. The docstring on
    `_DEFAULT_CAP` records the first time: six 0.95 entries filled a cap of six, so every 0.90
    entry fell out at once and the fake-time-axis warning vanished from every session. It
    happened again on 2026-09-22 — five 0.95 plus two 0.90 fill the cap of seven exactly, so a
    new 0.85 instinct is written into the store and reaches nobody.

    Raising the cap only moves the cliff. Saying where the cliff IS costs one line and is this
    fleet's own top instinct (`honest-empty-says-why`) applied to the memory layer itself: a
    shortened list that does not admit it is shortened reads exactly like a complete one.
    """
    if not picked:
        return ""
    lines = ["## Fleet instincts (learned — hold these)"]
    for it in picked:
        action = str(it.get("action") or "").strip()
        if not action:
            continue
        lines.append(f"- **{it.get('id', '?')}** ({it['confidence']:.2f}) — {action}")
    if len(lines) == 1:
        return ""
    if n_eligible is not None and n_eligible > len(picked):
        lines.append(
            f"- _({n_eligible - len(picked)} more cleared the bar but did not fit the cap of "
            f"{len(picked)} — `python .toolbox/instincts/inject.py --list` for all of them.)_")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# --what-if — what does promoting this actually COST?
#
# The curation gate is deliberately human, but until 2026-09-16 it was also blind. "Raise it above
# 0.7 and append it" reads as though promotion is additive. It is not: every entry in the store
# already clears 0.7 (the lowest is 0.85) and the cap is 7, so a promotion is a SWAP, and which
# entry it swaps out is not visible anywhere in the file.
#
# It is also not one entry. `select()` filters by SCOPE before it applies the cap, so each repo has
# its own last-through-the-gate. Answering "what does this displace" therefore meant copying the
# store, appending the candidate and running this script once per repo — enough work that nobody
# would do it before a decision, which is the same as not being able to answer.
# --------------------------------------------------------------------------- #

def fleet_scopes() -> list[str]:
    """Every app the toolbox knows about, read from `manifests/`.

    The store is NOT a sufficient source for this. `toolbox` and `herdity` are named in no
    instinct's scope — they only ever receive the "all" entries — so a scope list derived from the
    store alone silently omits the two repos where a promotion still costs something.

    Empty when this is the CHECKED-OUT copy inside an app repo, which has no `manifests/`; the
    caller falls back to the store's own scopes there.
    """
    mdir = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "manifests")
    try:
        return sorted(n[: -len(".manifest.json")] for n in os.listdir(mdir)
                      if n.endswith(".manifest.json"))
    except OSError:
        return []


def scopes_in(instincts: list[dict]) -> list[str]:
    """The named app scopes present in the store. "all" is not one — it is every scope at once."""
    out = set()
    for it in instincts:
        if not isinstance(it, dict):
            continue
        scopes = it.get("scope") or ["all"]
        if isinstance(scopes, str):
            scopes = [scopes]
        out.update(s for s in scopes if s and s != "all")
    return sorted(out)


def unknown_scopes(instincts: list[dict]) -> dict:
    """`{scope_token: [instinct ids]}` for scope values that are neither "all" nor a known app.

    `select()` matches a scope token literally against `"all"` or the app name, so a token like
    `"*"` — which READS as a wildcard and is not one — matches nothing and the instinct injects
    into no repo at all. It is not filtered out or rejected anywhere; it simply never appears,
    which is the same silent-inert failure the cap produces, arriving by a different door.
    """
    known = set(fleet_scopes()) | set(scopes_in(instincts)) | {"all"}
    # An app named in a manifest is known; a token that is ONLY ever used as a scope and matches
    # no manifest is suspicious, but only definitively wrong when no manifest list is available
    # to check against. Be conservative: report only when we have a manifest list to judge by.
    apps = set(fleet_scopes())
    if not apps:
        return {}
    bad: dict = {}
    for it in instincts:
        if not isinstance(it, dict):
            continue
        scopes = it.get("scope") or ["all"]
        if isinstance(scopes, str):
            scopes = [scopes]
        for s in scopes:
            if s and s != "all" and s not in apps:
                bad.setdefault(s, []).append(it.get("id", "?"))
    return bad


def what_if(instincts: list[dict], candidates: list[dict], *, scopes: list[str] | None = None,
            threshold: float | None = None, cap: int | None = None,
            cap_after: int | None = None) -> list[dict]:
    """Per scope, what the SessionStart block becomes if `candidates` joined the store.

    `leaves` is the answer the curation gate needs and could not get: the entries that are injected
    today and would not be. `inert` is the other half — a candidate that clears the bar and still
    does not appear, which is the outcome that LOOKS like a decision and changes nothing.

    `cap_after` exists because **the baseline has to be today.** "Raise the cap to 9 and promote
    both" compared against "raise the cap to 9 and promote nothing" reports 8 evictions, which is
    true and useless: nobody is proposing the second state, and it is not what anyone is running.
    Compared against what is ACTUALLY injected right now — cap 7, nothing promoted — the same
    change evicts nothing and adds two. Getting this wrong is easy and it inverts the answer, so
    the before-cap and the after-cap are separate parameters rather than one.
    """
    cand_ids = [c.get("id") for c in candidates]
    cap_after = cap if cap_after is None else cap_after
    rows = []
    # Prefer the manifest list when we have it: it is the real set of repos, and it excludes a
    # junk token like "*" that only LOOKS like a scope. Fall back to the store in a checked-out
    # copy, which has no manifests to read.
    apps = fleet_scopes()
    default_scopes = apps or scopes_in(instincts)
    for sc in (scopes if scopes is not None else default_scopes):
        before = [i["id"] for i in select(instincts, scope=sc, threshold=threshold, cap=cap)]
        after = [i["id"] for i in select(instincts + candidates, scope=sc,
                                        threshold=threshold, cap=cap_after)]
        eligible = [i["id"] for i in select(instincts + candidates, scope=sc,
                                           threshold=threshold, cap=0)]
        rows.append({
            "scope": sc,
            "before": before,
            "after": after,
            "enters": [i for i in after if i not in before],
            "leaves": [i for i in before if i not in after],
            "inert": [c for c in cand_ids if c in eligible and c not in after],
            "out_of_scope": [c for c in cand_ids if c not in eligible],
            "eligible": len(eligible),
            "shown": len(after),
        })
    return rows


def render_what_if(rows: list[dict], bad_scopes: dict | None = None) -> str:
    out = []
    if bad_scopes:
        out.append("!! %d instinct(s) carry a scope that matches NO repo, so they inject nowhere:"
                   % sum(len(v) for v in bad_scopes.values()))
        for tok, ids in sorted(bad_scopes.items()):
            out.append("     scope %r — %s" % (tok, ", ".join(ids)))
        out.append("   `select()` matches a scope token literally against \"all\" or an app name, so")
        out.append("   \"*\" reads as a wildcard and is not one. Curation decision, not a bug to")
        out.append("   silently rewrite — see docs/CIRCLE_BACK.md.")
        out.append("")
    total_leaves = 0
    for r in rows:
        out.append("## %s  — %d of %d eligible shown" % (r["scope"], r["shown"], r["eligible"]))
        for i in r["enters"]:
            out.append("  + ENTERS   %s" % i)
        for i in r["leaves"]:
            out.append("  - LEAVES   %s" % i)
        for i in r["inert"]:
            out.append("  ! INERT    %s — clears the bar, still below the cap: promoting it here "
                       "changes nothing" % i)
        for i in r["out_of_scope"]:
            out.append("    n/a      %s — not in this scope, or below the threshold" % i)
        if not (r["enters"] or r["leaves"] or r["inert"]):
            out.append("    (no change)")
        total_leaves += len(r["leaves"])
        out.append("")
    out.append("%d entr%s would stop being injected across %d scope(s)."
               % (total_leaves, "y" if total_leaves == 1 else "ies", len(rows)))
    return "\n".join(out)


def parse_candidate(spec: str) -> dict:
    """`id=confidence` or `id=confidence@scope1,scope2` (default scope: all).

    Deliberately not JSON on the command line: the question is asked in a shell, and quoting a JSON
    object in a shell is enough friction to stop it being asked. `--what-if-file` takes the store's
    own shape, so a paste-ready block from CIRCLE_BACK.md can be tried verbatim.
    """
    body, _, scopes = spec.partition("@")
    iid, sep, conf = body.partition("=")
    iid, conf = iid.strip(), conf.strip()
    if not iid or not sep or not conf:
        raise ValueError("expected id=confidence[@scope,scope], got %r" % spec)
    try:
        c = float(conf)
    except ValueError:
        raise ValueError("confidence must be a number, got %r" % conf) from None
    sc = [s.strip() for s in scopes.split(",") if s.strip()] or ["all"]
    return {"id": iid, "action": "(candidate)", "confidence": c, "scope": sc}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inject the fleet's learned instincts.")
    ap.add_argument("--scope", default="", help="this app (e.g. smart_analyst); keeps its + 'all'")
    ap.add_argument("--list", action="store_true", help="list every instinct, ignore the cap")
    ap.add_argument("--json", action="store_true", help="emit the selected instincts as JSON")
    ap.add_argument("--what-if", action="append", default=[], dest="what_if", metavar="ID=CONF[@SCOPES]",
                    help="what promoting this candidate would ADD and what it would EVICT, per "
                         "scope (repeatable). The cap makes promotion a swap, not an addition.")
    ap.add_argument("--what-if-file", default="", dest="what_if_file", metavar="PATH",
                    help="the same, for candidates in the store's own JSON shape")
    ap.add_argument("--what-if-cap", type=int, default=None, dest="what_if_cap", metavar="N",
                    help="evaluate the candidates against a DIFFERENT cap (e.g. 9), comparing "
                         "against what is injected today — the answer to 'raise the cap first?'")
    args = ap.parse_args(argv)
    instincts = load()

    if args.what_if or args.what_if_file:
        candidates = []
        for spec in args.what_if:
            try:
                candidates.append(parse_candidate(spec))
            except ValueError as exc:
                print("inject: --what-if %s" % exc, file=sys.stderr)
                return 2
        if args.what_if_file:
            try:
                with open(args.what_if_file, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                # NOT honest-empty: an unreadable candidates file is the caller's own question
                # going unanswered, and answering "no change" would be a lie.
                print("inject: cannot read %s (%s)" % (args.what_if_file, exc), file=sys.stderr)
                return 2
            rows = data.get("instincts") if isinstance(data, dict) else data
            candidates += [c for c in (rows or []) if isinstance(c, dict) and c.get("id")]
        if not candidates:
            print("inject: no candidates to test", file=sys.stderr)
            return 2
        scopes = [args.scope] if args.scope else None
        result = what_if(instincts, candidates, scopes=scopes, cap_after=args.what_if_cap)
        bad = unknown_scopes(instincts)
        if args.json:
            print(json.dumps({"scopes": result, "unknown_scopes": bad}, indent=2))
        else:
            print(render_what_if(result, bad))
        return 0

    # --list means EVERY instinct: bypass the confidence bar and the cap, not just the cap.
    picked = select(instincts, scope=args.scope,
                    threshold=(0.0 if args.list else None),
                    cap=(0 if args.list else None))
    if args.json:
        print(json.dumps(picked, indent=2, ensure_ascii=False))
    else:
        text = render(picked, n_eligible=len(eligible(instincts, scope=args.scope)))
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
