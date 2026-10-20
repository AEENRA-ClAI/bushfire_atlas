#!/usr/bin/env python3
"""board_items — keep this repo's cards on Janet's Runs → Board true, at every handover.

Owner 2026-10-19: "build this process into the handover at the end of each session to like update
cards or like move stuff from one spot to another". Each repo keeps its open work in
`docs/board_items.json` ({project, updated, items: [...]}), and Janet reads it from `main`.
data_library also keeps one review per pipeline in `catalog/pipeline_reviews.json`. This script is
the one way a session changes them, so every change stamps the date and leaves a line in the
card's history.

    python .toolbox/instincts/board_items.py check                  # the files read and the forms draw
    python .toolbox/instincts/board_items.py summary                # counts, and what this session moved
    python .toolbox/instincts/board_items.py list --stage decision
    python .toolbox/instincts/board_items.py add kit-guard --title "table_kit: guard a removed box" --who claude --open "fix it in the toolbox"
    python .toolbox/instincts/board_items.py move kit-guard building --note "started on claude/kit-guard"
    python .toolbox/instincts/board_items.py done kit-guard --note "merged #335"
    python .toolbox/instincts/board_items.py review Nasa_Firms --stage-hint blocked --said "key still not filed" --open "file the key"
    python .toolbox/instincts/board_items.py decided kit-guard --said "guard in the kit, not in Janet" --ref D51 --supersedes D40
    python .toolbox/instincts/board_items.py retire old-idea --why "superseded by D51: the kit guards it"
    python .toolbox/instincts/board_items.py add firms --title "File the FIRMS key" --who owner --stage circle_back --command "python -m scripts.run_queue add Nasa_Firms --testing" --where "on the laptop (PowerShell)"

A card's `commands` show on Janet's board with ⧉ Copy, and ▶ Send to Jobs when a Janet recipe
already runs that command. Its `decisions` are the trail of how its direction was decided and
changed (owner 2026-10-19: "any sort of like decision-making process as it changed on the ground …
that should also be something that gets updated in card"); a decision that `--supersedes` an
older one strikes it through. `retire` needs the why, and the Retired column shows it.

Stages are Janet's: to_build exploring building testing data_check producing decision blocked
failing circle_back retired. For a work item, `done` is Producing with a `done` date.
Exit 0 clean, 1 something to fix, 2 could not read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ITEMS = Path("docs/board_items.json")
REVIEWS = Path("catalog/pipeline_reviews.json")
STAGES = ("to_build", "exploring", "building", "testing", "data_check", "producing",
          "decision", "blocked", "failing", "circle_back", "retired")
WHO = ("owner", "claude", "local", "")
KINDS = ("choice", "checkbox", "text")
HISTORY = 10                 # lines kept in a card's history
STALE_DAYS = 30              # an open card nobody has touched for this long is named at the handover


def today() -> str:
    return dt.date.today().isoformat()


def load(path: Path) -> "dict | None":
    """The file's JSON, None when it is not there. ValueError when it will not read."""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def form_problems(d) -> "list[str]":
    """What keeps a decision form from drawing ([] when it draws)."""
    if d is None:
        return []
    if not isinstance(d, dict) or not str(d.get("question") or "").strip():
        return ["a decision with no question"]
    if d.get("kind") not in KINDS:
        return [f"decision kind {d.get('kind')!r} is not one of {', '.join(KINDS)}"]
    out = []
    opts = d.get("options") or []
    ids = [o.get("id") for o in opts if isinstance(o, dict)]
    if d["kind"] == "choice" and len(ids) < 2:
        out.append("a choice needs two answers or more")
    if d["kind"] == "checkbox" and not ids:
        out.append("tick boxes need at least one box")
    if len(ids) != len(set(ids)):
        out.append("two answers share an id")
    for o in opts:
        if isinstance(o, dict) and o.get("then") and o["then"] not in STAGES:
            out.append(f"answer {o.get('id')!r} moves to {o['then']!r}, which is not a stage")
    if d.get("recommend") and d["kind"] != "text" and d["recommend"] not in ids:
        out.append(f"recommend {d['recommend']!r} is not one of the answers")
    return out


