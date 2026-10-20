# -*- coding: utf-8 -*-
"""Surface the last handover at session start — the roster it needs + the work to look over.

The other half of the memory loop. Session cleanup writes a handover with a **Roster** line (the
agents the next session's work needs — e.g. a data-pipeline task lists `data_reviewers,
security-reviewer, deep-research`) and a **Leftover / for review** checklist (open items, each
tagged with the agent that should look at it). This reader finds the most recent handover, parses
those two, and prints a SessionStart block so the next session starts already knowing WHICH agents to
pull in and WHAT to pick up.

Self-contained (stdlib), shipped in the `instincts` bundle beside `inject.py`, run by the SessionStart
hook:  python .toolbox/instincts/handover.py --root .

Honest-empty: no handover, or no roster/leftover in it, prints nothing (never breaks a session).
"""
from __future__ import annotations

import argparse
import glob
import os
import re

# Where handovers commonly live, newest wins. Override with --path.
_SEARCH = (
    "docs/handover/*.md", "docs/Claude/handover/*.md", "docs/pipelines/handover/*.md",
    "docs/handover*.md", "HANDOVER.md", "docs/HANDOVER.md",
)

_ROSTER_RE = re.compile(r"^\s*[*_#>\s]*(?:roster|agents(?:\s+needed)?)\s*[:\-]\s*(.+?)\s*$", re.I)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_LEFTOVER_HEAD_RE = re.compile(
    # bare "next" was too greedy — it matched a "Notes / how to run it NEXT time" heading and swept the
    # notes into the leftover list (2026-09-07 dogfood). Require a real to-do phrase.
    r"(leftover|for[\s-]*review|open\s+items?|unfinished|next\s+(?:session|steps?|up)|"
    r"to[\s-]*do|todo|follow[\s-]*up)", re.I)
# A `*` is a bullet only when a SPACE follows it. Without that guard `\s*` eats the indent of a
# wrapped line and `[-*]` matches the first asterisk of a `**bold**` continuation, so a single
# item that happens to wrap onto a line starting with bold is read as two or three separate
# leftovers. Observed twice: once in the Herdity handover (reworded around it) and once in the
# hub's, which is when it was fixed here instead. `-` stays tolerant of a missing space, since
# `-item` is written by hand often enough and cannot collide with an emphasis marker.
# The "Conversation map" section (owner 2026-10-13): the route the ideas took, one link per bullet.
_MAP_HEAD_RE = re.compile(r"(conversation|idea|thread)s?\s+map|how\s+(?:the\s+)?ideas\s+connected", re.I)
MAP_SHOWN = 15
_BULLET_RE = re.compile(r"^\s*(?:-|\*(?=\s)|\d+\.)\s*(?:\[[ xX]?\]\s*)?(.+?)\s*$")
_OWNER_RE = re.compile(r"^\s*[\(\[]([a-z0-9][a-z0-9 _/,-]{1,60})[\)\]]\s*[:\-]?\s*(.*)$", re.I)


