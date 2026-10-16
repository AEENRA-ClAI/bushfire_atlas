# -*- coding: utf-8 -*-
"""Headless project management: read the fleet's project files, write nothing but a new one.

A project is declared once, in its home repo, as `docs/projects/<id>.md` (the format is in
`PROJECT_FORMAT.md` beside this file). This module reads those files for a Claude session, for
Janet and for anyone at a terminal. There is no database and no UI: the files are the store
(owner 2026-10-14: "a little bit more structured, but also a little bit more headless").

    python .toolbox/pm/pm.py status                    # this repo's projects
    python .toolbox/pm/pm.py status --fleet ..         # every sibling repo's projects
    python .toolbox/pm/pm.py scope <id>
    python .toolbox/pm/pm.py next [<id>]
    python .toolbox/pm/pm.py score <id>
    python .toolbox/pm/pm.py new <id> --title "..."    # the only command that writes

Every read command takes `--json`. Honest empty: "no projects declared" (no file at all) and
"could not read <file>: <why>" (a file that is there but broken) are different results, and a
broken file never hides the readable ones beside it.

Stdlib only, so it runs in every checkout. Shipped as the toolbox bundle `pm`; `handover.py` in
the `instincts` bundle imports it to print the active-project line at session start.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

PROJECTS_DIR = os.path.join("docs", "projects")
BACKLOGS = ("docs/BACKLOG.md", "docs/APP_BACKLOG.md")

# The front block is strict: these keys and no others, so a typo is an error, not a silent blank.
REQUIRED_KEYS = ("id", "title", "status", "repos")
OPTIONAL_KEYS = ("owner", "home", "horizon", "started")
PROJECT_STATUSES = ("proposed", "active", "paused", "done", "dropped")
OBJECTIVE_STATUSES = ("open", "PASS", "PARTIAL", "FAIL")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}")


class ProjectError(ValueError):
    """A project file that is there but cannot be read as one. The message says why."""


# --- parsing ------------------------------------------------------------------------------------

def _front_block(lines: "list[str]") -> "tuple[dict, int]":
    if not lines or lines[0].strip() != "---":
        raise ProjectError("the first line must be `---` (the front block)")
    meta: dict = {}
    for n, raw in enumerate(lines[1:], start=1):
        line = raw.strip()
        if line == "---":
            break
        if not line:
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep:
            raise ProjectError(f"front block line {n + 1} is not `key: value`")
        if key not in REQUIRED_KEYS + OPTIONAL_KEYS:
            raise ProjectError(f"unknown front-block key `{key}`")
        if key in meta:
            raise ProjectError(f"front-block key `{key}` appears twice")
        meta[key] = value.strip()
    else:
        raise ProjectError("the front block has no closing `---`")
    missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
    if missing:
        raise ProjectError("front block is missing " + ", ".join(f"`{k}`" for k in missing))
    if not _ID_RE.match(meta["id"]):
        raise ProjectError(f"id `{meta['id']}` must be lower-case letters, digits and dashes")
    if meta["status"] not in PROJECT_STATUSES:
        raise ProjectError(f"status `{meta['status']}` is not one of {', '.join(PROJECT_STATUSES)}")
    meta["repos"] = [r.strip() for r in meta["repos"].split(",") if r.strip()]
    return meta, n + 1


def _sections(lines: "list[str]") -> "dict[str, list[str]]":
    out: "dict[str, list[str]]" = {}
    current = None
    for ln in lines:
        h = _HEADING_RE.match(ln)
        if h:
            current = h.group(1).strip().lower()
            out[current] = []
        elif current is not None:
            out[current].append(ln)
    return out


def _table_rows(lines: "list[str]") -> "list[list[str]]":
    """The body rows of the first markdown table in `lines` (header and separator dropped)."""
    rows = [ln.strip() for ln in lines if ln.strip().startswith("|")]
    body = [r for r in rows[1:] if not _SEPARATOR_RE.match(r)]
    return [[c.strip() for c in r.strip("|").split("|")] for r in body]


def parse_project(text: str, filename: str = "") -> dict:
    """One project file → a dict. Raises ProjectError naming what is wrong."""
    lines = (text or "").splitlines()
    meta, end = _front_block(lines)
    if filename:
        stem = os.path.splitext(os.path.basename(filename))[0]
        if stem != meta["id"]:
            raise ProjectError(f"id `{meta['id']}` does not match the file name `{stem}.md`")
    sec = _sections(lines[end:])
    for need in ("scope", "objectives"):
        if need not in sec:
            raise ProjectError(f"no `## {need.title()}` section")

    scope = {"in": [], "out": []}
    for row in _table_rows(sec["scope"]):
        side = row[0].lower() if row else ""
        if side not in scope or len(row) < 2:
            raise ProjectError(f"scope row `{' | '.join(row)}` must start with `in` or `out`")
        scope[side].append(row[1])

    objectives = []
    for row in _table_rows(sec["objectives"]):
        if len(row) < 4:
            raise ProjectError(f"objective row `{' | '.join(row)}` needs id, objective, gate, status")
        oid, objective, gate, status = row[:4]
        evidence = row[4] if len(row) > 4 else ""
        if status not in OBJECTIVE_STATUSES:
            raise ProjectError(f"objective {oid} status `{status}` is not one of "
                               + ", ".join(OBJECTIVE_STATUSES))
        if not gate:
            raise ProjectError(f"objective {oid} has no gate (a pass/fail check is required)")
        objectives.append({"id": oid, "objective": objective, "gate": gate,
                           "status": status, "evidence": evidence})
    if not objectives:
        raise ProjectError("`## Objectives` has no rows")

    decisions = [{"date": r[0], "decision": r[1] if len(r) > 1 else "",
                  "where": r[2] if len(r) > 2 else ""}
                 for r in _table_rows(sec.get("owner decisions", []))]
    return {**{k: meta.get(k, "") for k in OPTIONAL_KEYS}, **meta,
            "scope": scope, "objectives": objectives, "decisions": decisions}


# --- finding and reading ------------------------------------------------------------------------

def project_files(root: str) -> "list[str]":
    return sorted(glob.glob(os.path.join(root, PROJECTS_DIR, "*.md")))


def read_repo(root: str) -> dict:
    """{repo, root, projects: [...], unreadable: [{file, reason}]} for one repo. Never raises."""
    repo = os.path.basename(os.path.abspath(root))
    projects, unreadable = [], []
    for fp in project_files(root):
        rel = os.path.relpath(fp, root)
        try:
            with open(fp, encoding="utf-8") as fh:
                p = parse_project(fh.read(), fp)
        except (OSError, UnicodeDecodeError, ProjectError) as exc:
            unreadable.append({"repo": repo, "file": rel, "reason": str(exc)})
            continue
        p["repo"], p["file"] = repo, rel
        p["home"] = p.get("home") or repo
        projects.append(p)
    return {"repo": repo, "root": root, "projects": projects, "unreadable": unreadable}


def fleet_roots(fleet: str) -> "list[str]":
    """Each immediate sub-folder of `fleet` that is a repo (has a `.git`)."""
    if not os.path.isdir(fleet):
        return []
    return sorted(os.path.join(fleet, d) for d in os.listdir(fleet)
                  if os.path.exists(os.path.join(fleet, d, ".git")))


def gather(root: str = ".", fleet: str = "") -> dict:
    """Every project in scope: one repo (`root`) or every repo under `fleet`."""
    roots = fleet_roots(fleet) if fleet else [root]
    reads = [read_repo(r) for r in roots]
    projects = [p for r in reads for p in r["projects"]]
    unreadable = [u for r in reads for u in r["unreadable"]]
    if projects or unreadable:
        empty = ""
    elif fleet and not roots:
        empty = f"no repos found under {fleet}"
    else:
        empty = "no projects declared"
    return {"scanned": [r["repo"] for r in reads], "projects": projects,
            "unreadable": unreadable, "empty": empty}


def next_open(project: dict) -> "dict | None":
    """The first objective, in file order, that has not PASSed."""
    return next((o for o in project["objectives"] if o["status"] != "PASS"), None)


def score(project: dict) -> dict:
    counts = {s: 0 for s in OBJECTIVE_STATUSES}
    for o in project["objectives"]:
        counts[o["status"]] += 1
    return counts


def tagged_backlog(root: str, pid: str) -> "list[str]":
    """Backlog rows in the project's home repo that carry `[P:<id>]`."""
    tag, out = f"[P:{pid}]", []
    for rel in BACKLOGS:
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
                out += [f"{rel}: {ln.strip()}" for ln in fh if tag in ln]
        except FileNotFoundError:
            continue
    return out


