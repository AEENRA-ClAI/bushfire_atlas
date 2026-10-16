# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/ambient_branch.py
#
# AN ASSERTION BEHIND `if <the machine has X>` IS A SKIP THAT NOBODY COUNTS.
#
# WHY (owner 2026-09-22, "now do the conditional assertion one"). The fourth and last part of
# the gate-that-cannot-bite class, after the empty-scan guard, the neuter-bite and the skip audit.
#
#     if not excel_import._HAVE_XLSX:
#         out = herd_import.import_file(b"PK\x03\x04fake", fmt="xlsx")
#         self.assertEqual(out["n"], 0)
#         self.assertTrue(out["warnings"])
#
# That is the WHOLE body of `test_xlsx_honest_without_openpyxl`. MEASURED 2026-09-22:
# `_HAVE_XLSX` is True, so the test runs nothing at all and reports a PASS. It does not appear
# in the skip count, because it is not a skip — it is a green tick over an empty function.
#
# THE PART WORTH KEEPING: adding `openpyxl` to Herdity's bootstrap CORE on 2026-09-21 — the fix
# that un-skipped twelve tests — is exactly what made this one dead. **Repairing an environment
# can silently disable the test written for the broken one.** Nothing announced it; the suite
# simply went on saying OK.
#
# TWO SHAPES, and the second is worse:
#
#   gated assert   `if <ambient>: assert …`   the assertion runs on some machines only
#   gated return   `if <ambient>: return`     the test STOPS and reports a pass. Strictly
#                                             worse than skipTest(), which at least shows up
#                                             in the count the skip audit reads.
#
# WHAT IT WILL NOT FLAG, because a sweep whose first findings are false is switched off within
# a week — this fleet's own rule, and a detector written for this class cried wolf twice before
# this one (74% of the suite, then a fake-fetch route matched on the word "Available"):
#
#   * a DATA-shaped branch (`if rows: assert rows[0] …`) — ordinary and correct
#   * a branch on a LOCAL variable, a fixture, or a parameter — the test controls it
#   * `unittest.skipUnless(...)` / `pytest.mark.skipif` — a declared skip, which is the skip
#     audit's business, not this one's
#
# It matches the CONDITION by AST, never by words, against a tight set of capability
# predicates: a call whose name ends `available` / `_present` / `is_installed`, a NAME of the
# `HAVE_*` / `_HAVE*` / `HAS_*` / `*_ENGINE` shape, `importlib.util.find_spec`, `shutil.which`,
# and the platform reads. A name is only ambient when it is NOT assigned inside the function,
# which is what keeps a local flag out of the findings.
# ============================================================================
"""Find an assertion or a return gated on an ambient capability. See the header."""
from __future__ import annotations

import ast
import os
from typing import Dict, Iterable, List, Optional

__all__ = ["find", "Finding", "AMBIENT_CALL_SUFFIXES", "AMBIENT_NAME_SHAPES"]

#: a CALL is ambient when its name ends with one of these
AMBIENT_CALL_SUFFIXES = ("available", "_present", "is_installed", "_installed",
                         "find_spec", "which", "system")
#: a NAME is ambient when it matches one of these shapes AND is not assigned in the function
AMBIENT_NAME_SHAPES = ("HAVE_", "_HAVE", "HAS_", "_HAS", "_ENGINE", "_SELENIUM")
#: attribute reads that are ambient on their own
AMBIENT_ATTRS = {("sys", "platform"), ("os", "name")}


class Finding(dict):
    """{path, test, line, kind, condition}. A dict so callers can json it without a shim."""


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_ambient(test: ast.AST, assigned: set) -> bool:
    """Does this condition ask the MACHINE rather than the data?"""
    for n in ast.walk(test):
        if isinstance(n, ast.Call):
            name = _call_name(n.func)
            if name and any(name.lower().endswith(s) for s in AMBIENT_CALL_SUFFIXES):
                # a method on something the test built is the test's own business
                recv = n.func.value if isinstance(n.func, ast.Attribute) else None
                if isinstance(recv, ast.Name) and recv.id in assigned:
                    continue
                return True
        if isinstance(n, ast.Attribute):
            base = n.value
            if isinstance(base, ast.Name) and (base.id, n.attr) in AMBIENT_ATTRS:
                return True
            if any(s in n.attr for s in AMBIENT_NAME_SHAPES) and n.attr not in assigned:
                return True
        if isinstance(n, ast.Name):
            if any(s in n.id for s in AMBIENT_NAME_SHAPES) and n.id not in assigned:
                return True
    return False


def _asserts(body: Iterable[ast.stmt]) -> bool:
    for stmt in body:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Assert):
                return True
            if isinstance(n, ast.Call):
                name = _call_name(n.func)
                if name.startswith("assert") or name == "fail":
                    return True
    return False


def _returns(body: Iterable[ast.stmt]) -> bool:
    return any(isinstance(s, ast.Return) for s in body)


def _assigned_names(fn: ast.AST) -> set:
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store,)):
            out.add(n.id)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
    return out


def find(paths: Iterable[str], *, allow: Optional[Dict[str, str]] = None) -> List[Finding]:
    """Findings across these test files, skipping any `test_name` in `allow`.

    `allow` maps a test name to WHY the branch is legitimate. A bare list would let an entry be
    added without a reason, which is how an allowlist becomes a loophole.
    """
    allow = allow or {}
    out: List[Finding] = []
    for path in paths:
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test") or fn.name in allow:
                continue
            assigned = _assigned_names(fn)
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                if not _is_ambient(node.test, assigned):
                    continue
                try:
                    cond = ast.unparse(node.test)
                except Exception:                                    # pragma: no cover
                    cond = "<unparseable>"
                kind = None
                if _returns(node.body):
                    kind = "gated_return"
                elif _asserts(node.body) or _asserts(node.orelse):
                    kind = "gated_assert"
                if kind:
                    out.append(Finding(path=os.path.relpath(path), test=fn.name,
                                       line=node.lineno, kind=kind, condition=cond))
    return out
