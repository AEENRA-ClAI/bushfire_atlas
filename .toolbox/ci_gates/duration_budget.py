# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/duration_budget.py
#
# A TEST MAY BE SLOW. IT MAY NOT BE ASLEEP.
#
# WHY THIS EXISTS (owner 2026-09-23, on a $100-per-minute thought experiment:
# "you might think that those seconds do not repeat, but every single time that it runs,
# that's seconds and then seconds and then seconds that add up").
#
#   A one-off sixty-five seconds is nothing. Sixty-five seconds welded into a gate that runs
#   twice a session, in five repos, forever, is an annuity of waste — and it is invisible,
#   because a slow test does not fail. It passes. It just takes the money.
#
#   MEASURED 2026-09-23 on data_library, one full run: 409.15s over 7,061 tests.
#
#       top  1 test            65.59s   16.0% of the wall clock
#       top 10 tests          182.60s   44.6%
#       the other 7,021       103.40s   25.3%      (14.7 ms each)
#
#   So the intuition that a big suite is slow BECAUSE it is big is exactly wrong here. The
#   average test costs 15 milliseconds. Three tests cost 128.61 seconds — 31.4% of the run —
#   and not one of those seconds is spent computing anything.
#
#       test_honest_empty_offline[Usda_Wasde]   65.59s   launching Chrome, twice, and failing
#       test_kvk_register HonestEmptyOffline    33.02s   the production retry backoff
#       test_sniff_api_drive (non-tty)          30.00s   a thirty-second wall-clock deadline
#
#   MEASURED after: 65.59s -> 0.01s and 33.02s -> 0.05s, with the tests still passing and still
#   asserting exactly the property their names claim. Nothing was deleted and no assertion was
#   weakened. The WAIT was never the test.
#
# WHY A MECHANISM RATHER THAN THREE FIXES.
#
#   Those three were written by three different people at three different times, and each one
#   passed review, because a slow test looks exactly like a fast one from the outside. The
#   process that produced them is still running. Without a gate the fourth one lands next month
#   and nobody notices for a year — which is precisely how the first three got here.
#
#   This is the fleet's own promote-at-three rule (`library/instincts/fault_ledger.json`): a
#   fault class that has bitten three times stops being something to remember and becomes
#   something a machine checks.
#
# THE RULE, AND WHY IT IS MEASURED RATHER THAN DECLARED.
#
#   The obvious design is a seconds budget plus a policy file where an author declares "this one
#   is slow because X". That is half right, and the half that is wrong is the half that matters:
#   an author who believed their test was fast is exactly the author who wrote the 65-second
#   one. Asking them to self-certify re-creates the problem with paperwork attached.
#
#   So the primary rule is MEASURED, not declared, and it is the one question that has a
#   machine-checkable answer:
#
#       RULE 1 (hard) — how much of this test was spent in `time.sleep`?
#
#   Sleeping is never computation. A test that sleeps is waiting for nothing, on every machine,
#   forever, and no amount of hardware makes it faster. This is deliberately machine-INDEPENDENT:
#   thirty seconds of sleep is thirty seconds on a laptop, on the box and on a CI runner, so this
#   rule cannot cry wolf on a slow machine. That matters — this fleet has already recorded four
#   detectors that were switched off within a week for crying wolf, and a committed baseline that
#   was red on a runner and green in a container for weeks.
#
#       RULE 2 (declared) — a test over the WALL budget must say why.
#
#   Wall time is machine-specific, so this half genuinely does need a human sentence, and its
#   budget is meant to be tuned per repo. Its kinds are the point: `computation`, `io` and
#   `fixture` are legitimate and pass; `wait` FAILS, because naming it does not make it worth
#   paying for. Declaring a wait buys you nothing except a record of who knew.
#
#   Rule 1 catches what Rule 2's author would have mis-declared; Rule 2 catches what Rule 1
#   cannot see. The sniff_api test is the worked example of why BOTH are needed: it sleeps for
#   almost none of its thirty seconds. It polls against a wall-clock deadline, so patching
#   `time.sleep` does not speed it up at all — MEASURED, still 30.00s with sleep globally
#   neutered — and only the wall rule sees it.
#
# WHAT IT DOES NOT DO, deliberately.
#
#   * It does NOT fail a test. It reports, and the gate that calls it decides. A timing check
#     that can fail an individual test turns every busy machine into a red suite, and a red
#     light that is always on is wallpaper.
#   * It does NOT measure subprocess time, CPU time, or I/O. Those are real and they are not
#     this. A gate that measures four things badly is worse than one that measures one thing
#     honestly, and `slept` is the one with no false positives in it.
#   * It does NOT guess a kind. An over-budget test with no policy entry is `undeclared` and
#     fails — it is never sorted into a plausible bucket. A taxonomy that guesses is how
#     data_library's `classify_failure` catch-all came to carry 207 of its 208 items.
#   * It NEVER passes vacuously. No recording, or a recording with no tests in it, is exit 2 —
#     the same refusal as `skip_audit`, for the same reason: a gate that cannot tell "clean"
#     from "did not run" is the exact fault this whole bundle exists to stop.
#
# HOW TO RECORD A RUN
#
#     python -m pytest tests -q -p duration_budget --durations=0
#         (with library/ci_gates on sys.path — data_library's tests/conftest.py already does
#          the one path insert, so `-p duration_budget` is enough)
#     python .toolbox/ci_gates/duration_budget.py --from .duration_budget.json
#
# ============================================================================
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

#: A test that sleeps longer than this is waiting for nothing. Machine-independent, so this
#: number means the same thing everywhere and needs no per-repo tuning. One second is generous:
#: a deliberate 0.05s settle in a concurrency test is legitimate and must not be flagged.
SLEEP_BUDGET_S = 1.0

#: Wall-clock budget. Machine-SPECIFIC by nature, so this is the knob a repo is expected to
#: move, and it is env-overridable ahead of a baked default (fleet Rule 12b — the automation
#: that runs this has no terminal and inherits nobody's environment).
WALL_BUDGET_S = 10.0

#: A declaration may say a test is slow for one of these reasons. `wait` is listed so it can be
#: NAMED and still fail: the vocabulary has to be able to describe the bad case, or an author
#: with a waiting test picks the nearest passing word instead.
KINDS_OK = ("computation", "io", "fixture")
KINDS_BAD = ("wait",)

