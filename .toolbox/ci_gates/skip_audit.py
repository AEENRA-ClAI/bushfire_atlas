# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/skip_audit.py
#
# A SKIP IS INVISIBLE IN THE SUMMARY LINE. THIS MAKES EACH ONE DECLARE ITSELF.
#
# WHY (owner 2026-09-22, "now do the skip audit"). The third part of the
# gate-that-cannot-bite class, after the empty-scan guard and the neuter-bite.
#
#   Ran 2985 tests ... OK (skipped=18)
#
# Reads as a pass. TWELVE of those eighteen were three missing packages — tests that had never
# run in that container at all (Herdity, 2026-09-21). A skip is indistinguishable from a pass in
# the summary, and worse than a failure, because a failure at least gets looked at.
#
# MEASURED across the fleet 2026-09-22 — fourteen skips, and only four of them are fine:
#
#   data_library    2   one data (green holds no country= partitions), one deliberate
#   Herdity        11   eight data (no herd / no green checked out), ONE ENVIRONMENT
#                       ("playwright absent" — pip install playwright takes that file from
#                       "Ran 16, skipped 1" to "Ran 17, OK"; it had never run anywhere),
#                       two deliberate
#   janet_lite      1   INVERTED: "a browser IS available here" — it runs only where a browser
#                       is ABSENT, so on this container and on the box it never runs at all
#   smart_analyst   0
#   toolbox         0
#
# WHAT IT REFUSES, and the kinds are the whole design — an undeclared skip FAILS, and two of
# the four declared kinds fail as well:
#
#   environment  the bootstrap CORE should have supplied this. The test has never run.  FAILS
#   forceable    the condition could be FORCED (monkeypatch the flag) instead of skipped, so
#                the skip is hiding a test that could run everywhere.                   FAILS
#   data         off-repo data, honestly absent in a lean clone.                         ok
#   deliberate   a real reason, written down.                                            ok
#
# `data` is allowed but is NOT a free pass: a repo with a data-checkout hook should have run it.
# Herdity's `data_checkout.sh` needs HERDITY_PROFILE set, which a plain shell does not have — so
# eight of its eleven skips are recoverable in the very container that reports them.
#
# WHAT IT DOES NOT DO. It does not judge a reason it has never seen: an unmatched skip is
# reported as UNDECLARED and fails, rather than being guessed into a kind. Guessing is how a
# taxonomy's catch-all comes to carry 207 of 208 items.
#
#   python .toolbox/ci_gates/skip_audit.py --run            # run the suite, then audit
#   python .toolbox/ci_gates/skip_audit.py --from out.txt   # audit a run you already have
#   python .toolbox/ci_gates/skip_audit.py --run --list     # every skip, no verdict
#
# Stdlib only; parses BOTH pytest (`-rs`/`-ra`) and unittest (`-v`), because Herdity runs
# unittest (its Rule 10) and everything else runs pytest.
# ============================================================================
"""Refuse a skip nobody has declared. See the header for the measurement."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

__all__ = ["parse_skips", "reported_skips", "run_reported", "classify", "load_policy", "audit",
           "FAILING_KINDS", "KINDS"]

#: The four kinds a declared skip may claim. Two of them still fail.
KINDS = ("environment", "forceable", "data", "deliberate")
FAILING_KINDS = ("environment", "forceable")

DEFAULT_POLICY = os.path.join("tests", "skip_policy.json")

# pytest -rs / -ra:  "SKIPPED [1] tests/test_x.py:12: the reason"
# The `:\d+` is part of WHERE, not of the reason: a non-greedy path capture swallows the
# file and leaves "195: green holds no…" as the reason, which then never matches a policy
# rule written against the words.
_PYTEST_SKIP = re.compile(r"^SKIPPED\s+\[\d+\]\s+(\S+?:\d+):\s*(.*)$")
# unittest -v: "test_x (mod.Cls.test_x) ... skipped 'the reason'" — BUT when a test has a
# docstring, unittest prints the docstring's first line INSTEAD of the name, so the "where" is a
# sentence with spaces and no parenthesised module:
#     "End to end, not by inspection: a stored animal ... skipped 'no herd checked out here'"
# The first version of this anchored on `^(\S+)\s+\(`, which missed exactly those and
# UNDERCOUNTED a real run 7 against a reported 10 — an audit that silently misses skips is the
# fault it exists to catch. Anchor on the " ... skipped " separator instead; everything before it
# is the where, whatever shape it takes.
_UNITTEST_SKIP = re.compile(r"^(.*?)\s*\.\.\.\s*skipped\s+['\"](.*)['\"]\s*$")
# unittest -v, a setUpClass skip: "setUpClass (mod.Cls) ... skipped 'the reason'"
_UNITTEST_CLASS_SKIP = re.compile(r"^(setUpClass|setUpModule)\s+\(([^)]*)\)\s*\.\.\.\s*"
                                  r"skipped\s+['\"](.*)['\"]\s*$")


def parse_skips(output: str) -> List[Tuple[str, str]]:
    """[(where, reason)] from a pytest or unittest run. Order preserved, duplicates kept.

    Duplicates are KEPT on purpose: two tests skipping for the same reason is two tests not
    running, and collapsing them understates the coverage that is missing.
    """
    out: List[Tuple[str, str]] = []
    for line in output.splitlines():
        line = line.rstrip()
        m = _PYTEST_SKIP.match(line)
        if m:
            out.append((m.group(1), m.group(2).strip()))
            continue
        m = _UNITTEST_CLASS_SKIP.match(line)
        if m:
            out.append((f"{m.group(2)} ({m.group(1)})", m.group(3).strip()))
            continue
        m = _UNITTEST_SKIP.match(line)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


# "OK (skipped=10)" / "2 skipped" / "1354 passed, 1 skipped in 94s"
_REPORTED = (re.compile(r"\(skipped=(\d+)\)"), re.compile(r"(\d+)\s+skipped"))


def reported_skips(output: str) -> Optional[int]:
    """The skip count the RUNNER itself printed, or None when it printed none.

    The audit is only as good as its parser, so it checks itself against the runner's own
    number. Without this the first version read 7 skips from a run that reported 10 and said
    "every skip is declared" — the same silent shortfall it exists to refuse, one level up.
    """
    last = None
    for rx in _REPORTED:
        for m in rx.finditer(output):
            last = int(m.group(1))
        if last is not None:
            return last
    return None


_RAN = re.compile(r"\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed)\b|^Ran \d+ tests?\b"
                  r"|^(?:OK|FAILED)\b", re.M)


def run_reported(output: str) -> bool:
    """Did this output come from a run that actually ran tests? (TB16)

    An empty file, `No module named pytest`, or pytest's "no tests ran" carry no skip lines,
    so they used to audit as "no skips in this run." and exit 0: a run that never started read
    as a clean one. A real pytest or unittest run prints its counts; a skip line is proof too."""
    return bool(_RAN.search(output or "")) or bool(parse_skips(output or ""))


def load_policy(path: Optional[str] = None, root: str = ".") -> Dict:
    """The repo's declared skips, or {} — never raises."""
    p = path or os.path.join(root, DEFAULT_POLICY)
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def classify(reason: str, policy: Dict) -> Tuple[str, str]:
    """(kind, why) for one skip reason. ("undeclared", "") when no rule matches.

    Matching is a case-insensitive SUBSTRING, because a reason often carries a path or a count
    that varies between machines ("green at D:/… holds no country= partitions yet"). A regex
    would be more precise and would also let a policy entry quietly widen to match everything,
    which is the failure mode an allowlist has.
    """
    for rule in policy.get("allow", []) or []:
        if not isinstance(rule, dict):
            continue
        needle = str(rule.get("match") or "")
        if needle and needle.lower() in reason.lower():
            kind = str(rule.get("kind") or "")
            return (kind if kind in KINDS else "undeclared"), str(rule.get("why") or "")
    return "undeclared", ""


