#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc_records — the four records that keep a repo's progress documentation honest.

Owner 2026-10-13, asked what would improve how progress is documented, chose all five suggestions:
a decision register, no hand-typed counts, a slim CLAUDE.md, one list of what is still unverified,
and the conversation maps joined across sessions. Four of them are mechanisms, and live here:

  decisions   docs/DECISIONS.md is a hand-kept register (the "supersedes" link is a judgement, so a
              tool cannot write it). This CHECKS it: ids unique, dates real, and every supersession
              recorded on BOTH rows, so a rule cannot outlive the decision that replaced it without
              the register saying so. `--unregistered` lists owner quotes in the docs that the
              register does not cite yet (a review aid, never a failure).
  counts      A number written in prose goes between markers, <!--count:ID-->27<!--/count-->, and
              docs/counts.json says how to measure it ({"ID": {"cmd": "...", "about": "..."}}).
              `--check` runs each command and fails on a mismatch; `--update` writes the measured
              value in. A command that fails is a failure, never a pass.
  unverified  Writes docs/UNVERIFIED.md: every sentence in CLAUDE.md and docs/ that says something
              was built but not tried for real (UNVERIFIED, SIMULATED, built without egress, not yet
              run …), grouped by file and heading. Generated; edit the source, not the list.
  threads     Writes docs/THREADS.md: every handover's "Conversation map" section, newest first, so
              an idea that ran across several sessions can be followed without opening each handover.

    python .toolbox/instincts/doc_records.py all            # write unverified + threads, check the rest
    python .toolbox/instincts/doc_records.py counts --update
    python .toolbox/instincts/doc_records.py decisions --unregistered

Stdlib only. Honest-empty: a repo with no register or no counts file is told so, and passes (the
record does not exist yet; that is not a broken record). Exit 1 only on a check that ran and failed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from handover import _SEARCH as _HANDOVER_GLOBS, _name_date, _name_sequence, parse_handover
except Exception:  # noqa: BLE001 — a standalone copy without handover.py: threads says so
    _HANDOVER_GLOBS = ()
    parse_handover = None  # type: ignore[assignment]

DECISIONS = "docs/DECISIONS.md"
# Fleet-wide decisions live ONCE, in the instincts bundle every repo checks out (ids F<n>); a repo's
# own register (ids D<n>) may supersede one, and the check resolves ids across both.
FLEET = ("library/instincts/FLEET_DECISIONS.md", ".toolbox/instincts/FLEET_DECISIONS.md")
COUNTS = "docs/counts.json"
UNVERIFIED = "docs/UNVERIFIED.md"
THREADS = "docs/THREADS.md"
GENERATED = ("UNVERIFIED.md", "THREADS.md", "COPY_PASTE.md")
# Folders of dated records (what a past session found), not statements about the code as it is now.
_DATED_DIRS = {"learnings", "runs", "archive", "_archive"}

# ---------------------------------------------------------------------------------------- shared