def active(projects: "list[dict]") -> "list[dict]":
    return [p for p in projects if p["status"] == "active"]


# --- commands -----------------------------------------------------------------------------------

def _find(found: dict, pid: str) -> "dict | None":
    return next((p for p in found["projects"] if p["id"] == pid), None)


def _not_found(found: dict, pid: str) -> dict:
    bad = [u for u in found["unreadable"] if os.path.splitext(os.path.basename(u["file"]))[0] == pid]
    if bad:
        return {"error": f"could not read {bad[0]['repo']}/{bad[0]['file']}: {bad[0]['reason']}"}
    return {"error": f"no project `{pid}` declared in {', '.join(found['scanned']) or 'nothing scanned'}"}


def _summary(p: dict) -> dict:
    nxt = next_open(p)
    return {"id": p["id"], "title": p["title"], "status": p["status"], "repo": p["repo"],
            "file": p["file"], "repos": p["repos"], "score": score(p), "next": nxt}


def cmd_status(found: dict) -> dict:
    return {"scanned": found["scanned"], "projects": [_summary(p) for p in found["projects"]],
            "unreadable": found["unreadable"], "empty": found["empty"]}


def cmd_scope(found: dict, pid: str) -> dict:
    p = _find(found, pid)
    if not p:
        return _not_found(found, pid)
    return {k: p[k] for k in ("id", "title", "status", "owner", "home", "horizon", "repo",
                              "file", "repos", "scope", "objectives", "decisions")}