RECORD_DEFAULT = ".duration_budget.json"
#: our own name, as `-p <this>` spells it — used to stop children inheriting the plugin.
PLUGIN_NAME = "duration_budget"

#: THE WALL. Off unless a repo asks for it, because a shared bundle must not change what five
#: suites do by being checked out. `DURATION_SLEEP_WALL_S` / `DURATION_SESSION_BUDGET_S` turn it
#: on, and the gate script that wants it says so out loud.
SLEEP_WALL_OFF = 0.0
SESSION_BUDGET_OFF = 0.0

#: THE CAP, IN MONEY (owner 2026-09-23: "can we set the cap at 500 for everything").
#: Denominated in dollars rather than seconds because that is the unit the budget is set in,
#: and because seconds are the thing that reads as nothing: "65 seconds" is a shrug, "$109 a
#: run, every run, forever" is a decision. The rate converts.
BUDGET_USD = 500.0

#: THE RATE IS PER-RESOURCE, and this default is a placeholder for the EXPENSIVE case. Set it
#: to what the compute actually costs where the suite actually runs, because the same suite is
#: worth wildly different amounts on different silicon:
#:
#:   a dev container          effectively free. The honest unit here is WALL-CLOCK — somebody
#:                            waiting — and a dollar figure is a readability device, nothing
#:                            more. Do not annualise it; a notional rate multiplied out by
#:                            sessions and weeks turns a modest time saving into something that
#:                            reads like money in a bank, and that is this fleet's own named
#:                            fault (a stated number makes a reader confident about a figure
#:                            they would otherwise check) wearing a currency symbol.
#:
#:   GitHub Actions minutes   METERED AND REAL, and this fleet has the receipts: 2,000 minutes
#:                            exhausted in July 2026 by one repo's 667 runs, then exhausted
#:                            again on 2026-09-17 across three repos. A $0 spending limit turns
#:                            that into a hard block — which read as "the feature is off"
#:                            rather than "the meter ran out", twice.
#:
#:   the herterodus brain     OWNED, and that inverts everything else on this list. ~$3,000 of
#:                            silicon, already spent, so the marginal cost of a call is
#:                            essentially the electricity. The real rate is CAPITAL DIVIDED BY
#:                            HOURS ACTUALLY USED, and you own the denominator:
#:
#:                                  1 h/day over 3 yr    $2.74/hour
#:                                  8 h/day over 3 yr    $0.34/hour
#:                                  never                the whole $3,000 unrealised
#:
#:                            So for a bought asset the waste is UNDER-use, not over-use, and
#:                            the cost-optimal instinct is the opposite of everywhere else in
#:                            this file: run MORE on it. What is genuinely scarce is not money
#:                            but EXCLUSIVITY — there is one of them, the flows engine is gated
#:                            to ANALYST_FLOW_CONCURRENCY=1, and the currency is queue depth.
#:
#:                            A DISTINCTION THIS FLEET ALREADY BLURS: "prompt beats model size
#:                            — tune the prompt before buying a bigger model / more VRAM" (with
#:                            llama3.1:8b MEASURED tying gemma4:12b at ~77%) is a CAPITAL-
#:                            AVOIDANCE argument, correct before the purchase. After it, the
#:                            same advice holds for a different reason — throughput, not cost —
#:                            and reading the old reason onto owned hardware is how you end up
#:                            under-using something you have already paid for.
#:
#:   THE AGENT ITSELF        ~$200/month with CAPS AND LIMITS ON TOKENS (owner 2026-09-23),
#:                            and this is the regime that actually governed the session that
#:                            wrote this file. Amortised it is small — 80 working hours a month
#:                            is ~$2.50/hour, against the $100/MINUTE frame above, so the
#:                            thought experiment ran 2,400x hot. But the DOLLARS ARE NOT THE
#:                            BINDING CONSTRAINT. The cap is.
#:
#:                            That makes it the same shape as the Actions quota, not the same
#:                            shape as the electricity bill: it does not degrade, it STOPS. And
#:                            a session that stopped because it ran out of budget looks exactly
#:                            like a session that stopped because it failed — this bundle's
#:                            founding fault, pointed at the thing doing the measuring.
#:
#:                            THE PRACTICAL CONSEQUENCE, recorded because it is the opposite of
#:                            what a compute-cost frame suggests: on this container a full
#:                            suite run is ~free in electricity and expensive in TOKENS — the
#:                            output has to be read, and re-read to compare. The session that
#:                            built this ran data_library's suite FIVE times. Nearly nothing in
#:                            compute; a real share of the only capped resource in the room.
#:                            So the optimisation that matters is reading a RECORDING rather
#:                            than a log, and asking `--plan` what a run will cost before
#:                            spending the turns to sit through it. The quote-before-the-run
#:                            applies to the agent as much as to the suite.
#:
#: The fleet already reasons this way about LLM calls — "prompt beats model size: tune the
#: prompt before buying a bigger model / more VRAM" is the same argument, already MEASURED.
#: It had simply never been pointed at the test suite.
RATE_USD_PER_MIN = 100.0

#: Warn at 90% of whatever the cap is — DERIVED, never a second number to keep in step with the
#: first. MEASURED the day the cap was set: data_library is $480/run, which lands inside this
#: band. Warned, not stopped, on its first real reading.
WARN_FRACTION = 0.9


class BudgetExceeded(BaseException):
    """DELIBERATELY BaseException, and this is the whole design (owner 2026-09-23).

        "if you have a wall, then you need a try and accept that bumps you out of the
         process, not necessarily a try and continue"

    A wall that `except Exception:` can swallow is not a wall. It is a suggestion, and the
    code most likely to swallow it is exactly the code worth walling: this fleet has already
    recorded SEVEN pipelines whose bare `except` made a 403, a consent redirect and a DNS
    failure read identically, and `Rba_ExchangeRates` landing nothing because of it.

    `KeyboardInterrupt` and `SystemExit` derive from `BaseException` for this reason — they are
    the two other things that mean "stop, this is not yours to handle". So does this. A retry
    loop that catches `Exception` and backs off would otherwise catch the wall and go back to
    sleep, which is the precise behaviour the wall exists to stop.

    The fleet has the mirror of this written down already, in `run_queue.is_due`: it catches
    `BaseException` rather than `Exception` BECAUSE `SystemExit` would otherwise take the
    worker down. Same distinction, read from the other side.
    """