def _docs(root: str) -> List[str]:
    """CLAUDE.md + every markdown file under docs/, minus the generated records and the handovers
    (a handover is a dated record of a past session, not a statement about the code now)."""
    out = []
    top = os.path.join(root, "CLAUDE.md")
    if os.path.isfile(top):
        out.append(top)
    for p in sorted(glob.glob(os.path.join(root, "docs", "**", "*.md"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        parts = rel.split("/")[1:-1]
        if os.path.basename(p) in GENERATED or any(d in _DATED_DIRS or d.startswith("handover") for d in parts):
            continue
        out.append(p)
    return out


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)

# ------------------------------------------------------------------------------------- decisions

_ROW = re.compile(r"^\|\s*([DF]\d+)\s*\|(.*)\|\s*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDS = re.compile(r"\b[DF]\d+\b")


def parse_decisions(text: str) -> List[Dict[str, str]]:
    """Rows of the register: | id | date | decision | in force | supersedes | where |."""
    rows = []
    for n, ln in enumerate(text.splitlines(), 1):
        m = _ROW.match(ln.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        cells += [""] * (5 - len(cells))
        rows.append({"id": m.group(1), "date": cells[0], "decision": cells[1], "status": cells[2],
                     "supersedes": cells[3], "where": cells[4], "line": str(n), "ncells": str(len(cells))})
    return rows


def check_decisions(text: str, others: str = "") -> List[str]:
    """Problems in `text`'s register. `others` is the OTHER register (fleet or repo) whose ids the
    links may name; a link across the two is checked on both rows like any other."""
    rows = parse_decisions(text)
    foreign = {r["id"]: r for r in parse_decisions(others)}
    problems: List[str] = []
    by_id: Dict[str, Dict[str, str]] = {}
    for r in rows:
        where = f"line {r['line']} {r['id']}"
        if r["id"] in by_id:
            problems.append(f"{where}: id used twice (first on line {by_id[r['id']]['line']})")
        by_id.setdefault(r["id"], r)
        if int(r["ncells"]) != 5:
            problems.append(f"{where}: {r['ncells']} cells after the id, expected 5 (a '|' inside a cell?)")
        if not _DATE.match(r["date"]):
            problems.append(f"{where}: date {r['date']!r} is not YYYY-MM-DD")
        if not r["decision"]:
            problems.append(f"{where}: no decision text")
    known = {**foreign, **by_id}
    for r in rows:
        where = f"line {r['line']} {r['id']}"
        for old in _IDS.findall(r["supersedes"]):
            if old not in known:
                problems.append(f"{where}: supersedes {old}, which is not in the register")
            elif r["id"] not in _IDS.findall(known[old]["status"]):
                problems.append(f"{where}: supersedes {old}, but {old}'s status does not say "
                                f"'superseded by {r['id']}' — the old rule still reads as in force")
        if "superseded" in r["status"].lower():
            for new in _IDS.findall(r["status"]):
                if new not in known:
                    problems.append(f"{where}: says superseded by {new}, which is not in the register")
                elif r["id"] not in _IDS.findall(known[new]["supersedes"]):
                    problems.append(f"{where}: says superseded by {new}, but {new} does not list "
                                    f"{r['id']} under supersedes")
            if not _IDS.findall(r["status"]):
                problems.append(f"{where}: superseded, but by which decision? name its id")
    return problems


_QUOTE = re.compile(r"owner,?\s+(\d{4}-\d{2}-\d{2})[^*\n]{0,80}?\*\"([^\"]{12,}?)\"", re.I)


def unregistered(root: str, register: str) -> List[Tuple[str, str, str]]:
    """Owner quotes in the docs whose date + opening words the register does not carry."""
    reg = re.sub(r"\s+", " ", register.lower())
    out, seen = [], set()
    for p in _docs(root):
        if p.endswith(DECISIONS.split("/")[-1]):
            continue
        for m in _QUOTE.finditer(_read(p)):
            date, quote = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            key = (date, quote[:40].lower())
            if key in seen:
                continue
            seen.add(key)
            if date in reg and quote[:25].lower() in reg:
                continue
            out.append((os.path.relpath(p, root), date, quote[:140]))
    return out

# ----------------------------------------------------------------------------------------- counts

_COUNT = re.compile(r"<!--\s*count:([A-Za-z0-9_.-]+)\s*-->(.*?)<!--\s*/count\s*-->", re.S)


def _quoted(text: str, m: "re.Match[str]") -> bool:
    """A marker written as an EXAMPLE, inside an inline code span (`<!--count:ID-->…`), is not a count."""
    return m.start() > 0 and text[m.start() - 1] == "`"


def _measure(root: str, spec: dict) -> Tuple[str, str]:
    """(value, error). The value is the command's last non-blank stdout line."""
    cmd = spec.get("cmd") if isinstance(spec, dict) else None
    if not cmd:
        return "", "no cmd in counts.json"
    try:
        r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "", "timed out after 300s"
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if r.returncode != 0 or not lines:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["no output"]
        return "", f"exit {r.returncode}: {tail[0][:160]}"
    return lines[-1], ""


def counts(root: str, update: bool = False) -> Tuple[List[str], List[str]]:
    """(problems, notes). Measures each id once, then compares or rewrites every marker."""
    path = os.path.join(root, COUNTS)
    files = {p: _read(p) for p in _docs(root)}
    used = {m.group(1) for t in files.values() for m in _COUNT.finditer(t) if not _quoted(t, m)}
    if not os.path.isfile(path):
        return ([f"{len(used)} count marker(s) but no {COUNTS} to measure them"] if used else [],
                [f"no {COUNTS} and no count markers — nothing to check"])
    try:
        specs = json.loads(_read(path))
    except ValueError as e:
        return [f"{COUNTS} does not parse: {e}"], []
    problems, notes, measured = [], [], {}
    for cid in sorted(used):
        if cid not in specs:
            problems.append(f"marker count:{cid} has no entry in {COUNTS}")
            continue
        val, err = _measure(root, specs[cid])
        if err:
            problems.append(f"count:{cid} could not be measured ({err})")
        else:
            measured[cid] = val
    for cid in sorted(set(specs) - used):
        notes.append(f"{COUNTS} entry {cid} is used by no marker")
    for p, text in files.items():
        rel = os.path.relpath(p, root)

        def fix(m: "re.Match[str]") -> str:
            if _quoted(text, m):
                return m.group(0)
            cid, shown = m.group(1), m.group(2).strip()
            if cid in measured and shown != measured[cid]:
                if not update:
                    problems.append(f"{rel}: count:{cid} says {shown!r}, measured {measured[cid]!r}")
                return m.group(0).replace(m.group(2), measured[cid], 1) if update else m.group(0)
            return m.group(0)

        new = _COUNT.sub(fix, text)
        if update and new != text:
            _write(p, new)
            notes.append(f"updated {rel}")
    notes.append(f"{len(measured)} of {len(used)} count(s) measured")
    return problems, notes

# ------------------------------------------------------------------------------------- unverified

MARKERS = re.compile(
    r"\bUNVERIFIED\b|\bSIMULATED\b|built without (?:egress|a live|the real)|without egress"
    r"|not (?:yet )?live[- ]verified|not yet (?:run|tried|verified)|never (?:run|tried) live"
    r"|built,? (?:but |and )?not (?:yet )?(?:live[- ])?(?:verified|tried|run)"
    r"|until the owner'?s first (?:live )?run|first live run is the check", re.I)
_DEFINES_LABELS = re.compile(r"MEASURED.{0,40}SIMULATED.{0,40}REASONED", re.S)
_FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})[\w+.-]*\s*$")   # a fence line alone, not an inline ```` span
_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`(\"])")


def _paragraphs(text: str):
    """(heading, paragraph) pairs; a bullet or a heading starts a new paragraph; code is skipped."""
    head, buf, fence = "", [], False
    for ln in text.splitlines() + [""]:
        if _FENCE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        h = _HEAD.match(ln)
        bullet = re.match(r"^\s*(?:[-*]|\d+\.)\s+", ln)
        if h or not ln.strip() or bullet:
            if buf:
                yield head, " ".join(buf)
                buf = []
            if h:
                head = h.group(2).strip()
                continue
            if not ln.strip():
                continue
        buf.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", ln).strip())


def unverified_items(root: str) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}
    for p in _docs(root):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        items = []
        for head, para in _paragraphs(_read(p)):
            for s in _SENT.split(para):
                # A sentence naming all three evidence labels is DEFINING them, not reporting a gap.
                if MARKERS.search(s) and not _DEFINES_LABELS.search(s):
                    s = s.strip()
                    items.append((head, s if len(s) <= 360 else s[:357] + "…"))
        if items:
            out[rel] = items
    return out


def render_unverified(items: Dict[str, List[Tuple[str, str]]]) -> str:
    n = sum(len(v) for v in items.values())
    lines = ["# Still unverified", "",
             "<!-- GENERATED by doc_records.py unverified — do not edit here. Each line is a sentence from",
             "     the file named above it; fix or remove the sentence THERE once the thing has been tried",
             "     for real, and the next cleanup drops it from this list. -->", "",
             f"{n} statement(s) in {len(items)} file(s) say something was built but not yet tried for "
             "real (on the owner's box, against the live source, or with real data). This is the list "
             "of what still needs a live check.", ""]
    if not items:
        lines.append("Nothing is marked unverified.")
    for rel in sorted(items):
        lines += [f"## {rel}", ""]
        last = None
        for head, s in items[rel]:
            if head != last:
                lines.append(f"- **{head or '(top)'}**")
                last = head
            lines.append(f"  - {s}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

# ---------------------------------------------------------------------------------------- threads

def handover_files(root: str) -> List[str]:
    found = set()
    for g in _HANDOVER_GLOBS:
        found.update(glob.glob(os.path.join(root, g)))
    return sorted(found, key=lambda p: (_name_date(p), _name_sequence(p), os.path.basename(p)),
                  reverse=True)


def render_threads(root: str) -> Tuple[str, int]:
    if parse_handover is None:
        return "", 0
    sections = []
    for p in handover_files(root):
        links = parse_handover(_read(p)).get("map") or []
        if links:
            date = _name_date(p) or "undated"
            link = os.path.relpath(p, os.path.join(root, "docs")).replace(os.sep, "/")
            sections.append(f"## {date} · [{os.path.basename(p)}]({link})\n\n"
                            + "\n".join(f"- {ln}" for ln in links) + "\n")
    head = ("# Threads — how the ideas connected, session by session\n\n"
            "<!-- GENERATED by doc_records.py threads from each handover's \"Conversation map\" section,\n"
            "     newest first. Edit the handover, not this file. -->\n\n"
            "Each session's map, in order. Follow an idea backwards by reading down: a `↺ back to:` "
            "link names an earlier thread, and a `⏸ parked:` one is picked up in a later session.\n\n")
    if not sections:
        return head + "No handover carries a conversation map yet.\n", 0
    return head + "\n".join(sections), len(sections)

# ------------------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=["decisions", "counts", "unverified", "threads", "all"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", action="store_true", help="unverified/threads: fail if the file is stale")
    ap.add_argument("--update", action="store_true", help="counts: write measured values in")
    ap.add_argument("--unregistered", action="store_true", help="decisions: list uncited owner quotes")
    ap.add_argument("--print", action="store_true", help="print the generated file instead of writing it")
    a = ap.parse_args(argv)
    root, bad = a.root, False

    if a.what in ("decisions", "all"):
        regs = {}
        for rel in (DECISIONS,) + FLEET:
            if os.path.isfile(os.path.join(root, rel)) and not (rel in FLEET and any(f in regs for f in FLEET)):
                regs[rel] = _read(os.path.join(root, rel))
        if not regs:
            print(f"decisions: no {DECISIONS} yet — nothing to check")
        for rel, text in regs.items():
            other = "\n".join(t for r2, t in regs.items() if r2 != rel)
            probs = check_decisions(text, other)
            print(f"decisions: {rel}: {len(parse_decisions(text))} row(s), {len(probs)} problem(s)")
            for pr in probs:
                print(f"  ✗ {pr}")
            bad |= bool(probs)
        if a.unregistered and regs:
            for rel, date, q in unregistered(root, "\n".join(regs.values())):
                print(f"  ? {rel} · {date} · \"{q}\"")

    if a.what in ("counts", "all"):
        probs, notes = counts(root, update=a.update)
        for n in notes:
            print(f"counts: {n}")
        for pr in probs:
            print(f"  ✗ {pr}")
        bad |= bool(probs)

    for name, rel, build in (("unverified", UNVERIFIED, lambda: render_unverified(unverified_items(root))),
                             ("threads", THREADS, lambda: render_threads(root)[0])):
        if a.what not in (name, "all"):
            continue
        text = build()
        if not text:
            print(f"{name}: handover.py is not beside this file — cannot read the maps")
            continue
        path = os.path.join(root, rel)
        if a.print:
            print(text)
        elif a.check:
            same = os.path.isfile(path) and _read(path) == text
            print(f"{name}: {rel} {'up to date' if same else 'is STALE — run without --check'}")
            bad |= not same
        else:
            _write(path, text)
            print(f"{name}: wrote {rel}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
