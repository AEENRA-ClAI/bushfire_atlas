# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/duration_budget_unittest.py
#
# THE SAME RECORDER, FOR A unittest SUITE.
#
# WHY THIS EXISTS. `duration_budget` is a pytest plugin, and Herdity runs
# `python -m unittest discover -s tests/unit_root_tests` (its Rule 10 — unittest is stdlib and
# this repo deliberately does not install pytest). So the one suite in the fleet that had
# actually blown up — 25,697s, 7.1 hours, MEASURED 2026-09-22 against 28.4s cold — was the one
# suite the cost tooling could not see.
#
# A limit stated in a handover is a limit somebody still has to work around. This closes it.
#
# ⚠ THAT 7.1 HOURS IS HISTORY, NOT A CURRENT FACT, and this line said otherwise for two days.
# MEASURED 2026-09-24 on the same repo, same profile, same 411 MB data branch checked out:
# **3,238 tests in 30.9s**. Herdity's B48 (`tests/support/external_root.py`, 2026-09-21) fixed
# the class of test responsible; the figure outlived the fault. It is worth more than a
# correction, because of what the stale number DID: it talked Herdity's gate out of wiring its
# own `--against` watch. A 7.1-hour run cannot fit a $500 cap and cannot afford a baseline
# run, so the first draft of that step shipped informational-only, with a careful
# justification resting entirely on a number nobody had re-measured. A stated duration has no
# mechanism keeping it true — re-measure before quoting this paragraph.
#
# WHAT IT DELIBERATELY DOES NOT DO: re-implement anything. It writes the IDENTICAL JSON shape,
# so `--plan`, `--hoist`, `--against` and the audit are the same code reading the same rows for
# both runners (fleet Rule 3 — one implementation, never a second copy that drifts). If the
# shape ever needs to change it changes in one place; a second analyser for unittest would be
# the exact fault this bundle keeps finding elsewhere.
#
#     python -m duration_budget_unittest discover -s tests/unit_root_tests
#     python duration_budget.py --from .duration_budget.json --hoist --against prev.json
#
# ============================================================================
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import duration_budget as db  # noqa: E402


class _RecordingResult(unittest.TextTestResult):
    """Times each test, and — the part that took work — SETUP separately from the test body.

    unittest's result hooks do not draw that line: `startTest` fires before `setUp` and
    `stopTest` after `tearDown`, so a naive timer reports one number for the lot and the
    fixture cost stays invisible. That is precisely the number the hoist detector needs, so
    measuring the whole thing would have shipped a recorder that cannot answer the question it
    was built for.

    The seam is that `TestCase.run()` calls `self.setUp()` — an attribute looked up on the
    INSTANCE at call time — and `startTest(test)` is handed that instance first. So the wrapper
    goes on the instance, is used exactly once, and nothing global is touched. It is restored
    in `stopTest` rather than left, because a TestCase instance can be re-run.

    Failures are recorded like anything else. A test that fails still SPENT its time, and a
    cost report that quietly drops the failures is measuring a run that did not happen.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []
        self._t0 = 0.0
        self._slept0 = 0.0
        self._setup = (0.0, 0.0)
        self._orig_setup = None

    def startTest(self, test):
        self._setup, self._orig_setup = (0.0, 0.0), test.setUp

        def _timed_setup(_orig=test.setUp):
            s0, sl0 = time.perf_counter(), db._SLEPT["total"]
            try:
                return _orig()
            finally:
                self._setup = (round(time.perf_counter() - s0, 3),
                               round(db._SLEPT["total"] - sl0, 3))

        test.setUp = _timed_setup
        self._t0, self._slept0 = time.perf_counter(), db._SLEPT["total"]
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        if self._orig_setup is not None:
            try:
                test.setUp = self._orig_setup
            except AttributeError:          # a test class that forbids attribute writes
                pass
            self._orig_setup = None
        setup_wall, setup_slept = self._setup
        total = time.perf_counter() - self._t0
        # The body is the whole thing MINUS setup, so `wall` means the same in both recorders.
        # Clamped at zero: on a coarse clock the two measurements can cross by a microsecond,
        # and a negative duration would poison every sum downstream.
        self.rows.append({
            "setup": setup_wall,
            "setup_slept": setup_slept,
            "nodeid": test.id(),
            "wall": round(max(0.0, total - setup_wall), 3),
            "slept": round(max(0.0, db._SLEPT["total"] - self._slept0 - setup_slept), 3),
        })


class _RecordingRunner(unittest.TextTestRunner):
    resultclass = _RecordingResult

    def run(self, test):
        real_sleep, db._SLEPT["total"] = time.sleep, 0.0
        time.sleep = db._accounting_sleep
        try:
            result = super().run(test)
        finally:
            time.sleep = real_sleep
        out = os.environ.get("DURATION_BUDGET_OUT", db.RECORD_DEFAULT)
        rows = getattr(result, "rows", [])
        try:
            # db.write_record, not a second json.dump: both recorders must stamp the file
            # identically, and the analyser reads ONE shape for both (fleet Rule 3).
            db.write_record(out, rows)
            sys.stderr.write(f"duration_budget: recorded {len(rows)} tests -> {out}\n")
        except OSError as e:
            # Loud, never silent: a recording that did not land makes the next step exit 2,
            # and the reader needs to know it was the WRITE that failed, not the run.
            sys.stderr.write(f"duration_budget: COULD NOT WRITE {out}: {e}\n")
        return result


def main(argv=None):
    """Run the suite, record it, and REPORT WHETHER IT PASSED.

    THIS RETURNED 0 UNCONDITIONALLY UNTIL 2026-09-24, and the bug is worth stating plainly
    because of where it was about to be installed. `unittest.main(..., exit=False)` does not
    exit, so the caller owns the exit code — and this returned `0` whatever happened. MEASURED
    on a two-test suite with one deliberate failure: plain `python -m unittest` exits 1, this
    recorder exited 0.

    Herdity's gate step is named "tests (must be GREEN)" and is the fleet's one hard green
    gate. Swapping the runner for this one would have turned that assertion into a vacuous
    pass — a gate that goes green on a red suite — which is the exact fault this bundle
    refuses next door in `ci_baseline.py` ("a pytest run that DIED is never read as a pass").
    A cost meter that silences the test result is worse than no cost meter.

    It shipped because `duration_budget_unittest` had NO TEST OF ITS OWN: the pytest half is
    covered by 71, this half by nothing, so the only property anyone had checked was that it
    writes a file. `tests/test_duration_budget_unittest.py` closes that.

    A run that collected NOTHING exits 2, not 0, for the same reason the analyser does: "no
    tests" and "all tests passed" are different facts, and `wasSuccessful()` answers True to
    an empty result.
    """
    argv = list(sys.argv if argv is None else argv)
    prog = unittest.main(module=None, argv=argv, testRunner=_RecordingRunner, exit=False)
    result = getattr(prog, "result", None)
    if result is None or getattr(result, "testsRun", 0) == 0:
        sys.stderr.write("duration_budget: NOTHING RAN — this is not a pass.\n")
        return 2
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