def _env_float(name: str, default: float) -> float:
    """Env first, then a REAL baked default; an unparseable value is IGNORED, never read as 0.

    Reading `WALL_BUDGET=1o` as 0.0 would put every test in the suite over budget, which reads
    as a catastrophic regression rather than as a typo. Herdity's threshold registry took the
    same decision for the same reason.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        sys.stderr.write(f"duration_budget: ignoring unparseable {name}={raw!r}\n")
        return default


# ── the recorder (a pytest plugin) ──────────────────────────────────────────
_SLEPT = {"total": 0.0, "test_start": 0.0, "wall": SLEEP_WALL_OFF}
_SETUP: Dict[str, tuple] = {}
_REAL_SLEEP = time.sleep


def _accounting_sleep(seconds, *a, **k):
    """`time.sleep`, with a meter on it.

    Installed over the `time` module itself rather than per-caller, because the point is to
    catch the sleep NOBODY KNEW ABOUT — a retry backoff four call frames down, a driver poll
    inside a vendored library. A per-caller patch only ever finds the sleeps you already
    suspected, which are not the expensive ones.

    UNDER-counts in two honest ways, both chosen over over-counting: a module that did
    `from time import sleep` before this was installed keeps the original, and concurrent
    sleeps in threads add up to more than the wall clock they actually cost. A gate that
    invents a finding gets switched off; one that occasionally misses is merely incomplete.
    """
    wall = _SLEPT["wall"]
    if wall and (_SLEPT["total"] - _SLEPT["test_start"]) >= wall:
        # THE WALL IS THE SLEEP ITSELF, which is why this needs no signal and no watchdog
        # thread and works identically on Windows, where `signal.SIGALRM` does not exist and
        # the owner's laptop lives. The meter is already here; refusing is one line further.
        raise BudgetExceeded(
            f"slept {_SLEPT['total'] - _SLEPT['test_start']:.2f}s, over the {wall:.2f}s wall. "
            "Sleeping is never computation — force the absence instead of waiting for it.")
    t0 = time.perf_counter()
    try:
        return _REAL_SLEEP(seconds, *a, **k)
    finally:
        _SLEPT["total"] += time.perf_counter() - t0


def _stop_inheriting(env=None) -> None:
    """Remove this plugin from PYTEST_ADDOPTS once it is loaded, so CHILDREN do not get it.

    THE VARIABLE'S JOB IS DONE THE MOMENT THE PLUGIN IS LOADED, and leaving it set makes it an
    instruction to every pytest this session's tests go on to SPAWN. That is not hypothetical:
    MEASURED 2026-09-25 on data_library, where
    `test_data_engineer::test_gate_is_the_subprocess_verdict_and_names_the_failing_assertion`
    runs a real pytest over a generated scaffold and asserts on its summary. With the recorder
    inherited, the child loaded it too, printed its own "recorded N tests" line, and the
    assertion failed — a test that had nothing to do with cost, broken by the cost meter, and
    only in a full-gate run where the env was set. It passed everywhere it was looked at.

    WORSE THAN A BROKEN ASSERTION: the child writes `.duration_budget.json` into ITS OWN cwd.
    A test that spawns pytest at the repo root would silently OVERWRITE the parent's recording
    mid-run, and the watch would then diff a three-test child against the baseline — which
    reads as thousands of tests GONE, not as a bug.

    Both forms are stripped (`-p duration_budget` and `-pduration_budget`), and the variable is
    removed entirely when nothing is left, because an empty PYTEST_ADDOPTS is not the same as
    an unset one to every tool that reads it.

    LIMIT, stated rather than discovered: a distributed runner whose workers are subprocesses
    (pytest-xdist) needs the plugin in each worker, and this would take it away. No repo in
    the fleet uses xdist — CHECKED, not assumed — and the fix there is to name `-p
    duration_budget` on the command line, where it is not inherited by anything.
    """
    env = os.environ if env is None else env
    raw = env.get("PYTEST_ADDOPTS")
    if not raw:
        return
    # An index walk, because the first draft tracked a "skip the next token" flag and got
    # SEVEN of eight cases wrong — including eating the argument of an unrelated `-p randomly`.
    # A table test caught it before it shipped; the flag version read fine.
    toks, kept, i = raw.split(), [], 0
    while i < len(toks):
        t = toks[i]
        if t == "-p" and i + 1 < len(toks) and toks[i + 1] == PLUGIN_NAME:
            i += 2                                  # "-p duration_budget"
            continue
        if t == "-p" + PLUGIN_NAME:
            i += 1                                  # "-pduration_budget"
            continue
        kept.append(t)
        i += 1
    out = " ".join(kept).strip()
    if out:
        env["PYTEST_ADDOPTS"] = out
    else:
        # Removed, not emptied: an empty PYTEST_ADDOPTS is not the same as an unset one to
        # every tool that reads it.
        env.pop("PYTEST_ADDOPTS", None)


def pytest_configure(config):
    _stop_inheriting()
    time.sleep = _accounting_sleep
    config._duration_rows = []
    _SLEPT["wall"] = _env_float("DURATION_SLEEP_WALL_S", SLEEP_WALL_OFF)
    config._rate = _env_float("DURATION_RATE_USD_PER_MIN", RATE_USD_PER_MIN)
    config._budget_usd = _env_float("DURATION_BUDGET_USD", 0.0)
    config._warn_usd = (_env_float("DURATION_WARN_USD", 0.0)
                        or config._budget_usd * WARN_FRACTION)
    # A money cap IS a seconds cap once the rate is known. One conversion, here, so nothing
    # downstream has to hold both units — and a repo that prefers seconds can still set them.
    config._session_budget = _env_float("DURATION_SESSION_BUDGET_S", SESSION_BUDGET_OFF)
    if config._budget_usd and not config._session_budget:
        config._session_budget = config._budget_usd / config._rate * 60.0
    config._session_t0 = time.perf_counter()
    config._budget_blown = None
    if _SLEPT["wall"] or config._session_budget:
        cap = (f"${config._budget_usd:.0f} ({config._session_budget:.0f}s)"
               if config._budget_usd else f"{config._session_budget or 'off'}s")
        sys.stderr.write(
            f"duration_budget: WALL ON — sleep {_SLEPT['wall'] or 'off'}s/test, cap {cap}\n")


def pytest_unconfigure(config):
    time.sleep = _REAL_SLEEP
    rows = getattr(config, "_duration_rows", None)
    if rows is None:
        return
    out = os.environ.get("DURATION_BUDGET_OUT", RECORD_DEFAULT)
    try:
        write_record(out, rows)
        sys.stderr.write(f"duration_budget: recorded {len(rows)} tests -> {out}\n")
    except OSError as e:
        # Loud, never silent: a recording that did not land makes the NEXT step exit 2, and the
        # reader needs to know it was the write that failed rather than the run.
        sys.stderr.write(f"duration_budget: COULD NOT WRITE {out}: {e}\n")


def pytest_runtest_setup(item):
    """Record the SETUP phase SEPARATELY, because it is where the repeatable waste lives.

    Setup is not the test's own cost — it is the FIXTURE's — and that distinction is the whole
    point of measuring it apart. A fixture costing 2.3s under a module of 35 tests is 80
    seconds that one `scope="module"` would turn into 2.3, with every assertion untouched.
    That is efficiency with no coverage traded away, which is the only kind worth having.

    Herdity is the live case: `animal_registry.all_animals` costs 2.26s uncached, and the
    tests that used to skip it now read real parquet. Nothing about that is visible in a CALL
    time, so a report built on call time alone would look at the most expensive suite in the
    fleet and see nothing to fix.
    """
    t0, before = time.perf_counter(), _SLEPT["total"]
    try:
        yield
    finally:
        _SETUP[item.nodeid] = (round(time.perf_counter() - t0, 3),
                               round(_SLEPT["total"] - before, 3))


def pytest_runtest_call(item):
    """Wrap the CALL phase only — setup and teardown are the fixtures' cost, not the test's."""
    _SLEPT["test_start"] = _SLEPT["total"]        # the per-test sleep wall is per TEST
    before, t0 = _SLEPT["total"], time.perf_counter()
    try:
        yield
    finally:
        _su, _su_slept = _SETUP.pop(item.nodeid, (0.0, 0.0))
        item.config._duration_rows.append({
            "setup": _su,
            "setup_slept": _su_slept,
            "nodeid": item.nodeid,
            "wall": round(time.perf_counter() - t0, 3),
            "slept": round(_SLEPT["total"] - before, 3),
        })


# pytest needs to know the above is a hook wrapper; set the marker in a way that works whether
# or not pytest is importable (this module is also read by the audit path, which has no pytest).
try:  # pragma: no cover - import-shape only
    import pytest as _pytest

    pytest_runtest_call = _pytest.hookimpl(hookwrapper=True)(pytest_runtest_call)
    pytest_runtest_setup = _pytest.hookimpl(hookwrapper=True)(pytest_runtest_setup)
except Exception:  # noqa: BLE001
    pass


def pytest_runtest_logreport(report):
    """The SESSION wall. Stops the run; never lets the run report a pass.

    A session budget has one failure mode that matters and it is not the obvious one. Stopping
    early is easy; stopping early and exiting 0 is a catastrophe, because a suite that quietly
    tested two thirds of itself reads exactly like a suite that tested all of it. That is this
    bundle's founding fault — "a failure and an honest empty look identical" — raised to the
    level of the whole run.

    So the stop is recorded on the config and turned into a NON-ZERO exit in
    `pytest_sessionfinish`, and the terminal summary names how many tests never ran.
    """
    cfg = getattr(report, "config", None) or _CONFIG.get("current")
    if cfg is None or not getattr(cfg, "_session_budget", 0):
        return
    if getattr(cfg, "_budget_blown", None):
        return
    spent = time.perf_counter() - cfg._session_t0
    if spent >= cfg._session_budget:
        cfg._budget_blown = {"spent": spent, "at": report.nodeid,
                             "ran": len(getattr(cfg, "_duration_rows", []))}
        # `shouldstop` is pytest's own cooperative stop: the current test finishes, nothing
        # after it starts. Killing mid-test would leave a half-run test reported as neither
        # passed nor failed, which is a worse lie than the one we are preventing.
        if _CONFIG.get("session") is not None:
            _CONFIG["session"].shouldstop = (
                f"duration_budget: SESSION BUDGET EXHAUSTED after {spent:.1f}s")


def pytest_sessionstart(session):
    _CONFIG["session"] = session
    _CONFIG["current"] = session.config


def pytest_sessionfinish(session, exitstatus):
    blown = getattr(session.config, "_budget_blown", None)
    if blown:
        # EXIT 2, not 0 and not 1. Not 0 for the reason above; not 1 because 1 means "tests
        # failed", and nothing here failed — the run was cut short, which is a different fact
        # and sends the reader somewhere else entirely.
        session.exitstatus = 2


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    blown = getattr(config, "_budget_blown", None)
    if not blown:
        return
    terminalreporter.write_sep("=", "DURATION BUDGET EXHAUSTED", red=True)
    terminalreporter.write_line(
        f"  spent {blown['spent']:.1f}s of a {config._session_budget:.0f}s budget; "
        f"{blown['ran']} tests ran, the rest NEVER RAN.")
    terminalreporter.write_line(
        "  This is NOT a pass and NOT a test failure — it is an unfinished run (exit 2).")
    terminalreporter.write_line(
        "  Before raising the budget: `duration_budget --from <record> --rate 100` says where "
        "it went.")


#: The session/config, so `pytest_runtest_logreport` can reach them without a fixture. A module
#: global rather than a hook argument because `logreport` is not handed the session.
_CONFIG: Dict[str, object] = {}


# ── the audit ───────────────────────────────────────────────────────────────
def load_policy(root: str = ".") -> dict:
    """The committed declarations. A malformed file is treated as ABSENT, never as empty.

    Empty would mean "nothing is declared, so everything over budget fails"; absent means
    "nothing was checked", and those get different exit codes. Reading a broken file as the
    first one would fail a suite for a missing comma.
    """
    p = os.path.join(root, "tests", "duration_policy.json")
    try:
        with open(p, encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def machine_stamp() -> dict:
    """WHO took this recording, so a comparison across machines can be argued with.

    A duration is meaningless without the machine that produced it. The watch is already
    machine-TOLERANT by construction — a factor, so a uniformly slower box is not N
    regressions — but tolerance is not the same as legibility: when it DOES fire, the first
    question is "was this the same machine?", and until now nothing in the file could answer.
    A committed baseline whose provenance is unrecorded cannot be disputed, only believed.

    What it records is what changes a duration: the host, the OS/arch, the Python, and how
    many cores were available. `DURATION_BUDGET_MACHINE` overrides the label (Rule 12b — env
    first, then a real baked default) for anyone who would rather not commit a hostname.

    NO SECRETS AND NO PATHS. This file is COMMITTED, so the stamp is limited to facts about
    the hardware. A cwd or a home directory would leak a layout into every repo in the fleet.
    """
    label = os.environ.get("DURATION_BUDGET_MACHINE", "").strip()
    try:
        import platform
        host = label or platform.node() or "unknown"
        plat = platform.platform(terse=True)
        py = platform.python_version()
    except Exception:                                    # pragma: no cover - defensive
        host, plat, py = label or "unknown", "unknown", sys.version.split()[0]
    try:
        cpus = os.cpu_count() or 0
    except Exception:                                    # pragma: no cover - defensive
        cpus = 0
    # HOW BUSY THE BOX WAS, which the machine identity does not answer and which a reader
    # needs just as much. MEASURED 2026-09-24, on this recorder's own first use: a baseline
    # taken while the container was doing something else read 6.4s against 5.2s on a quiet
    # run — 23% high, on the same machine, with an identical stamp otherwise. Committed, that
    # inflates the bar every later comparison is measured against, and the watch's factor
    # means a test would then have to be 2.5x its true cost to trip. Nothing about the host
    # would have hinted at it.
    #
    # `None` on a platform without a load average (Windows), never 0.0 — a reported zero
    # means an idle box, which is the opposite of "we could not look".
    try:
        load = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load = None
    return {
        "load_1min": load,
        "machine": host,
        "platform": plat,
        "python": py,
        "cpus": cpus,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "labelled": bool(label),
    }


def load_meta(path: str) -> dict:
    """The stamp from a recording, or {} for one written before stamps existed.

    Honest-empty on purpose: a baseline taken in August is not broken, it is unstamped, and
    the report says "provenance not recorded" rather than pretending to know.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    meta = got.get("meta") if isinstance(got, dict) else None
    return meta if isinstance(meta, dict) else {}