def find_handovers(root: str = ".", path: str = "") -> "list[str]":
    """Every handover that is EQUALLY the newest — normally one. Never raises.

    THE ORDERING RULE, strongest signal first. Each step only breaks ties the step
    above could not:

      1. **The date in the filename** (`session_2026-09-13_x.md`). The author's
         statement of when. mtime cannot do this job: in a fresh clone every
         handover's mtime is its checkout order (the 2026-09-13 trap).
      2. **A counter or a time after that date in the filename** — `_2`, `-3`,
         `T14-30`. An author numbering their own files within a day is stating
         their order outright. A file with no counter sorts before a numbered one
         from the same day (`session_2026-09-13.md` then `..._2.md`).
      3. **Whether the file READS as a handover** — has a Roster line or a
         Leftover checklist, the two machine-read sections. A real handover beats
         a same-day plain write-up sitting next to it. (Same rule copy_paste.py
         already applies.)
      4. **Nothing left ⇒ IT CANNOT KNOW.** mtime is not a fourth signal here,
         it is noise wearing a timestamp: in a fresh clone it is checkout order,
         so using it would silently pick one of two equally-valid handovers and
         look decisive doing it. data_library has up to ten handovers on one date
         across 21 such dates, so this is the common case, not the corner. All
         the tied files are returned and the caller shows them ALL — the fleet's
         honest-empty discipline: say "I cannot tell" rather than guess quietly.
    """
    if path:
        return [path] if os.path.isfile(path) else []
    hits = []
    for pat in _SEARCH:
        hits.extend(glob.glob(os.path.join(root, pat)))
    # Dedupe by real path: two globs can match the SAME file, and without this a
    # file would tie with itself and be reported as an ambiguity.
    seen, uniq = set(), []
    for h in hits:
        if not os.path.isfile(h):
            continue
        key = os.path.realpath(h)
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    if not uniq:
        return []
    # EVERY handover of the newest date (owner 2026-10-13 sprint review): ranking a `_2` above
    # another session's same-day file hid that session's Leftover list at the next start-up, which
    # is how 66 janet_lite leftovers and the toolbox's netwatch and device findings were lost. A
    # counter still ORDERS them (newest first), it no longer removes any. A plain write-up still
    # loses to a real handover on the same day.
    day = max(_name_date(h) for h in uniq)
    same_day = [h for h in uniq if _name_date(h) == day]
    real = [h for h in same_day if _reads_as_handover(h)]
    keep = real or same_day
    return sorted(keep, key=lambda h: (tuple(-n for n in _name_sequence(h)) or (0,), h))


def find_handover(root: str = ".", path: str = "") -> str:
    """The newest handover file, or "" — never raises.

    When several are equally the newest this returns the first by name so callers
    that want ONE file stay deterministic; `find_handovers` is what tells you the
    tie existed, and `main` reports it rather than hiding it.
    """
    found = find_handovers(root, path)
    return found[0] if found else ""


def _rank(path: str) -> tuple:
    """The sort key behind the rule in `find_handovers` — steps 1-3, and nothing else."""
    return (_name_date(path), _name_sequence(path), _reads_as_handover(path))


# A time the author put straight after the date: `..._2026-09-13T14-30.md`.
_SEQ_TIME = re.compile(r"^[_-]?T(\d{1,2})[-.](\d{2})")
# A letter straight after the date: `session_2026-10-13c_….md` is that day's third handover
# (janet_lite writes them so; J31.3, 2026-10-20: the letter was ignored and the next start-up
# printed an earlier file). `b` = 2 … `z` = 26; the plain date is the first.
_SEQ_LETTER = re.compile(r"^([a-z])(?=[_-]|$)")
# A counter at the very END of the name: `..._2.md`, `...-3.md`. Nowhere else.
_SEQ_TRAILING = re.compile(r"[_-](\d{1,3})$")


