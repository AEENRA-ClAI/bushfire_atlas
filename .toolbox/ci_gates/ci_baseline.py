# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/ci_baseline.py   (checked out to each repo as .toolbox/ci_gates/)
#
# THE SUITE IS NOT GREEN, AND A GATE THAT DEMANDS GREEN WOULD BE IGNORED BY FRIDAY.
#
# Measured 2026-09-15: 49 failed / 4827 passed. Those 49 are real, pre-existing, and none of them
# is this session's to fix. A CI job that runs `pytest` and fails the build would be red on its
# first run and red on every run after, and the only thing it would teach anyone is to stop reading
# it. A red light that is always on is not a gate, it is wallpaper.
#
# So the gate is the one this repo already uses by hand and that has caught two real regressions a
# count comparison missed: DIFF THE FAILURE LIST. Not "how many failed" — *which* failed. 49 → 50
# tells you nothing (one fixed, two broken reads identically); the diff names the test in one line.
#
#   python .toolbox/ci_gates/ci_baseline.py                 # run the suite, diff the baseline
#   python .toolbox/ci_gates/ci_baseline.py --update         # re-baseline (DELIBERATE — see below)
#   python .toolbox/ci_gates/ci_baseline.py --paths .        # janet_lite: tests live beside the code
#   python .toolbox/ci_gates/ci_baseline.py --from-file out.txt   # diff an existing log, don't re-run
#
# WHICH PATHS ARE COLLECTED IS PART OF THE GATE, NOT A DETAIL. A bare `pytest` in data_library
# sweeps stray test files under examples/, framework/ and tools/ and dies with nine COLLECTION
# errors before a single test in tests/ runs — a suite that never ran reads as a suite with nine
# problems. `--paths` defaults to `tests`, which is that repo's documented command; janet_lite,
# whose tests sit beside the code as *_test.py, passes `--paths .`. Set it to whatever the repo's
# own README says to run, and nothing else.
#
# Exit 1 if any test fails that the baseline does not already record. Exit 0 otherwise — and it
# still PRINTS the ones your branch fixed, so the baseline can be trimmed on purpose.
#
# Three things it deliberately does, each of them learned here:
#
# * `--update` is never automatic. `pipeline_watch` makes the same call and states the reason: a
#   watcher that re-baselines itself can never report the same regression twice, and quietly
#   normalises a decline. Re-baselining is a human saying "yes, that one is known".
#
# * A MISSING DEPENDENCY IS DIAGNOSED BEFORE ANYTHING IS BLAMED ON THE CODE. Measured at the
#   2026-09-14 cleanup: the suite read 49 failed / 4054 passed, and installing bs4 + scikit-learn
#   took the same tree to 4 failed / 4269 passed. FORTY-FIVE of the forty-nine were two absent
#   packages — and they did not announce themselves, they failed on `assert 0 == 4` and
#   `None has no attribute 'get'`, which reads exactly like a regression in the code that had just
#   merged. A baseline that is red for an environment reason teaches a session to distrust the
#   baseline. So `ModuleNotFoundError` in the output is reported FIRST, as its own verdict, with
#   the missing module named — an environment problem said out loud is not a code problem.
#
# * The baseline records a COLLECTION ERROR as well as a failure. A module that cannot be imported
#   contributes no FAILED lines at all, so a suite that stops collecting a whole file would
#   otherwise look like a suite that got better.
# ============================================================================
"""ci_baseline — has this branch introduced a test failure the baseline does not already record?"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import List, Optional, Set, Tuple

# The repo under test, NOT this file's location: the script ships as a checked-out copy inside
# `.toolbox/ci_gates/`, so deriving the root from `__file__` would point at the checkout dir.
DEFAULT_BASELINE = os.path.join("tests", "ci_baseline_failures.txt")

# `FAILED tests/x.py::test_y - SomeError: detail` → keep the nodeid, drop the detail. The detail
# changes with unrelated edits (a repr, a path, a line number) and would churn the baseline without
# telling anyone anything.
_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+.*)?$")
# Quoted in a ModuleNotFoundError ("No module named 'bs4'"), BARE when the interpreter itself
# cannot find a -m target ("python: No module named pytest"). The bare form is the one that let
# a run that never started read as a pass (TB8, MEASURED in janet_lite 2026-09-21).
_MISSING_MOD_RE = re.compile(r"No module named '?([A-Za-z0-9_.]*[A-Za-z0-9_])'?")
# pytest's closing line: "4827 passed, 18 skipped in 113.94s", "1 failed, 2 errors in 0.3s",
# "no tests ran in 0.01s".
_SUMMARY_PART_RE = re.compile(
    r"^(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected|rerun)$")
_RAN = {"passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed"}
_NO_TESTS_RAN_RE = re.compile(r"^=*\s*no tests ran\b", re.M)


def parse_failures(output: str) -> Set[str]:
    """The set of failing/erroring test nodeids in a pytest run's output.

    Reads the `short test summary info` lines, which pytest emits for both FAILED and ERROR. An
    ERROR nodeid may be a bare module path (a collection error) rather than a `::test` id — that is
    kept as-is on purpose, because "this file no longer imports" is exactly the regression that a
    failure-count comparison cannot see.
    """
    out: Set[str] = set()
    for line in output.splitlines():
        m = _FAILED_RE.match(line.strip())
        if m:
            out.add(m.group(1))
    return out


def missing_modules(output: str) -> Set[str]:
    """Modules the run could not import. An environment verdict, never a code verdict."""
    return set(_MISSING_MOD_RE.findall(output))


def tests_collected(output: str) -> Optional[int]:
    """How many tests pytest's closing summary says it ran (passed + failed + errors + skipped …).

    None means no summary line was found at all (a trimmed log, or a run that died before it could
    print one); 0 means pytest said so ("no tests ran"). Neither is a pass on its own."""
    if _NO_TESTS_RAN_RE.search(output):
        return 0
    for line in reversed(output.strip().splitlines()):
        body = line.strip().strip("=").strip().split(" in ")[0]
        parts = [_SUMMARY_PART_RE.match(x.strip()) for x in body.split(",")]
        if body and all(parts):
            return sum(int(m.group(1)) for m in parts if m.group(2) in _RAN)
    return None


def read_baseline(path: str) -> Optional[Set[str]]:
    """The committed baseline, or None if there is none. None is NOT an empty baseline: an absent
    file means the gate cannot answer, and a gate that cannot answer must say so rather than pass."""
    if not os.path.isfile(path):
        return None
    out: Set[str] = set()
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def write_baseline(failures: Set[str], path: str) -> None:
    header = [
        "# The KNOWN-FAILING tests in this repo, as measured, one nodeid per line.",
        "#",
        "# This is not a wish list and not a to-do list: it is a record of what was already red when",
        "# the gate was put in, so that CI can answer the only question that is actionable on a pull",
        "# request — did THIS change break something. Every line here is a real failure somebody",
        "# should eventually fix; none of them is a reason to block an unrelated branch.",
        "#",
        "# MEASURE IT WHERE THE GATE RUNS. A baseline is environment-specific, and not only in the",
        "# obvious way: a test that asserts an ABSENCE (\"honest-empty offline\", \"no browser\") passes",
        "# on a machine that happens to lack the thing and FAILS on one that has it, and a timing",
        "# assertion passes on an idle box and fails on a shared runner. Measured 2026-09-15: three",
        "# data_library tests are red on a GitHub runner and green in the dev container, purely",
        "# because the runner has real network egress and a real Chrome. None is a regression.",
        "# So a baseline taken locally can be WRONG for CI. The workflow uploads the current failure",
        "# list as a `failures` artifact on every run — that file is the corrected baseline.",
        "#",
        "# Refresh it deliberately, never automatically:",
        "#     python .toolbox/ci_gates/ci_baseline.py --update",
        "# (`pipeline_watch --save-baseline` is the same rule for the same reason: a watcher that",
        "# re-baselines itself can never report the same regression twice.)",
        "#",
        f"# {len(failures)} known failure(s).",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(header))
        fh.write("\n".join(sorted(failures)))
        fh.write("\n")


# pytest's own exit codes. 0 and 1 are the two we can reason about; everything else means the RUN
# is not a run, and its (empty) failure list must never be compared against a baseline.
_PYTEST_OK, _PYTEST_TESTS_FAILED = 0, 1
_PYTEST_BROKEN = {
    2: "the run was INTERRUPTED — most often a COLLECTION ERROR aborting the session,\n        sometimes a Ctrl-C or a plugin. Read the tail below for the import that failed",
    3: "pytest hit an INTERNAL ERROR",
    4: "pytest was given BAD ARGUMENTS — check --paths and anything passed through",
    5: "NO TESTS WERE COLLECTED — --paths almost certainly points somewhere with no tests",
}


def run_suite(paths: List[str], extra: List[str], root: str) -> Tuple[str, int]:
    """Run pytest in `root` over `paths`; return (combined output, exit code).

    The exit code is NOT cosmetic and must not be dropped. A run that dies before collecting
    anything — a usage error, an interrupt, zero tests found — produces NO `FAILED` lines at all.
    Compared against a baseline that lists four, an empty failure set reads as "this branch fixed
    all four" and the gate returns 0. A broken run would pass, loudly congratulating you. That is
    the silent-failure shape this whole repo is built to refuse, so the code is read and acted on.
    """
    cmd = ([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
           + list(paths) + list(extra))
    print(f"$ {' '.join(cmd)}   (in {root})", flush=True)
    # encoding= is NOT optional beside text=True: it decodes with the LOCALE codec, cp1252
    # on the owner's Windows console, while every report in this fleet is UTF-8.
    # data_library gates this with a sweep (test_subprocess_decodes_utf8) after it was
    # reintroduced twice — but that sweep does not scan `.toolbox/`, so the CHECKED-OUT
    # copy of this very file was out of its reach. Found 2026-09-22.
    proc = subprocess.run(cmd, cwd=root, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.stdout + proc.stderr, proc.returncode


def compare(current: Set[str], baseline: Set[str]) -> Tuple[Set[str], Set[str]]:
    """(new, fixed) — what this branch broke, and what it repaired."""
    return current - baseline, baseline - current


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate on NEW test failures, not on a green suite.")
    ap.add_argument("--root", default=".", help="the repo under test (default: the current directory)")
    ap.add_argument("--paths", nargs="+", default=["tests"],
                    help="what to collect — this repo's own documented test command (default: tests)")
    ap.add_argument("--baseline", default=None,
                    help=f"the baseline file, relative to --root (default: {DEFAULT_BASELINE})")
    ap.add_argument("--update", action="store_true",
                    help="rewrite the baseline from this run (a deliberate human act)")
    ap.add_argument("--from-file", default=None,
                    help="read an existing pytest log instead of running the suite")
    ap.add_argument("--out", default=None,
                    help="also write the current failure list here (CI uploads it as an artifact)")
    ap.add_argument("pytest_args", nargs="*", help="extra args passed through to pytest")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    baseline_path = os.path.join(root, args.baseline or DEFAULT_BASELINE)

    if args.from_file:
        # A log read from disk carries no exit code; treat it as a completed run, because the only
        # caller that does this is a human diffing a log they already looked at.
        output, rc = open(args.from_file, encoding="utf-8", errors="replace").read(), _PYTEST_OK
    else:
        output, rc = run_suite(args.paths, args.pytest_args, root)

    # Always show the tail so a CI log is readable without downloading anything.
    tail = output.strip().splitlines()[-1:] or ["(no summary line)"]
    print("\n".join(tail))

    current = parse_failures(output)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(current)) + "\n")

    # ---- THE ENVIRONMENT VERDICT COMES FIRST, and it is not a code verdict ----
    #
    # Before the exit-code check, deliberately. MEASURED on this gate's own first CI run
    # (2026-09-15): a single missing `requests` broke collection, pytest exited 2, and the exit-code
    # branch below reported "the run was INTERRUPTED (Ctrl-C, or a plugin aborted it)" — true of the
    # exit code and useless to the reader, while the actual cause sat unmentioned in the tail. A
    # missing package EXPLAINS a broken run; a broken run does not explain a missing package. So the
    # more specific verdict is the one that gets to speak.
    missing = missing_modules(output)
    if missing:
        print("\n=== ENVIRONMENT, NOT CODE ===")
        print("The run could not import: " + ", ".join(sorted(missing)))
        if rc not in (_PYTEST_OK, _PYTEST_TESTS_FAILED):
            print(f"(pytest exited {rc} — the import failure is why; nothing was collected.)")
        print("An absent package does not announce itself as one. It fails as `assert 0 == 4` and")
        print("`None has no attribute 'get'`, i.e. exactly like a regression in whatever merged most")
        print("recently — and a baseline that is red for an environment reason teaches everyone to")
        print("distrust the baseline. Install the missing package(s) and re-run BEFORE attributing")
        print("any of this to the code.")
        print("\nIf the suite genuinely cannot run without it, the dep belongs in requirements.txt")
        print("AND in the CORE list in .claude/hooks/session_bootstrap.sh, which is what CI installs.")
        print("\n--- last 40 lines ---")
        print("\n".join(output.strip().splitlines()[-40:]))
        return 1

    # ---- a run that is not a run is reported as such, before any list is compared ----
    if rc in _PYTEST_BROKEN or rc not in (_PYTEST_OK, _PYTEST_TESTS_FAILED):
        why = _PYTEST_BROKEN.get(rc, f"pytest exited {rc}, which is not a result this gate can read")
        print(f"\n=== THE SUITE DID NOT RUN (pytest exit {rc}) ===")
        print(why)
        print("No failure list was produced, so there is nothing to compare. This is NOT a pass:")
        print("an empty failure list against a populated baseline would otherwise read as 'this")
        print("branch fixed everything'. Fix the run, then re-run the gate.")
        print("\n--- last 40 lines ---")
        print("\n".join(output.strip().splitlines()[-40:]))
        return 1

    # ZERO TESTS COLLECTED IS FATAL (TB8). Exit 1 stays allowed, because a genuinely failing
    # suite returns it too, so the exit code alone cannot catch a run that never started. What
    # can: a summary that says nothing ran, or no summary AND no failure lines at all.
    collected = tests_collected(output)
    if collected == 0 or (collected is None and not current):
        print("\n=== THE SUITE DID NOT RUN (zero tests collected) ===")
        print("pytest's summary says no test ran" if collected == 0 else
              "There is no pytest summary line and no FAILED/ERROR line in this output, so no test "
              "can be shown to have run.")
        print("An empty failure list against a populated baseline would otherwise read as 'this")
        print("branch fixed everything'. Fix the run (is pytest installed? do --paths hold tests?),")
        print("then re-run the gate.")
        print("\n--- last 40 lines ---")
        print("\n".join(output.strip().splitlines()[-40:]))
        return 1

    if args.update:
        write_baseline(current, baseline_path)
        print(f"\nBaseline REWRITTEN: {len(current)} known failure(s) → "
              f"{os.path.relpath(baseline_path, root)}")
        print("Commit it, and say in the commit message why each newly-recorded failure is known.")
        return 0

    baseline = read_baseline(baseline_path)
    if baseline is None:
        print(f"\nNo baseline at {os.path.relpath(baseline_path, root)} — the gate cannot answer.")
        print("Seed it with:  python .toolbox/ci_gates/ci_baseline.py --update")
        return 1

    new, fixed = compare(current, baseline)

    if fixed:
        print(f"\n=== FIXED by this branch ({len(fixed)}) — trim these from the baseline ===")
        for nid in sorted(fixed):
            print("  " + nid)

    if new:
        print(f"\n=== NEW failures ({len(new)}) — not in the baseline ===")
        for nid in sorted(new):
            print("  " + nid)
        print("\nThese are this change's to fix. If one is genuinely pre-existing and was simply")
        print("not running before, record it on purpose:")
        print("  python .toolbox/ci_gates/ci_baseline.py --update")
        return 1

    print(f"\nNo new failures. ({len(current)} failing, all {len(baseline)} known.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