def describe_machine(meta: dict) -> str:
    """One line for a report. Says it does not know rather than guessing."""
    if not meta:
        return "provenance not recorded"
    bits = [str(meta.get("machine") or "unknown")]
    for k in ("platform", "python", "cpus"):
        v = meta.get(k)
        if v:
            bits.append(f"py{v}" if k == "python" else
                        (f"{v} cpu" if k == "cpus" else str(v)))
    load, cpus = meta.get("load_1min"), meta.get("cpus")
    if load is not None:
        busy = " BUSY" if (cpus and load > cpus * 0.7) else ""
        bits.append(f"load {load}{busy}")
    at = meta.get("recorded_at")
    return " · ".join(bits) + (f" · {at}" if at else "")


def same_machine(a: dict, b: dict) -> Optional[bool]:
    """True / False / None for "unknowable", which is a THIRD answer and not a False.

    Collapsing "I cannot tell" into "different machines" would print a warning on every
    comparison against an old unstamped baseline, and a warning that is always on is
    wallpaper — this repo's own rule, and the reason the caller must handle three cases.
    """
    if not a or not b:
        return None
    ka = (a.get("machine"), a.get("platform"), a.get("cpus"))
    kb = (b.get("machine"), b.get("platform"), b.get("cpus"))
    if any(x is None for x in ka + kb):
        return None
    return ka == kb


