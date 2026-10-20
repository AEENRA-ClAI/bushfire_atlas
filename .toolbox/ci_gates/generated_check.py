# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/generated_check.py
#
# A GENERATED FILE MUST MATCH ITS BUILDER.
#
# WHY (CIRCLE_BACK "Nothing gates a GENERATED file", 2026-09-16). `verify_checkout.py` watches
# checked-out files; nothing watched a generated one. data_library's
# `catalog/corporate_questionnaire.json` had been hand-edited downstream of its generator
# (`scripts/build_corporate_questionnaire.py`), and the next rebuild would have wiped the edit
# without a word. A deterministic builder can be re-run and its output compared, so it should be.
#
# HOW. Each repo lists its builders in `config/generated_files.json`:
#
#     {"builders": [
#       {"output": "catalog/corporate_questionnaire.json",
#        "check":  ["scripts/build_corporate_questionnaire.py", "--check"]},
#       {"output": "tools/device_fleet/data/region_terms.json",
#        "build":  ["-m", "tools.device_fleet.build_region_terms",
#                   "../data_library/catalog/society_search_terms.json"],
#        "needs":  ["../data_library/catalog/society_search_terms.json"]}]}
#
#   * `check`  the builder's own verify mode: exit 0 = in date, anything else = stale.
#   * `build`  a builder with no verify mode: the output's bytes are kept, the builder runs, the
#              new bytes are compared, and the kept bytes are put back WHATEVER happened, so the
#              check never leaves the tree changed.
#   * `needs`  inputs that live outside this repo (a sibling checkout). When one is absent the
#              entry is NOT RUN, said by name; it is never read as in date.
#
#   An argv starting with a `.py` path or `-m` is run with this Python.
#
# EXIT. 0 every builder in date · 1 any stale or failed · 2 no list, an unreadable list, or an
# empty one (nothing was checked, so no verdict) · 75 nothing stale but some entry could not run
# here (the fleet gates print 75 as "not run", neither ok nor FAIL).
# ============================================================================
"""Re-run each declared builder and fail on a GENERATED file that no longer matches it."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

__all__ = ["DEFAULT_CONFIG", "NOT_RUN", "load", "check_entry", "main"]

DEFAULT_CONFIG = os.path.join("config", "generated_files.json")
#: EX_TEMPFAIL: "could not run here", the same code the fleet gates print as "not run"
NOT_RUN = 75


def load(path: str) -> Optional[List[Dict[str, Any]]]:
    """The declared builders, or None when the file is missing or will not parse."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    rows = data.get("builders") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else None


def _argv(cmd: List[str]) -> List[str]:
    first = cmd[0] if cmd else ""
    return [sys.executable, *cmd] if first == "-m" or first.endswith(".py") else list(cmd)


def _read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _restore(path: str, kept: Optional[bytes]) -> None:
    if kept is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "wb") as fh:
        fh.write(kept)


def check_entry(entry: Dict[str, Any], root: str, run=subprocess.run) -> Dict[str, str]:
    """{output, verdict: ok|STALE|FAILED|NOT RUN|BAD ENTRY, why}."""
    out = str(entry.get("output") or "")
    if not out or bool(entry.get("check")) == bool(entry.get("build")):
        return {"output": out or "?", "verdict": "BAD ENTRY",
                "why": "an entry needs an `output` and exactly one of `check` / `build`"}
    missing = [p for p in entry.get("needs") or [] if not os.path.exists(os.path.join(root, p))]
    if missing:
        return {"output": out, "verdict": "NOT RUN",
                "why": "input not on this machine: " + ", ".join(missing)}
    if entry.get("check"):
        r = run(_argv(entry["check"]), cwd=root, capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return {"output": out, "verdict": "ok" if r.returncode == 0 else "STALE",
                "why": f"`{' '.join(entry['check'])}` exit {r.returncode}: {tail[0]}"}
    target = os.path.join(root, out)
    kept = _read(target)
    try:
        r = run(_argv(entry["build"]), cwd=root, capture_output=True, text=True)
        built = _read(target)
    finally:
        _restore(target, kept)
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        return {"output": out, "verdict": "FAILED",
                "why": f"the builder exited {r.returncode}: {tail[0]}"}
    if kept is None:
        return {"output": out, "verdict": "STALE", "why": "the committed file is missing"}
    if built != kept:
        return {"output": out, "verdict": "STALE",
                "why": "the builder's output differs from the committed file (hand-edited, or "
                       "the inputs moved): re-run the builder and commit"}
    return {"output": out, "verdict": "ok", "why": "rebuilt byte-identical"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="the repo root (default: the current folder)")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help=f"the builder list, relative to --root (default {DEFAULT_CONFIG})")
    a = ap.parse_args(argv)
    path = os.path.join(a.root, a.config)
    rows = load(path)
    if rows is None:
        print(f"generated_check: {path} is missing or unreadable — nothing was checked, "
              f"so no verdict")
        return 2
    if not rows:
        print(f"generated_check: {path} declares no builder — nothing was checked, so no verdict")
        return 2
    results = [check_entry(e if isinstance(e, dict) else {}, a.root) for e in rows]
    for r in results:
        print(f"  {r['verdict']:9s} {r['output']}  — {r['why']}")
    bad = [r for r in results if r["verdict"] in ("STALE", "FAILED", "BAD ENTRY")]
    skipped = [r for r in results if r["verdict"] == "NOT RUN"]
    ok = len(results) - len(bad) - len(skipped)
    print(f"generated_check: {ok} in date, {len(bad)} stale or failed, {len(skipped)} not run, "
          f"of {len(results)} declared")
    if bad:
        return 1
    return NOT_RUN if skipped else 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