def _name_sequence(path: str) -> tuple:
    """The counter/time an author put AFTER the date in the filename, as a tuple of ints.

    `session_2026-09-13_2.md` -> (2,);  `..._2026-09-13T14-30.md` -> (14, 30);
    `session_2026-09-13_work_order.md` -> () and sorts first among that day's files.
    A second full date in the name is ignored, so `2026-09-13_for_2026-09-14.md`
    does not read its own second date as a counter.

    **IT REFUSES RATHER THAN GUESSES, and that is the whole point.** This used to take
    every digit anywhere in the tail, which meant janet_lite's
    `session_2026-09-16_j7_themes_panel_browser_proof.md` read as counter **7** and won
    the day outright — not because anyone numbered it, but because the backlog item it
    is named after is called J7. That is worse than the `mtime` rule it replaced: mtime
    was arbitrary and looked it, whereas this was confidently wrong AND suppressed the
    tie report, so nothing said a choice had been made. So:

      * a digit run only counts if it is the LAST thing in the name (`_2`), which is how
        a counter is actually written, or a `T`-time right after the date;
      * more than one standalone number in the tail (`..._seams_1_to_3.md`) is ambiguous
        and returns `()` — the file sorts as uncounted and the caller reports an honest
        tie, which is this module's documented answer to "it cannot know";
      * a digit stuck to a word (`j7`, `v2beta`) is never a counter.

    A false negative here costs a tie report. A false positive costs a silently wrong
    handover, which is the bug this module exists to not have.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    m = _DATE_IN_NAME.search(base)
    tail = base[m.end():] if m else ""
    tail = _DATE_IN_NAME.sub("", tail)
    t = _SEQ_TIME.match(tail)
    if t:
        return (int(t.group(1)), int(t.group(2)))
    letter = _SEQ_LETTER.match(tail)
    if letter:
        return (ord(letter.group(1)) - ord("a") + 1,)
    standalone = [tok for tok in re.split(r"[_-]", tail) if tok.isdigit()]
    if len(standalone) != 1:
        return ()
    c = _SEQ_TRAILING.search(tail)
    return (int(c.group(1)),) if c else ()


def _reads_as_handover(path: str) -> bool:
    """Has a Roster line or a Leftover checklist — the two sections this reader exists to find."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            p = parse_handover(fh.read())
        return bool(p.get("roster") or p.get("leftover") or p.get("map"))
    except Exception:  # noqa: BLE001
        return False


_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _name_date(path: str) -> str:
    """The first YYYY-MM-DD in the file's basename, or "" (sorts below every dated file)."""
    m = _DATE_IN_NAME.search(os.path.basename(path))
    return m.group(1) if m else ""


def _split_tokens(value: str) -> "list[str]":
    # strip surrounding markdown emphasis (**bold** / _italic_) so a "**Roster:**" line doesn't leak a
    # stray "**" onto the first token (2026-09-07 dogfood).
    return [t for t in (raw.strip().strip("*_ ").strip()
                        for raw in re.split(r"[,;/]| and ", value or "")) if t]


def parse_handover(text: str) -> dict:
    """Extract {roster: [tokens], leftover: [{owner, item}], map: [link]} from a handover's markdown.
    Tolerant of formatting; honest-empty when a section is absent."""
    lines = (text or "").splitlines()
    roster: "list[str]" = []
    leftover: "list[dict]" = []
    links: "list[str]" = []
    in_leftover = in_map = False
    leftover_heading = False
    for ln in lines:
        if not roster:
            m = _ROSTER_RE.match(ln)
            if m:
                roster = _split_tokens(m.group(1))
                continue
        h = _HEADING_RE.match(ln)
        if h:
            # The map heading wins: "How the ideas connected" must never collect leftovers.
            in_map = bool(_MAP_HEAD_RE.search(h.group(1)))
            in_leftover = not in_map and bool(_LEFTOVER_HEAD_RE.search(h.group(1)))
            leftover_heading = leftover_heading or in_leftover
            continue
        if in_map:
            b = _BULLET_RE.match(ln)
            if b and b.group(1).strip() and not b.group(1).lstrip().startswith("<"):
                links.append(b.group(1).strip())   # a leftover <placeholder> line is the template's, skipped
            continue
        if in_leftover:
            b = _BULLET_RE.match(ln)
            if b:
                item = b.group(1).strip()
                o = _OWNER_RE.match(item)
                if o and o.group(2).strip():
                    leftover.append({"owner": o.group(1).strip(), "item": o.group(2).strip()})
                elif item:
                    leftover.append({"owner": "", "item": item})
    # A leftover that is one bare token ("janet_lite0") is a list that broke on the way into the
    # file, not an item (J31.4: a handover's whole Leftover read so, and nothing said).
    garbled = [it["item"] for it in leftover if not re.search(r"\s", it["item"])]
    return {"roster": roster, "leftover": leftover, "map": links,
            "leftover_heading": leftover_heading, "leftover_garbled": garbled}