def write_record(path: str, rows: List[dict]) -> None:
    """The ONE writer, so both recorders stamp identically.

    The pytest plugin and the unittest runner both land here. A second `json.dump` in the
    other file is how the two shapes drift, and the analyser reads one shape for both.
    """
    with open(path, encoding="utf-8", mode="w") as fh:
        json.dump({"meta": machine_stamp(), "tests": rows}, fh, indent=1)


def load_record(path: str) -> List[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = got.get("tests") if isinstance(got, dict) else got
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("nodeid")]


def _declared(nodeid: str, policy: dict) -> Optional[dict]:
    """Exact nodeid, else a declaration whose `match` is a substring of it.

    Substring rather than glob because a parametrised id carries brackets and a path carries
    slashes, and a glob over both is a language nobody gets right on the first try.
    """
    for rule in policy.get("allow", []) or []:
        if not isinstance(rule, dict):
            continue
        m = rule.get("match") or rule.get("nodeid") or ""
        if m and m in nodeid:
            return rule
    return None


def audit(rows: List[dict], policy: dict, *, sleep_budget: float = None,
          wall_budget: float = None) -> Tuple[List[dict], bool]:
    """-> (findings worst-first, ok). Findings carry the evidence, never just a verdict."""
    sb = SLEEP_BUDGET_S if sleep_budget is None else sleep_budget
    wb = (_env_float("DURATION_WALL_BUDGET_S", WALL_BUDGET_S)
          if wall_budget is None else wall_budget)
    out: List[dict] = []
    for r in rows:
        wall, slept = float(r.get("wall") or 0.0), float(r.get("slept") or 0.0)
        rule = _declared(r["nodeid"], policy)
        kind = (rule or {}).get("kind")

        if slept > sb:
            # Rule 1. A declaration does NOT excuse this one, and that is deliberate: there is
            # no reason a test needs to sleep, so an allow-list entry here would only record
            # that somebody signed off on paying forever.
            out.append({"nodeid": r["nodeid"], "wall": wall, "slept": slept,
                        "verdict": "asleep",
                        "why": f"spent {slept:.2f}s in time.sleep (budget {sb:.2f}s)"})
            continue
        if wall > wb:
            if kind in KINDS_BAD:
                out.append({"nodeid": r["nodeid"], "wall": wall, "slept": slept,
                            "verdict": "declared_wait",
                            "why": f"declared `wait`: {rule.get('why', '(no reason given)')}"})
            elif kind in KINDS_OK:
                continue                      # declared, legitimate, paid for knowingly
            else:
                out.append({"nodeid": r["nodeid"], "wall": wall, "slept": slept,
                            "verdict": "undeclared",
                            "why": f"{wall:.2f}s > wall budget {wb:.2f}s, nothing declared"})
    out.sort(key=lambda f: -f["wall"])
    return out, not out