def check(root: Path) -> "tuple[int, list[str]]":
    lines, code = [], 0
    try:
        doc = load(root / ITEMS)
    except ValueError as e:
        return 2, [f"{ITEMS} will not read: {e}"]
    if doc is None:
        lines.append(f"{ITEMS}: none yet (`add` makes it)")
    else:
        items = doc.get("items") if isinstance(doc, dict) else None
        if not isinstance(items, list):
            return 2, [f"{ITEMS} has no items list"]
        seen = set()
        for it in items:
            name = key(doc, it)
            probs = []
            if not it.get("id") or not it.get("title"):
                probs.append("needs an id and a title")
            if name in seen:
                probs.append("the id is used twice")
            seen.add(name)
            if it.get("stage", "") not in STAGES + ("",):
                probs.append(f"stage {it.get('stage')!r} is not a stage")
            if it.get("who", "") not in WHO:
                probs.append(f"who {it.get('who')!r} is not owner, claude or local")
            probs += form_problems(it.get("decision"))
            if it.get("stage") == "retired" and not any(it.get(k) for k in ("retired_why", "category", "history", "source")):
                probs.append("retired with no why (retire --why)")
            for d in it.get("decisions") or []:
                if not isinstance(d, dict) or not d.get("said"):
                    probs.append("a decision on its trail says nothing")
            for c in it.get("commands") or []:
                if not (isinstance(c, dict) and str(c.get("text") or "").strip()) and not isinstance(c, str):
                    probs.append("a command with no text")
            if probs:
                code = 1
                lines.append(f"  ✗ {name}: " + "; ".join(probs))
        lines.insert(0, f"{ITEMS}: {len(items)} item(s), {sum(1 for l in lines if '✗' in l)} problem(s)")
    try:
        rv = load(root / REVIEWS)
    except ValueError as e:
        return 2, lines + [f"{REVIEWS} will not read: {e}"]
    if rv is not None:
        bad = [f"  ✗ {n}: " + "; ".join(p) for n, r in (rv.get("pipelines") or {}).items()
               if (p := ([f"stage_hint {r.get('stage_hint')!r} is not decision, blocked or retired"]
                         if r.get("stage_hint") not in ("", None, "decision", "blocked", "retired") else [])
                   + form_problems(r.get("decision")))]
        code = max(code, 1 if bad else 0)
        lines += [f"{REVIEWS}: {len(rv.get('pipelines') or {})} pipeline(s), {len(bad)} problem(s)"] + bad
    return code, lines


def repo_name(root: Path) -> str:
    """The repo's name from git's origin URL; the folder only when there is no origin. A worktree's
    folder is not the repo (featurette_studio 2026-10-19: a new file was named 'fs_board')."""
    import subprocess
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return (name[:-4] if name.endswith(".git") else name) or root.resolve().name


def _doc(root: Path) -> dict:
    """The repo's file; a new one is named after the repo (an item can still name another project)."""
    doc = load(root / ITEMS)
    return doc if doc is not None else {"project": repo_name(root), "updated": today(), "items": []}


def key(doc: dict, it: dict) -> str:
    """The card's name on Janet's board: project:id, the file's project when the item names none."""
    return f"{it.get('project') or doc.get('project')}:{it.get('id')}"


def _find(doc: dict, ident: str) -> dict:
    hits = [i for i in doc["items"] if i.get("id") == ident or key(doc, i) == ident]
    if len(hits) != 1:
        raise SystemExit(f"no card {ident!r}" if not hits else f"{ident!r} names {len(hits)} cards: use project:id")
    return hits[0]


def _stamp(doc: dict, it: dict, stage: str, note: str) -> None:
    it["date"] = today()
    it.setdefault("history", []).append({"date": today(), "stage": stage, "note": note})
    it["history"] = it["history"][-HISTORY:]
    doc["updated"] = today()


def _commands(a) -> "list[dict]":
    return [{"text": t, "where": a.where or ""} for t in (a.command or [])]


def add(root: Path, a) -> str:
    doc = _doc(root)
    proj = a.project or doc["project"]
    if any(key(doc, i) == f"{proj}:{a.id}" for i in doc["items"]):
        raise SystemExit(f"{proj}:{a.id} is on the board already: use move")
    it = {"id": a.id, "project": proj, "title": a.title, "kind": a.kind, "stage": a.stage,
          "who": a.who, "open": list(a.open or []), "owner_action": a.owner_action or "",
          "source": a.source or "", "date": today(), "category": a.category or "",
          "blocker": a.blocker or "", "tags": [a.category] if a.category else [],
          "commands": _commands(a)}
    if a.decision:
        it["decision"] = json.loads(Path(a.decision).read_text(encoding="utf-8"))
    doc["items"].append(it)
    _stamp(doc, it, a.stage, a.note or "added")
    save(root / ITEMS, doc)
    return f"added {proj}:{a.id} in {a.stage}"