def render(parsed: dict, source: str = "") -> str:
    roster, leftover = parsed.get("roster") or [], parsed.get("leftover") or []
    links = parsed.get("map") or []
    heading = bool(parsed.get("leftover_heading"))
    garbled = parsed.get("leftover_garbled") or []
    if not roster and not leftover and not links and not heading:
        return ""
    lines = ["## From the last handover"]
    if source:
        lines[0] += f"  ({os.path.basename(source)})"
    if roster:
        lines.append("**Suggested agents / rosters for this work:** " + ", ".join(roster))
    if heading and not leftover:
        lines.append("**Open items:** ⚠ the handover HAS a Leftover section and it is EMPTY — "
                     "read the handover by hand; the list may have been cut on the way in.")
    if leftover:
        lines.append("**Open items to look over:**")
        for it in leftover[:20]:
            who = f"({it['owner']}) " if it.get("owner") else ""
            lines.append(f"- {who}{it['item']}")
        if garbled:
            lines.append(f"- ⚠ {len(garbled)} item(s) are one bare word ({', '.join(garbled[:3])}) "
                         "— the list looks garbled; read the handover by hand.")
    if links:
        lines.append("**How the ideas connected last session:**")
        lines.extend(f"- {ln}" for ln in links[:MAP_SHOWN])
        if len(links) > MAP_SHOWN:
            lines.append(f"- … {len(links) - MAP_SHOWN} more links in the handover itself")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Surface the last handover's roster + leftover work.")
    ap.add_argument("--root", default=".", help="repo root to search")
    ap.add_argument("--path", default="", help="a specific handover file (skips the search)")
    args = ap.parse_args(argv)
    found = find_handovers(args.root, args.path)
    start = start_block(args.root)
    blocks = []
    for fp in found:
        try:
            text = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        out = render(parse_handover(text), source=fp)
        if out:
            blocks.append(out)
    if not blocks:
        if start:
            print(start)
        return 0
    if len(blocks) > 1:
        # The filenames alone cannot say which of these is the later one, and mtime
        # in a fresh clone is checkout order, not authorship order. Picking one
        # would be a guess that looks like a decision, so show them all and let the
        # session read both.
        print(f"## {len(blocks)} handovers from the newest date — read them all")
        print("_Several sessions (or one session more than once) wrote a handover that day. Numbered "
              "ones come first. Each carries its own open items; a later one does not replace "
              "another session's._")
        print()
    print("\n\n".join(blocks))
    if start:
        print("\n" + start)
    return 0


# --- the start of a session asks (owner 2026-10-14: "in the startup, ask the questions … what's the
# goal, pass, fail" and "sort a short decision every session") --------------------------------------

QUESTIONS = "docs/QUESTIONS.md"
QUESTIONS_SHOWN = 5
_Q_ROW = re.compile(r"^\|\s*(Q\d+)\s*\|(.*)\|\s*$")