def render(findings: List[dict], ok: bool, *, total_tests: int = 0,
           total_wall: float = 0.0, rate: float = 0.0) -> str:
    """The report. It prices the finding when a rate is given, because 65 seconds reads as
    nothing and $109 a run does not — and the second number is the one that is true."""
    if ok:
        return (f"duration budget: clean — {total_tests} tests, "
                f"{total_wall:.1f}s, nothing asleep and nothing over budget.\n")
    lines = ["duration budget: FINDINGS (worst first)", ""]
    reclaimable = 0.0
    for f in findings:
        cost = f" ${f['wall'] / 60.0 * rate:,.2f}/run" if rate else ""
        lines.append(f"  [{f['verdict']:14s}] {f['wall']:7.2f}s{cost}  {f['nodeid']}")
        lines.append(f"                    {f['why']}")
        reclaimable += f["wall"]
    lines += ["", f"  {reclaimable:.2f}s of {total_wall:.1f}s "
                  f"({reclaimable / total_wall * 100:.1f}% of the run)"
              if total_wall else ""]
    if rate:
        lines.append(f"  ${reclaimable / 60.0 * rate:,.2f} per run — and a suite runs twice a "
                     f"session, in every repo, forever.")
    lines += ["",
              "  asleep         -> the wait is not the test. Force the absence (a fixture that",
              "                    moves EVERY binding), or set the pipeline's own backoff knobs",
              "                    to 0. The assertion does not change.",
              "  declared_wait  -> naming it does not make it worth paying for.",
              "  undeclared     -> declare it in tests/duration_policy.json with a kind and a",
              "                    reason, or make it fast. `wait` is not a passing kind."]
    return "\n".join(lines) + "\n"


# ── the forecast: DON'T GET INTO THE 7-HOUR RUN (owner 2026-09-23) ──────────
#
#   "if we have a 17-hour run, obviously that's going to go way over that 500 budget ...
#    how do we prevent that from happening?"
#
# THE WALL DOES NOT PREVENT IT. It BOUNDS it, which is a different and much weaker thing:
# stopping a 7-hour suite at $500 means you have spent the entire budget and run about 1% of
# your tests. You are not under budget, you are broke AND untested.
#
# Prevention has to happen BEFORE the run, and it only can because the recorder leaves a
# per-test price list behind. Two mechanisms, and the second is the one that actually saves
# the day:
#
#   forecast()  — a QUOTE. Sum the last recording and compare it to the cap. A run that cannot
#                 afford to finish is refused at the door, naming the tests that make it so,
#                 instead of being discovered seven hours later.
#
#   affordable() — a PLAN. If you can only buy five minutes of a seven-hour suite, WHICH five
#                 minutes you buy is the entire question. In file order you get an arbitrary
#                 1%. Cheapest-first you get very nearly everything, because the cost is
#                 always concentrated: MEASURED, data_library's 7,021 cheapest tests are 25%
#                 of its clock, and Herdity's cost is dominated by a single module. So the
#                 budget buys ~99% of the TESTS either way — the only question is whether you
#                 choose which ones.
#
# THE DEFERRED SET IS THE OUTPUT, NOT A FOOTNOTE. A budget-shaped run that prints OK while the
# expensive tests never ran is this bundle's founding fault wearing a cost-control badge. So
# `affordable` returns both halves and the caller is expected to say the second one out loud.


def forecast(rows: List[dict], budget_usd: float,
             rate: float = RATE_USD_PER_MIN) -> dict:
    """What will this run cost, from the last recording? -> a quote, never a guess.

    `stale` is the honest part: a forecast made from a recording that predates the current
    code is a guess wearing a number. It is reported rather than silently trusted, because the
    whole value of a quote is that it was not made up.
    """
    total = sum(float(r.get("wall") or 0.0) for r in rows)
    cost = total / 60.0 * rate
    worst = sorted(rows, key=lambda r: -float(r.get("wall") or 0.0))[:10]
    return {
        "tests": len(rows),
        "seconds": total,
        "cost": cost,
        "budget": budget_usd,
        "affordable": (not budget_usd) or cost <= budget_usd,
        "over_by": max(0.0, cost - budget_usd) if budget_usd else 0.0,
        "worst": [{"nodeid": r["nodeid"], "wall": float(r.get("wall") or 0.0),
                   "cost": float(r.get("wall") or 0.0) / 60.0 * rate} for r in worst],
    }


def affordable(rows: List[dict], budget_usd: float,
               rate: float = RATE_USD_PER_MIN) -> Tuple[List[dict], List[dict]]:
    """Split the suite into what fits the cap and what does not, CHEAPEST FIRST.

    -> (fits, deferred). Both halves are returned because a caller that only reads the first
    one has built the silent-coverage-loss bug this exists to prevent.

    Cheapest-first is not a heuristic, it is the consequence of where the cost actually sits.
    A suite's time is concentrated in a handful of tests, so sorting by price means the budget
    buys nearly every test rather than an arbitrary prefix of them. It is also stable: ties
    break on nodeid, so two runs of the same recording defer the same set and the boundary
    does not wander.
    """
    if not budget_usd:
        return list(rows), []
    cap_s = budget_usd / rate * 60.0
    ordered = sorted(rows, key=lambda r: (float(r.get("wall") or 0.0), r.get("nodeid", "")))
    fits, spent = [], 0.0
    for r in ordered:
        w = float(r.get("wall") or 0.0)
        if spent + w > cap_s:
            break
        fits.append(r)
        spent += w
    kept = {r["nodeid"] for r in fits}
    return fits, [r for r in rows if r["nodeid"] not in kept]


def render_forecast(q: dict, deferred: List[dict], rate: float = RATE_USD_PER_MIN) -> str:
    L = [f"forecast from the last recording: {q['tests']} tests, {q['seconds']:.1f}s, "
         f"${q['cost']:,.2f}"]
    if not q["budget"]:
        L.append("  (no cap set — DURATION_BUDGET_USD)")
        return "\n".join(L) + "\n"
    if q["affordable"]:
        L.append(f"  fits the ${q['budget']:.0f} cap, ${q['budget'] - q['cost']:,.2f} to spare.")
        return "\n".join(L) + "\n"
    L += [f"  ⛔ OVER THE ${q['budget']:.0f} CAP BY ${q['over_by']:,.2f}. "
          f"Do not start this run expecting it to finish.",
          "",
          "  the cost is concentrated here:"]
    for w in q["worst"][:6]:
        L.append(f"    ${w['cost']:9,.2f}  {w['wall']:8.1f}s  {w['nodeid'][:64]}")
    L += ["",
          f"  WITHIN the cap, cheapest first: {q['tests'] - len(deferred)} of {q['tests']} "
          f"tests ({(q['tests'] - len(deferred)) / q['tests'] * 100:.1f}%).",
          f"  DEFERRED: {len(deferred)} test(s), "
          f"${sum(r['wall'] for r in deferred) / 60.0 * rate:,.2f} — THESE WILL NOT RUN.",
          "  Say that out loud wherever the result is reported. A budget-shaped run that",
          "  prints OK while the expensive tests never ran is worse than an honest overage."]
    return "\n".join(L) + "\n"