def cmd_next(found: dict, pid: str = "", roots: "dict | None" = None) -> dict:
    if pid:
        p = _find(found, pid)
        if not p:
            return _not_found(found, pid)
        chosen = [p]
    else:
        chosen = active(found["projects"])
    out = []
    for p in chosen:
        root = (roots or {}).get(p["repo"], "")
        out.append({"id": p["id"], "title": p["title"], "repo": p["repo"],
                    "open": [o for o in p["objectives"] if o["status"] != "PASS"],
                    "backlog": tagged_backlog(root, p["id"]) if root else []})
    empty = "" if out else (found["empty"] or "no active projects")
    return {"projects": out, "unreadable": found["unreadable"], "empty": empty}


def cmd_score(found: dict, pid: str) -> dict:
    p = _find(found, pid)
    if not p:
        return _not_found(found, pid)
    return {"id": p["id"], "title": p["title"], "score": score(p),
            "objectives": [{k: o[k] for k in ("id", "status", "gate", "evidence")}
                           for o in p["objectives"]]}


TEMPLATE = """---
id: {id}
title: {title}
status: proposed
owner: {owner}
home: {home}
repos: {repos}
horizon:
---

# {title}

## Scope

| side | item |
|---|---|
| in | <what this project delivers> |
| out | <what it deliberately does not> |

## Objectives

| id | objective | gate (checkable) | status | evidence |
|---|---|---|---|---|
| O1 | <the first outcome> | <a named test, a command's output, or what she sees on her box> | open | |

## Owner decisions

| date | decision | where |
|---|---|---|

## Next

- <backlog rows that serve this project carry `[P:{id}]`>
"""