def open_questions(root: str = ".") -> "list[dict]":
    """Rows of docs/QUESTIONS.md still waiting: | id | question | recommendation | asked since | where |.
    A row whose question cell starts with ~~ (struck) or whose last cell says answered is done."""
    try:
        with open(os.path.join(root, QUESTIONS), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        m = _Q_ROW.match(ln.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")] + ["", "", "", ""]
        if cells[0].startswith("~~") or "answered" in " ".join(cells).lower():
            continue
        out.append({"id": m.group(1), "question": cells[0], "recommendation": cells[1],
                    "since": cells[2], "where": cells[3]})
    return sorted(out, key=lambda q: (q["since"] or "9999", q["id"]))


def questions_empty_reason(root: str = ".") -> str:
    """Which empty it is when no question is open (fault hunt 2026-10-14, F001): no file, a file
    that will not read, or a file with nothing open. The three must not print the same nothing."""
    path = os.path.join(root, QUESTIONS)
    if not os.path.exists(path):
        return f"no `{QUESTIONS}` in this repo yet (add a row when a decision only the owner can make comes up)."
    try:
        with open(path, encoding="utf-8") as fh:
            fh.read()
    except (OSError, UnicodeDecodeError) as e:
        return f"could not read `{QUESTIONS}` ({e.__class__.__name__}: {e}); check it before assuming none are open."
    return f"none open in `{QUESTIONS}`."


def start_block(root: str = ".") -> str:
    """What every session asks the owner before work starts: the sprint questions, then up to five
    decisions waiting on her, oldest first. Printed even when there is no handover."""
    qs = open_questions(root)
    lines = ["## Start of session — ask the owner before any work",
             "**Sprint (one line each):** what is the goal today? What check will say it passed? "
             "What is out of scope? (Score each goal PASS / PARTIAL / FAIL at the handover.)"]
    if qs:
        lines.append(f"**Decisions waiting on you** ({len(qs)} open in `{QUESTIONS}`, oldest first; "
                     "ask these as a short decision slot, record each answer in `docs/DECISIONS.md` "
                     "and mark the question answered):")
        for q in qs[:QUESTIONS_SHOWN]:
            rec = f" — recommended: {q['recommendation']}" if q["recommendation"] else ""
            since = f" (asked since {q['since']})" if q["since"] else ""
            lines.append(f"- **{q['id']}** {q['question']}{rec}{since}")
        if len(qs) > QUESTIONS_SHOWN:
            lines.append(f"- … {len(qs) - QUESTIONS_SHOWN} more in `{QUESTIONS}`; "
                         "a decision session every week or two clears the rest.")
    else:
        lines.append(f"**Decisions waiting on you:** {questions_empty_reason(root)}")
    lines.extend(project_lines(root))
    return "\n".join(lines)


# --- the active projects (F26, owner 2026-10-14: "set the scope for different projects and then run
# them through the different systems … a little bit more headless") ----------------------------------

PROJECTS_SHOWN = 3


def _load_pm():
    """The `pm` bundle's reader, from the folder beside this one (.toolbox/pm/ in an app,
    library/pm/ in the toolbox). None when that bundle is not checked out."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "pm", "pm.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("_fleet_pm", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def project_lines(root: str = ".") -> "list[str]":
    """One line per active project in this repo with its next open objective and gate, so the
    sprint goal is picked from a declared project instead of invented. Nothing at all when the repo
    declares no project; a broken file is named, never skipped quietly."""
    if not glob.glob(os.path.join(root, "docs", "projects", "*.md")):
        return []
    pm = _load_pm()
    if pm is None:
        return ["**Projects:** `docs/projects/` has project files, but the `pm` bundle is not "
                "checked out here, so they were not read."]
    found = pm.read_repo(root)
    live = pm.active(found["projects"])
    out = []
    if live:
        out.append("**Active project(s) here** (pick the sprint goal from the next open objective):")
        for p in live[:PROJECTS_SHOWN]:
            nxt = pm.next_open(p)
            step = (f"next {nxt['id']} [{nxt['status']}]: {nxt['objective']} — gate: {nxt['gate']}"
                    if nxt else "every objective PASS; close it (status: done) or add the next one")
            out.append(f"- `{p['id']}` {p['title']} — {step}")
        if len(live) > PROJECTS_SHOWN:
            out.append(f"- … {len(live) - PROJECTS_SHOWN} more: `python .toolbox/pm/pm.py next`")
    if found["unreadable"] and not live:
        out.append("**Project files that could not be read:**")
    for u in found["unreadable"][:PROJECTS_SHOWN]:
        out.append(f"- could not read `{u['file']}`: {u['reason']}")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
