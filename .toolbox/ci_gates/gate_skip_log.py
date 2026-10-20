# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/gate_skip_log.py
#
# THE SKIP RECORDER skip_audit.py READS, so a gate audits the run it already made.
#
# WHY A PLUGIN (data_library fault hunt F008, 2026-09-30; janet_lite 2026-10-03; the toolbox and
# health 2026-10-16). A gate that runs its suite through a wrapper (ci_baseline.py, check.sh)
# sees only the wrapper's tail, so skip_audit, which reads the `SKIPPED [n] path:line: reason`
# lines of a run, had nothing to read and the gate never ran it. A second suite run just to
# audit skips doubles the cost. So the run the gate already makes records its skips on the side,
# the way duration_budget records its timings: loaded with `-p gate_skip_log` through
# PYTEST_ADDOPTS. Ported from janet_lite `scripts/gate_skip_log.py`, whose header said its home
# should be here; behaviour unchanged for one process.
#
# One line PER skipped test (`[1]`), never folded: skip_audit counts lines and checks its count
# against the runner's own `N skipped`, and a folded `[3]` line would read as one skip. The file
# ends with that `N skipped` line so the cross-check has the runner's number.
#
# SEVERAL PROCESSES (the toolbox's check.sh runs one pytest per package root). With
# GATE_SKIPS_DIR set, each process writes `<dir>/<root>.txt`, its paths relative to the
# directory ABOVE that folder (the repo root), and
#
#   python .toolbox/ci_gates/gate_skip_log.py --merge .gate_skips.d --out .gate_skips.txt
#
# folds them into one file with one total, which skip_audit reads with --from. A folder with
# nothing in it exits 2: "nothing was recorded" is not "nothing skipped". `--expect N` (the number
# of roots the gate ran) exits 1 when the folder holds another number of records, so 8 of 9 can
# never read as complete (gate-auditor leftover, 2026-10-16).
#
# Loaded WITHOUT GATE_SKIPS_DIR the plugin still writes `.gate_skips.txt` in pytest's rootpath
# (the one-process gate), and says so on the terminal, so a stray load is never silent.
#
# Stdlib only.
# ============================================================================
"""Record a pytest run's skips for skip_audit; --merge folds one file per process into one."""
from __future__ import annotations

import argparse
import os
import re
import sys

_OUT = ".gate_skips.txt"
_TOTAL = re.compile(r"^(\d+) skipped$")


def _lines(stats, rootpath: str, base: str):
    lines = []
    for rep in stats.get("skipped", []):
        longrepr = getattr(rep, "longrepr", None)
        if isinstance(longrepr, tuple) and len(longrepr) == 3:
            path, lineno, reason = longrepr
            path = os.path.relpath(os.path.join(rootpath, str(path)), base)
        else:                                      # an unusual report: keep it, never drop it
            path = os.path.relpath(os.path.join(rootpath, rep.nodeid.split("::")[0]), base)
            lineno, reason = None, str(longrepr or "")
        reason = str(reason)
        if reason.startswith("Skipped: "):
            reason = reason[len("Skipped: "):]
        lines.append(f"SKIPPED [1] {path}:{lineno if lineno is not None else 0}: {reason}")
    return lines


def _destination(rootpath: str, target: str = ""):
    """(file to write, folder paths are relative to).

    In a folder, the file is named after the package the run TESTED (the folder above its
    `tests/` target), not pytest's rootpath: check.sh retries a failed root from the repo root
    (`pytest <root>/tests`), and a name taken from the rootpath gave that retry a second file,
    so one skip was counted twice (fault hunt 2026-10-16). The retry now overwrites its root's
    first attempt, the way a retry should.
    """
    d = os.environ.get("GATE_SKIPS_DIR", "").strip()
    if not d:
        return os.path.join(rootpath, _OUT), rootpath
    base = os.path.dirname(os.path.abspath(d))
    tested = os.path.dirname(os.path.abspath(target)) if target else rootpath
    rel = os.path.relpath(tested, base)
    slug = "repo_root" if rel in (".", "") else re.sub(r"[^A-Za-z0-9_-]", "_", rel)
    return os.path.join(d, slug + ".txt"), base


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    rootpath = str(config.rootpath)
    args = [a for a in (config.args or []) if not a.startswith("-")]
    target = (os.path.join(str(config.invocation_params.dir), args[0].split("::")[0])
              if args else "")
    out, base = _destination(rootpath, target)
    lines = _lines(terminalreporter.stats, rootpath, base)
    lines.append(f"{len(lines)} skipped")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    if not os.environ.get("GATE_SKIPS_DIR", "").strip():
        terminalreporter.write_line(
            f"gate_skip_log: GATE_SKIPS_DIR is not set, so this run's skips went to {out} "
            "(one-process mode). A gate that runs several processes must set it.")


def merge(dirpath: str):
    """(skip lines, total, files read, files with no total)."""
    skips, total, files, broken = [], 0, 0, []
    if not os.path.isdir(dirpath):
        return skips, total, files, broken
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".txt"):
            continue
        with open(os.path.join(dirpath, fname), encoding="utf-8", errors="replace") as fh:
            body = fh.read().splitlines()
        files += 1
        counted = None
        for line in body:
            m = _TOTAL.match(line.strip())
            if m:
                counted = int(m.group(1))
            elif line.startswith("SKIPPED "):
                skips.append(line)
        # A file with no total is a run that died mid-write: named, never read as clean.
        if counted is None:
            broken.append(fname)
        else:
            total += counted
    return skips, total, files, broken


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merge", required=True, help="the folder of per-process records")
    ap.add_argument("--out", default=_OUT)
    ap.add_argument("--expect", type=int, default=None,
                    help="the number of records there must be (one per process the gate ran)")
    a = ap.parse_args(argv)
    skips, total, files, broken = merge(a.merge)
    if broken:
        sys.stderr.write("gate_skip_log: no total in %s: that run did not finish writing, so "
                         "its skips cannot be trusted.\n" % ", ".join(broken))
        return 1
    if not files:
        sys.stderr.write(f"gate_skip_log: NOTHING RECORDED under {a.merge}/. Nothing was "
                         "checked, so this is not a pass. Load the recorder with "
                         "`-p gate_skip_log` and set GATE_SKIPS_DIR.\n")
        return 2
    if a.expect is not None and files != a.expect:
        sys.stderr.write(f"gate_skip_log: {files} record(s) under {a.merge}/ but {a.expect} "
                         "run(s) expected: a root's record is missing (or a stray one is there), "
                         "so the total cannot be trusted.\n")
        return 1
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(skips + [f"{total} skipped"]) + "\n")
    print(f"gate_skip_log: {files} run(s) recorded, {len(skips)} skip(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