# ── keeping the SAME tests cheap: hoisting, and the regression watch ────────
#
#   "how do you keep the tests efficient? how do you keep the modules efficient? ... without
#    cheating or cutting out really critical tests"  (owner 2026-09-23)
#
# That constraint rules out the deferred set as an answer. Deferring IS cutting tests, just
# honestly. Everything below makes the SAME tests cost less, with no assertion touched:
#
#   hoist_candidates()  repeated FIXTURE cost. A module paying 2.3s of setup 35 times is 80
#                       seconds; `scope="module"` makes it 2.3. Same tests, same assertions.
#
#   regressions()       the forecast is backward-looking — it prices the LAST recording, so a
#                       test that degrades is invisible until the bill arrives. This is what
#                       stops a suite drifting from 7 minutes to 17 hours one commit at a time.
#                       It is the `pipeline_watch` shape, and it inherits that module's rule:
#                       IT NEVER RE-BASELINES ITSELF, because a watcher that does can never
#                       report the same regression twice and quietly normalises a decline.


def _group_of(nodeid: str) -> str:
    """The unit a fixture is actually scoped to — the CLASS where there is one, else the module.

    Grouping by module was wrong and the Herdity data said so on the first real reading. That
    repo runs unittest, where `setUp` belongs to the TestCase CLASS: one module holding four
    classes, three of them cheap and one doing a 2.9s read, reads as a 366x spread at module
    level and is correctly rejected as "not a shared cost" — while inside that one class it is
    a perfectly uniform shared cost, and hoistable to `setUpClass`.

    So the grouping has to match the language's own fixture scope or the detector asks a
    question nobody can act on. pytest ids are `path::Class::test[param]`; unittest ids are
    `pkg.mod.Class.test_method`. Both drop their last component to name the scope.
    """
    if "::" in nodeid:
        parts = nodeid.split("::")
        return "::".join(parts[:2]) if len(parts) > 2 else parts[0]
    return nodeid.rsplit(".", 1)[0] if "." in nodeid else nodeid


