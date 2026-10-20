# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/sweep_guard.py
#
# A SWEEP THAT SCANNED NOTHING MUST NOT PASS.
#
# WHY THIS EXISTS (owner 2026-09-22: "some of the gate tests are actually not that useful").
#
#   A property sweep has one shape across this whole fleet: walk a tree, collect the offenders,
#   assert the list is empty.
#
#       offenders = []
#       for path in (REPO / root).rglob("*.py"):
#           ...
#       self.assertEqual(offenders, [])
#
#   An EMPTY scan and a CLEAN scan produce the identical assertion. Rename a directory,
#   restructure a package, move a tree, run the suite from the wrong working directory, and the
#   gate goes on passing while checking nothing at all.
#
#   MEASURED 2026-09-22, on the real gate, not a constructed example:
#   data_library `tests/test_browser_mode.py::TestNobodyReadsItBehindTheResolversBack
#   ::test_no_module_reads_a_headed_or_headless_env_var_directly` sweeps six directories.
#
#       as shipped                                  PASS
#       ROOTS = ('directory_that_does_not_exist',)   PASS   <- scanned zero files
#
#   Across the fleet, 60 of 60 tree-walking sweeps had this shape. That is this fleet's OWN
#   number-one named fault class — "a failure and an honest empty look identical" — living
#   inside the gate tests written to enforce it. The sweeps themselves are careful work; what
#   they were missing is the one assertion that cannot be made from inside the loop.
#
#   The pattern was already here ONCE, hand-written, in the toolbox's own
#   `tests/test_teams_index.py::test_the_gate_is_reading_something`:
#   "A sweep that parses nothing passes both assertions above vacuously."
#   That is exactly right, and it is why this is a shared helper rather than a new idea — a
#   discipline that lives in one test is a habit, and a habit only works while someone remembers.
#
# WHAT IT DOES NOT DO, deliberately.
#
#   * It does NOT check that the tree is COMPLETE. The floor answers "did I scan the tree at
#     all", not "is every file present". Those are different questions and conflating them gives
#     you a ratchet that fails on every legitimate file addition — a red light that is always on
#     is wallpaper, and this fleet has written that down twice.
#   * It does NOT replace the guard-bite. A sweep can scan six hundred files and still assert
#     nothing that would ever be false. The only proof a gate bites is breaking the thing it
#     guards and watching it go red. This helper removes one specific, mechanical, fleet-wide
#     blindness; it does not make a weak assertion strong.
#
# USAGE — `swept()` is the one to reach for:
#
#       from sweep_guard import swept
#       for path in swept((REPO / root).rglob("*.py"), 1, f"modules under {root}/"):
#           ...
#
#   Per ROOT, not per sweep, and that is load-bearing. A sweep over six roots where one has been
#   renamed still yields hundreds of files from the other five: the whole-sweep count stays
#   healthy while the biggest tree goes unswept. A floor per root catches the partial collapse,
#   which is the failure that actually happens during a refactor.
#
# Stdlib only, no pytest import: this is checked out into repos that run unittest (Herdity) as
# well as pytest, and it raises plain AssertionError, which both report the same way.
# ============================================================================
"""Refuse a property sweep that scanned nothing. See the header for the measurement."""
from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Optional, Sequence, TypeVar

__all__ = ["assert_swept", "swept", "SweptNothing", "report", "main"]

T = TypeVar("T")


class SweptNothing(AssertionError):
    """Raised when a sweep scanned fewer items than its floor.

    An AssertionError subclass so unittest and pytest both report it as a failing assertion
    rather than an error, and so `except AssertionError` in a caller still behaves.
    """


def assert_swept(n: int, minimum: int = 1, what: str = "items", hint: str = "") -> int:
    """Assert a sweep actually scanned something. Returns `n` so it can be used inline.

    `minimum` is a FLOOR, never an exact count. Set it well below today's number: its job is to
    catch a tree that has moved or vanished, not to pin a total that grows every week.
    """
    if not isinstance(n, int) or n < 0:
        raise ValueError(f"a scan count must be a non-negative int, got {n!r}")
    if minimum < 1:
        # A floor of zero is not a weaker guard, it is the absence of one — and it reads in the
        # source as though a guard is present, which is worse than having none at all.
        raise ValueError(
            "minimum must be at least 1: a floor of 0 passes on an empty scan, which is the "
            "exact failure this helper exists to catch")
    if n < minimum:
        raise SweptNothing(
            f"THE SWEEP DID NOT SCAN ENOUGH TO MEAN ANYTHING: found {n} {what}, expected at "
            f"least {minimum}.\n"
            f"This gate's 'no offenders' result is therefore vacuous — it did not look. "
            f"Usually the tree moved, was renamed, or the suite is running from a different "
            f"working directory than the sweep assumes."
            + (f"\n{hint}" if hint else ""))
    return n