def cmd_new(root: str, pid: str, title: str, repos: str, owner: str) -> dict:
    if not _ID_RE.match(pid):
        return {"error": f"id `{pid}` must be lower-case letters, digits and dashes"}
    path = os.path.join(root, PROJECTS_DIR, f"{pid}.md")
    if os.path.exists(path):
        return {"error": f"{os.path.relpath(path, root)} already exists; edit it instead"}
    home = os.path.basename(os.path.abspath(root))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(TEMPLATE.format(id=pid, title=title or pid, owner=owner, home=home,
                                 repos=repos or home))
    return {"created": os.path.relpath(path, root)}


# --- text rendering -----------------------------------------------------------------------------

def _unreadable_lines(items: "list[dict]") -> "list[str]":
    return [f"could not read {u['repo']}/{u['file']}: {u['reason']}" for u in items]


def render_text(cmd: str, res: dict) -> str:
    if res.get("error"):
        return res["error"]
    if cmd == "new":
        return f"created {res['created']}"
    lines: "list[str]" = []
    if cmd == "status":
        for p in res["projects"]:
            s, nxt = p["score"], p["next"]
            tally = " ".join(f"{k}:{v}" for k, v in s.items() if v)
            n = f"next {nxt['id']}: {nxt['objective']}" if nxt else "every objective PASS"
            lines.append(f"{p['repo']}/{p['id']} [{p['status']}] {p['title']} — {tally} — {n}")
    elif cmd == "scope":
        lines += [f"{res['id']} [{res['status']}] {res['title']}",
                  f"repos: {', '.join(res['repos'])}"]
        lines += [f"  in:  {x}" for x in res["scope"]["in"]]
        lines += [f"  out: {x}" for x in res["scope"]["out"]]
        lines += [f"  {o['id']} [{o['status']}] {o['objective']} — gate: {o['gate']}"
                  for o in res["objectives"]]
        lines += [f"  decided {d['date']}: {d['decision']}" for d in res["decisions"]]
    elif cmd == "next":
        for p in res["projects"]:
            lines.append(f"{p['repo']}/{p['id']} {p['title']}")
            lines += [f"  {o['id']} [{o['status']}] {o['objective']} — gate: {o['gate']}"
                      for o in p["open"]] or ["  every objective PASS"]
            lines += [f"  backlog {b}" for b in p["backlog"]]
    elif cmd == "score":
        lines.append(f"{res['id']} {res['title']}: "
                     + " ".join(f"{k}:{v}" for k, v in res["score"].items()))
        lines += [f"  {o['id']} {o['status']}" + (f" — {o['evidence']}" if o["evidence"] else "")
                  for o in res["objectives"]]
    if res.get("empty") and not lines:
        lines.append(res["empty"])
    lines += _unreadable_lines(res.get("unreadable", []))
    return "\n".join(lines)


# --- entry point --------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pm", description="Read the fleet's project files.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, needs_id in (("status", False), ("scope", True), ("next", None), ("score", True)):
        sp = sub.add_parser(name)
        if needs_id:
            sp.add_argument("id")
        elif needs_id is None:
            sp.add_argument("id", nargs="?", default="")
        sp.add_argument("--root", default=".", help="the repo to read (default: here)")
        sp.add_argument("--fleet", default="", help="read every repo under this folder instead")
        sp.add_argument("--json", action="store_true", help="print JSON")
    sp = sub.add_parser("new", help="scaffold docs/projects/<id>.md (the only write)")
    sp.add_argument("id")
    sp.add_argument("--root", default=".")
    sp.add_argument("--title", default="")
    sp.add_argument("--repos", default="", help="comma-separated; default: this repo")
    sp.add_argument("--owner", default="")
    sp.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        res = cmd_new(args.root, args.id, args.title, args.repos, args.owner)
    else:
        found = gather(args.root, args.fleet)
        roots = {os.path.basename(os.path.abspath(r)): r
                 for r in (fleet_roots(args.fleet) if args.fleet else [args.root])}
        res = {"status": lambda: cmd_status(found),
               "scope": lambda: cmd_scope(found, args.id),
               "next": lambda: cmd_next(found, args.id, roots),
               "score": lambda: cmd_score(found, args.id)}[args.cmd]()
    print(json.dumps(res, indent=1, ensure_ascii=False) if args.json else render_text(args.cmd, res))
    return 1 if res.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