def move(root: Path, a, stage: str = "") -> str:
    doc = _doc(root)
    it = _find(doc, a.id)
    stage = stage or a.stage
    was = it.get("stage", "")
    it["stage"] = stage
    note = a.note or ""
    if a.open is not None:
        it["open"] = list(a.open)
    elif stage == "producing" and it.get("open"):
        # A finished card has nothing open (2026-10-20: a done card kept its open steps, so the
        # board showed work left on a Producing card). The history line keeps what was open.
        was_open = "; ".join(str(x) for x in it["open"])
        note = (note + " " if note else "") + f"(was open: {was_open})"
        it["open"] = []
    if getattr(a, "category", None) is not None:
        it["category"] = a.category
        tags = [t for t in it.get("tags") or [] if t]
        if a.category and a.category not in tags:
            it["tags"] = tags + [a.category]
    if getattr(a, "blocker", None) is not None:
        it["blocker"] = a.blocker
    if getattr(a, "owner_action", None) is not None:
        it["owner_action"] = a.owner_action
    if stage == "producing":
        it["done"] = today()
    if stage == "retired":
        if not (a.note or "").strip():
            raise SystemExit("say why it is retired (--why / --note): the Retired column shows it")
        it["retired_why"] = a.note.strip()
    if getattr(a, "command", None):
        have = {c.get("text") for c in it.get("commands") or []}
        it["commands"] = (it.get("commands") or []) + [c for c in _commands(a) if c["text"] not in have]
    _stamp(doc, it, stage, note)
    save(root / ITEMS, doc)
    return f"{key(doc, it)}: {was or 'not judged'} → {stage}"


def decided(root: Path, a) -> str:
    """A decision on the card's trail; one that supersedes an older ref is the direction changing."""
    doc = _doc(root)
    it = _find(doc, a.id)
    entry = {"date": today(), "said": a.said, "ref": a.ref or "", "supersedes": a.supersedes or ""}
    it["decisions"] = [d for d in it.get("decisions") or [] if not (a.ref and d.get("ref") == a.ref)] + [entry]
    _stamp(doc, it, it.get("stage", ""), f"decided: {a.said}" + (f" (replaces {a.supersedes})" if a.supersedes else ""))
    save(root / ITEMS, doc)
    return f"{key(doc, it)}: decided {a.ref or ''} {a.said}".replace("  ", " ")


def review(root: Path, a) -> str:
    doc = load(root / REVIEWS)
    if doc is None:
        raise SystemExit(f"{REVIEWS} is not in this repo: a pipeline review lives in data_library")
    r = doc.setdefault("pipelines", {}).setdefault(a.pipeline, {})
    if a.stage_hint is not None:
        if a.stage_hint not in ("", "decision", "blocked", "retired"):
            raise SystemExit("--stage-hint is decision, blocked, retired or '' (clears it)")
        r["stage_hint"] = a.stage_hint
    for field, val in (("said", a.said), ("owner_action", a.owner_action), ("blocker", a.blocker)):
        if val is not None:
            r[field] = val
    if a.open is not None:
        r["open"] = list(a.open)
    if a.source:
        r["sources"] = [a.source] + [s for s in r.get("sources") or [] if s != a.source][:3]
    r["date"] = today()
    save(root / REVIEWS, doc)
    return f"{a.pipeline}: review updated ({r.get('stage_hint') or 'no stage hint'})"