def swept(items: Iterable[T], minimum: int = 1, what: str = "items",
          hint: str = "") -> List[T]:
    """The items to sweep, refusing to hand back a scan that found fewer than `minimum`.

    Returns a LIST, and the check fires BEFORE the caller's loop body runs. That is deliberate
    and it is the whole design:

        for path in swept(root.rglob("*.py"), 20, "modules"):
            ...

    A lazy counting wrapper that asserted on exhaustion would be the more elegant object and the
    wrong one — a loop that `break`s early, `return`s on the first offender, or raises would
    never exhaust it, so the guard would silently not fire in precisely the runs that matter.
    That is the same shape as the bug this module exists to remove, one level up.
    """
    collected = list(items)
    assert_swept(len(collected), minimum, what, hint)
    return collected


def _iter_guarded(items: Iterable[T], minimum: int, what: str) -> Iterator[T]:  # pragma: no cover
    """Intentionally absent from __all__ and unused. See `swept`'s docstring for why a lazy
    guard is the wrong shape; this stub exists so nobody adds one without reading that."""
    raise NotImplementedError("use swept(): a lazy guard cannot fire on an early break")


#: a call with one of these names walks a directory
WALK_CALLS = frozenset({"rglob", "glob", "iglob", "walk", "iterdir", "scandir", "listdir"})
#: a module using one of these has a floor on what it scanned (this module's API)
FLOOR_CALLS = frozenset({"swept", "assert_swept"})


def _called_names(path: str) -> Optional[set]:
    """The names every call in `path` uses, or None when the file does not parse."""
    import ast
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError):
        return None
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def report(files: Sequence[str]) -> Dict[str, List[str]]:
    """{floored, walking, unread}: the test files that put a floor under a walk (`swept` /
    `assert_swept`), the ones that walk a directory without one, and the ones that did not parse."""
    out: Dict[str, List[str]] = {"floored": [], "walking": [], "unread": []}
    for p in files:
        names = _called_names(p)
        if names is None:
            out["unread"].append(p)
        elif names & FLOOR_CALLS:
            out["floored"].append(p)
        elif names & WALK_CALLS:
            out["walking"].append(p)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """`sweep_guard.py report <root>... [--list]`: the gate step that says how much it scanned.

    It replaces the copies janet_lite and data_library each kept in `scripts/gate_checks.py`
    (`sweeps`, fault hunt F008). Exit 1 when it read no test file, or when no test uses the floor
    at all (checked out and unused); 2 when run with no command, because a bare run checks
    nothing. The unfloored walkers are REPORTED, not failed: a walk over a temp dir and one over
    the repo tree look the same to this count.
    """
    import argparse
    import os
    import sys
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        # TB16: run bare this used to exit 0 having checked nothing.
        sys.stderr.write("sweep_guard is a library: import `swept` in a sweep test. Run bare it "
                         "checks nothing, so it exits 2 rather than reading as a pass. The gate "
                         "step is `sweep_guard.py report <test root>...`.\n")
        return 2
    ap = argparse.ArgumentParser(description="Report which test files floor their sweeps.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="walks vs floors over the test files under each root")
    rp.add_argument("roots", nargs="+", help="folders whose test files are read (recursive; "
                    "test_*.py and *_test.py, hidden folders skipped)")
    rp.add_argument("--list", action="store_true", help="name the unfloored walkers")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ambient_branch import test_files          # the one test-file finder in this bundle
    per_root = test_files(args.roots)
    files = sorted({f for fs in per_root.values() for f in fs})
    r = report(files)
    print(f"sweeps: read {len(files)} test file(s) under {len(per_root)} root(s); "
          f"{len(r['floored'])} put a floor under what they scanned (sweep_guard); "
          f"{len(r['walking'])} others walk a directory without one")
    print("        (a repo tree or a temp dir; this count cannot tell the two apart, so it is "
          "reported, not failed — `--list` names them)")
    for root, fs in per_root.items():
        if not fs:
            print(f"sweeps: {root}: no test file found there")
    if r["unread"]:
        print(f"sweeps: {len(r['unread'])} test file(s) did not parse: "
              + ", ".join(r["unread"][:5]))
    if args.list:
        for p in r["walking"]:
            print(f"  {p}")
    if not files:
        print("sweeps: read NOTHING — an empty scan is not a clean one")
        return 1
    if not r["floored"]:
        print("sweeps: no test uses sweep_guard's floor at all — it is checked out and unused")
        return 1
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