def audit(skips: List[Tuple[str, str]], policy: Dict) -> Tuple[List[Dict], bool]:
    """(rows, ok). `ok` is False when any skip is undeclared or of a failing kind."""
    rows, ok = [], True
    for where, reason in skips:
        kind, why = classify(reason, policy)
        bad = kind == "undeclared" or kind in FAILING_KINDS
        ok &= not bad
        rows.append({"where": where, "reason": reason, "kind": kind, "why": why, "bad": bad})
    return rows, ok


def run_suite(cmd: List[str], root: str) -> Tuple[str, int]:
    """Run the repo's own suite command and return its output.

    `encoding="utf-8"` is NOT optional beside `text=True`: that decodes with the LOCALE codec,
    cp1252 on the owner's Windows console, while every report in this fleet is UTF-8. It has
    been reintroduced three times now (read_feedback, pipeline_watch, and gate_bite on
    2026-09-22), which is why data_library gates it with a sweep.
    """
    print(f"$ {' '.join(cmd)}   (in {root})", flush=True)
    proc = subprocess.run(cmd, cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return (proc.stdout or "") + (proc.stderr or ""), proc.returncode


def render(rows: List[Dict], ok: bool, *, list_only: bool = False) -> str:
    if not rows:
        return "no skips in this run."
    lines = [f"{len(rows)} skip(s):", ""]
    for r in rows:
        mark = "  " if not r["bad"] else "✗ "
        lines.append(f"{mark}[{r['kind']:11s}] {r['where']}")
        lines.append(f"               {r['reason']}")
        if r["why"]:
            lines.append(f"               → {r['why']}")
    if list_only:
        return "\n".join(lines)
    bad = [r for r in rows if r["bad"]]
    lines.append("")
    if ok:
        lines.append("every skip is declared, and none of a kind that should not be a skip.")
    else:
        lines.append(f"{len(bad)} skip(s) must not stand:")
        for r in bad:
            if r["kind"] == "undeclared":
                lines.append(f"  · UNDECLARED — {r['reason']!r}. Add it to the skip policy with a "
                             f"kind and a reason, or stop skipping.")
            elif r["kind"] == "environment":
                lines.append(f"  · ENVIRONMENT — {r['reason']!r}. This test has NEVER RUN here. "
                             f"Add the dependency to the bootstrap CORE list.")
            else:
                lines.append(f"  · FORCEABLE — {r['reason']!r}. Force the condition (monkeypatch "
                             f"the flag) instead of skipping, so it runs everywhere.")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--policy", default=None, help="default: tests/skip_policy.json")
    ap.add_argument("--from", dest="from_file", default=None,
                    help="audit a run's output already on disk")
    ap.add_argument("--run", action="store_true", help="run the suite named in the policy")
    ap.add_argument("--list", action="store_true", help="every skip, no verdict (exit 0)")
    args = ap.parse_args(argv)

    policy = load_policy(args.policy, args.root)
    if not policy:
        print("skip_audit: no skip policy found — nothing declared, so nothing can be checked.\n"
              f"            Expected {args.policy or DEFAULT_POLICY} under {args.root}.",
              file=sys.stderr)
        return 2                      # honest: absent policy is NOT a pass

    if args.from_file:
        try:
            with open(args.from_file, encoding="utf-8", errors="replace") as fh:
                output = fh.read()
        except OSError as exc:
            print(f"skip_audit: cannot read {args.from_file}: {exc}", file=sys.stderr)
            return 2
    elif args.run:
        cmd = policy.get("suite_command")
        if not isinstance(cmd, list) or not cmd:
            print("skip_audit: the policy names no suite_command, so --run has nothing to run.",
                  file=sys.stderr)
            return 2
        cmd = [sys.executable if c == "python" else c for c in cmd]
        output, rc = run_suite(cmd, args.root)
        if rc not in (0, 1):
            # pytest 2-5 / an interpreter error: the suite did not run to the end, so its skips
            # cannot be the whole list (the return code used to be discarded, TB16).
            print(f"skip_audit: the suite exited {rc}, so it did not run to the end — no audit.",
                  file=sys.stderr)
            return 2
    else:
        output = sys.stdin.read()

    if not run_reported(output):
        print("skip_audit: THE RUN REPORTED NO TEST COUNTS (empty output, `No module named pytest`, "
              "or no tests ran), so there is nothing to audit and no verdict.", file=sys.stderr)
        return 2

    skips = parse_skips(output)
    rows, ok = audit(skips, policy)
    print(render(rows, ok, list_only=args.list))

    said = reported_skips(output)
    if said is not None and said != len(skips):
        print(f"\n✗ THE PARSER AND THE RUNNER DISAGREE: the run reported {said} skip(s), this "
              f"read {len(skips)}. The audit is incomplete — do not read the verdict above as "
              f"covering everything. Fix the parser before trusting it.", file=sys.stderr)
        return 1
    return 0 if (ok or args.list) else 1


if __name__ == "__main__":                                     # pragma: no cover
    raise SystemExit(main())