def summary(root: Path, since: str = "") -> "tuple[int, list[str]]":
    """Counts per stage, the cards moved since `since` (default today), the stale ones."""
    code, lines = check(root)
    doc = load(root / ITEMS) if code < 2 else None
    if not doc:
        return code, lines
    since = since or today()
    items = doc["items"]
    by: "dict[str, int]" = {}
    for it in items:
        by[it.get("stage") or "not judged"] = by.get(it.get("stage") or "not judged", 0) + 1
    lines.append("by stage: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())))
    moved = [(i, h) for i in items for h in i.get("history") or [] if h.get("date", "") >= since]
    lines.append(f"moved since {since}: {len(moved)}" if moved else
                 f"moved since {since}: none — if this session opened, moved or finished work, say it with add / move / done")
    lines += [f"  {key(doc, i)} → {h.get('stage')}" + (f" — {h['note']}" if h.get("note") else "")
              for i, h in moved]
    cut = (dt.date.fromisoformat(since) - dt.timedelta(days=STALE_DAYS)).isoformat() if len(since) == 10 else ""
    stale = [i for i in items if i.get("stage") not in ("producing", "retired") and (i.get("date") or "") < cut]
    if stale:
        lines.append(f"untouched for {STALE_DAYS}+ days ({len(stale)}): still true? "
                     + ", ".join(key(doc, i) for i in stale[:12])
                     + (" …" if len(stale) > 12 else ""))
    return code, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="keep this repo's board cards true")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="the files read, ids are unique, stages are known, forms draw")
    s = sub.add_parser("summary", help="counts, what was moved since a date, what is stale")
    s.add_argument("--since", default="", help="YYYY-MM-DD (default: today)")
    s = sub.add_parser("list", help="the cards, one line each")
    s.add_argument("--stage", default="")
    s.add_argument("--who", default=None)
    s = sub.add_parser("add", help="a new card")
    s.add_argument("id")
    s.add_argument("--title", required=True)
    s.add_argument("--stage", default="to_build", choices=STAGES)
    s.add_argument("--who", default="claude", choices=WHO)
    s.add_argument("--kind", default="task")
    s.add_argument("--project", default="", help="when it is not this repo (e.g. Herdity in the toolbox)")
    s.add_argument("--open", action="append", help="an open step (repeat for several)")
    s.add_argument("--owner-action", default="")
    s.add_argument("--source", default="", help="where it comes from: a handover, CIRCLE_BACK line, PR")
    s.add_argument("--category", default="", help="e.g. needs-credential, purchasing-decision")
    s.add_argument("--blocker", default="")
    s.add_argument("--decision", default="", help="a JSON file holding the decision form")
    s.add_argument("--command", action="append", help="a copy-paste command (repeat for several)")
    s.add_argument("--where", default="", help="where the commands run, e.g. 'on the laptop (PowerShell)'")
    s.add_argument("--note", default="")
    for name, hlp in (("move", "to another stage, either way"), ("done", "finished: Producing, with a done date"),
                      ("retire", "dropped or superseded: Retired, with the why")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("id", help="the id, or project:id")
        if name == "move":
            s.add_argument("stage", choices=STAGES)
        s.add_argument("--open", action="append", help="replaces the open steps (repeat for several)"
                       + ("; without it, done clears them and the history keeps them" if name == "done" else ""))
        s.add_argument("--owner-action", default=None)
        s.add_argument("--category", default=None, help="e.g. needs-credential, purchasing-decision")
        s.add_argument("--blocker", default=None, help="what it waits on (set it when moving to blocked)")
        s.add_argument("--command", action="append", help="add a copy-paste command")
        s.add_argument("--where", default="")
        s.add_argument("--note", "--why", dest="note", default="")
    s = sub.add_parser("decided", help="a decision on the card's trail (a changed one: --supersedes)")
    s.add_argument("id")
    s.add_argument("--said", required=True, help="the decision, in her words where there are some")
    s.add_argument("--ref", default="", help="its DECISIONS.md id, e.g. D51")
    s.add_argument("--supersedes", default="", help="the id of the decision it replaces")
    s = sub.add_parser("review", help="a pipeline's review (data_library's catalog/pipeline_reviews.json)")
    s.add_argument("pipeline")
    s.add_argument("--stage-hint", default=None)
    s.add_argument("--said", default=None)
    s.add_argument("--open", action="append")
    s.add_argument("--owner-action", default=None)
    s.add_argument("--blocker", default=None)
    s.add_argument("--source", default="")
    a = ap.parse_args(argv)
    root = Path(a.root)

    if a.cmd in ("check", "summary"):
        code, lines = check(root) if a.cmd == "check" else summary(root, a.since)
        print("\n".join(lines))
        return code
    if a.cmd == "list":
        doc = load(root / ITEMS) or {"items": []}
        for it in doc["items"]:
            if (not a.stage or it.get("stage") == a.stage) and (a.who is None or it.get("who") == a.who):
                print(f"{it.get('stage') or '-':12} {it.get('who') or '-':7} {key(doc, it)}  {it.get('title')}")
        return 0
    msg = (add(root, a) if a.cmd == "add" else move(root, a) if a.cmd == "move"
           else move(root, a, "producing") if a.cmd == "done" else move(root, a, "retired") if a.cmd == "retire"
           else decided(root, a) if a.cmd == "decided" else review(root, a))
    print(msg)
    code, lines = check(root)
    if code:
        print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