def hoist_candidates(rows: List[dict], rate: float = RATE_USD_PER_MIN,
                     min_seconds: float = 2.0) -> List[dict]:
    """Modules whose SETUP is paid per test and could be paid once. -> worst first.

    The signal is deliberately narrow: many tests, each paying a SIMILAR setup. Similarity is
    what distinguishes a shared fixture from a test that happens to do expensive work of its
    own, and getting that wrong is how a detector starts crying wolf in week one. So the spread
    has to be tight (max <= 3x median) before anything is claimed.

    `saving` is what a module-scoped fixture would return: everything but one payment. It is
    stated as an UPPER bound, because a fixture may be genuinely per-test (it mutates state,
    or the test needs isolation) and only a human can say which.
    """
    by_mod: Dict[str, List[dict]] = {}
    for r in rows:
        by_mod.setdefault(_group_of(r["nodeid"]), []).append(r)
    out = []
    for mod, rs in by_mod.items():
        setups = sorted(float(r.get("setup") or 0.0) for r in rs)
        if len(setups) < 3:
            continue
        total = sum(setups)
        if total < min_seconds:
            continue
        median = setups[len(setups) // 2]
        if median <= 0 or setups[-1] > median * 3:
            continue                       # not a shared cost — one test is doing its own work
        saving = total - median            # pay it once instead of n times
        if saving < min_seconds:
            continue
        out.append({"module": mod, "tests": len(rs), "setup_total": round(total, 2),
                    "per_test": round(median, 3), "saving": round(saving, 2),
                    "cost": saving / 60.0 * rate})
    return sorted(out, key=lambda d: -d["saving"])


def regressions(before: List[dict], after: List[dict], *, factor: float = 2.0,
                min_seconds: float = 3.0, rate: float = RATE_USD_PER_MIN,
                before_meta: Optional[dict] = None,
                after_meta: Optional[dict] = None) -> dict:
    """What got SLOWER, what got faster, what is new or gone. The `pipeline_watch` shape.

    Two thresholds, both needed: `factor` so a uniformly slower machine does not light up the
    whole report, and `min_seconds` so a small move is not called a regression.

    THE FLOOR WAS 0.5s AND IT CRIED WOLF ON THE FIRST REAL GATE RUN, which is recorded here
    because it is the fifth time this session that a detector's first findings were false.
    data_library's gate reported two "regressions":

        1.04s -> 2.66s   test_parallel_search::test_one_bad_query_does_not_lose_the_rest
        1.23s -> 2.82s   test_hash_index::test_a_migration_blocked_by_a_running_one

    Both are CONCURRENCY tests — one about a failing query among parallel ones, one about a
    blocked migration — so their wall time is load-sensitive by nature, and a 1s test reaching
    2.7s on a busy box is the machine talking, not the code. Neither is a defect.

    The fix is not a bigger number picked to make today pass. It is that the floor was
    denominated in the WRONG UNIT. This watch exists to stop drift toward the CAP, so the
    threshold for "worth reporting" should be a share of the cap, not an absolute duration
    that means something different on a 1s test and a 60s one. At $100/min and a $500 cap,
    3 seconds is ~1% of the budget; the two false findings were $2.70 and $2.64 of a $552
    run, 0.5% each, and reporting them taught the reader to ignore the report.

    What it still catches is everything that matters: 0.01s -> 90.02s, 65.5s -> 0.01s, and any
    single test growing past 1% of what you are willing to spend on the whole suite.
    """
    provenance = {"before": describe_machine(before_meta or {}),
                  "after": describe_machine(after_meta or {}),
                  "same": same_machine(before_meta or {}, after_meta or {})}
    b = {r["nodeid"]: float(r.get("wall") or 0.0) for r in before}
    a = {r["nodeid"]: float(r.get("wall") or 0.0) for r in after}
    worse, better = [], []
    for k in a.keys() & b.keys():
        d = a[k] - b[k]
        if d >= min_seconds and a[k] >= b[k] * factor:
            worse.append({"nodeid": k, "before": b[k], "after": a[k], "delta": d,
                          "cost": d / 60.0 * rate})
        elif -d >= min_seconds and b[k] >= a[k] * factor:
            better.append({"nodeid": k, "before": b[k], "after": a[k], "delta": d,
                           "cost": d / 60.0 * rate})
    return {"provenance": provenance,
            "worse": sorted(worse, key=lambda x: -x["delta"]),
            "better": sorted(better, key=lambda x: x["delta"]),
            "new": sorted(a.keys() - b.keys()), "gone": sorted(b.keys() - a.keys())}


def render_efficiency(hoists: List[dict], watch: Optional[dict],
                      rate: float = RATE_USD_PER_MIN) -> str:
    L = []
    if hoists:
        tot = sum(h["saving"] for h in hoists)
        L += [f"HOIST THE FIXTURE — {len(hoists)} scope(s), {tot:.1f}s, "
              f"${tot / 60.0 * rate:,.2f}/run, NO test changed:", ""]
        for h in hoists[:12]:
            L.append(f"  {h['saving']:7.1f}s  ${h['cost']:8,.2f}  {h['tests']:4d} tests x "
                     f"{h['per_test']:.2f}s setup   {h['module']}")
        L += ["", "  A class- or module-scoped fixture pays this ONCE. Upper bound: a fixture",
              "  that mutates state or needs isolation is legitimately per-test, and",
              "  only a human can say which.", ""]
    if watch is not None:
        prov = watch.get("provenance")
        if prov:
            L += [f"baseline: {prov['before']}",
                  f"this run: {prov['after']}"]
            if prov["same"] is False:
                L += ["",
                      "  ⚠ DIFFERENT MACHINE. The factor below absorbs a uniformly slower box,",
                      "    so this is not by itself a reason to dismiss a finding — but a single",
                      "    test moving on a different machine is a weaker claim than the same",
                      "    test moving on the same one. Re-take the baseline here if this is",
                      "    where the gate now runs."]
            elif prov["same"] is None:
                L += ["",
                      "  (one side is unstamped, so same-machine cannot be established — an old",
                      "   baseline is not broken, only unlabelled. Re-take it to say.)"]
            L.append("")
        if watch["worse"]:
            L += [f"SLOWER than the baseline — {len(watch['worse'])}:", ""]
            for w in watch["worse"][:12]:
                L.append(f"  {w['before']:7.2f}s -> {w['after']:7.2f}s  "
                         f"${w['cost']:8,.2f}  {w['nodeid'][:62]}")
            L.append("")
        if watch["better"]:
            L.append(f"faster: {len(watch['better'])} "
                     f"(${-sum(x['cost'] for x in watch['better']):,.2f}/run reclaimed)")
        if watch["new"]:
            L.append(f"new: {len(watch['new'])}")
        if watch["gone"]:
            L.append(f"GONE: {len(watch['gone'])} — a test that stopped existing is not a "
                     f"test that got faster")
        if not any((watch["worse"], watch["better"], watch["new"], watch["gone"])):
            L.append("nothing moved against the baseline.")
    return "\n".join(L) + "\n" if L else "nothing to report.\n"


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--from", dest="src", default=None,
                    help="the JSON a recorded run wrote (default .duration_budget.json)")
    ap.add_argument("--rate", type=float, default=0.0,
                    help="$/minute, to price each finding")
    ap.add_argument("--list", action="store_true", help="report without failing")
    ap.add_argument("--plan", action="store_true",
                    help="forecast this run's cost against the cap and refuse if it cannot "
                         "afford to finish — the BEFORE-the-run check")
    ap.add_argument("--hoist", action="store_true",
                    help="modules paying a shared fixture cost per test — the same tests, "
                         "cheaper, with nothing cut")
    ap.add_argument("--against", default=None,
                    help="a previous recording: report what got SLOWER (never re-baselines)")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help=f"the cap in dollars (default {BUDGET_USD:.0f}, "
                         f"env DURATION_BUDGET_USD)")
    a = ap.parse_args(argv)

    src = a.src or os.path.join(a.root, RECORD_DEFAULT)
    rows = load_record(src)
    if not rows:
        # Exit 2, never 0. "No recording" and "a clean run" are different facts, and reading the
        # first as the second is the vacuous pass this bundle exists to refuse.
        sys.stderr.write(
            f"duration_budget: NOTHING RECORDED at {src}.\n"
            "  Nothing was checked, so this is not a pass. Record a run first:\n"
            "    python -m pytest tests -q -p duration_budget\n")
        return 2

    if a.hoist or a.against:
        rate = a.rate or _env_float("DURATION_RATE_USD_PER_MIN", RATE_USD_PER_MIN)
        watch = None
        if a.against:
            prev = load_record(a.against)
            if not prev:
                sys.stderr.write(f"duration_budget: NOTHING TO COMPARE AGAINST at {a.against}\n")
                return 2
            watch = regressions(prev, rows, rate=rate,
                                before_meta=load_meta(a.against), after_meta=load_meta(src))
        hoists = hoist_candidates(rows, rate) if a.hoist else []
        sys.stdout.write(render_efficiency(hoists, watch, rate))
        if a.list:
            return 0
        return 1 if (watch and watch["worse"]) else 0

    if a.plan:
        budget = (a.budget_usd if a.budget_usd is not None
                  else _env_float("DURATION_BUDGET_USD", BUDGET_USD))
        rate = a.rate or _env_float("DURATION_RATE_USD_PER_MIN", RATE_USD_PER_MIN)
        q = forecast(rows, budget, rate)
        _fits, deferred = affordable(rows, budget, rate)
        sys.stdout.write(render_forecast(q, deferred, rate))
        # Exit 1, not 2: 2 means "nothing was checked". Here everything was checked and the
        # answer is no.
        return 0 if q["affordable"] else (0 if a.list else 1)

    policy = load_policy(a.root)
    findings, ok = audit(rows, policy)
    total_wall = sum(float(r.get("wall") or 0.0) for r in rows)
    sys.stdout.write(render(findings, ok, total_tests=len(rows),
                            total_wall=total_wall, rate=a.rate))
    return 0 if (ok or a.list) else 1


if __name__ == "__main__":
    raise SystemExit(main())
