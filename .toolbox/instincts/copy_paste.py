#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""copy_paste — every command a session handed the owner, harvested into ONE file.

Owner 2026-09-13: "add something to the housekeeper — to create a file of any copy-paste code that
was in the session." A session hands the owner commands in chat, and chat is not a file. The
discipline that makes them a file: the handover carries them (its `## Copy-paste` section, fenced
```powershell / ```bash blocks — see HANDOVER_TEMPLATE.md), and this harvester, run by the
housekeeper at session cleanup, lifts every command block out of the newest handover and its
same-day siblings into ONE rolling sheet, **`docs/COPY_PASTE.md`, beside `CIRCLE_BACK.md`** (owner:
"the copy paste should be an md file that lives near the circle back") — the same shape as the
circle-back: a dated `## §` section per session, newest first, a session's section replaced in place
when it is harvested again. Falls back to `<handover stem>_copy_paste.md` beside the handover only
when the repo has no CIRCLE_BACK.md.

Rules (the owner's): a block with an `<angle-bracket>` placeholder is NOT copy-paste and is marked
⚠ (`--check` exits 1 on it); blocks are verbatim, never rewritten; duplicates are folded. Untagged
blocks count only when their first line looks like a command — a table or a JSON sample is not a
command. Stdlib only; honest-empty (no handover, no blocks → says so, exit 0); never breaks a session.

    python .toolbox/instincts/copy_paste.py                # newest handover → docs/COPY_PASTE.md
    python .toolbox/instincts/copy_paste.py --path docs/handover/session_2026-09-13_x.md --print
    python .toolbox/instincts/copy_paste.py --check        # exit 1 if a command carries a <placeholder>
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    # The ONE handover reader's globs + parser + same-day ordering. `_name_sequence` matters as much
    # as the others: it is the half of handover.py's rule that breaks a same-day tie by what the
    # AUTHOR wrote in the filename (a trailing `_2`, a `T14-30`) rather than by a filesystem fact.
    from handover import (_SEARCH as _HANDOVER_GLOBS, _name_sequence,
                          parse_handover)
except Exception:                                          # noqa: BLE001 — standalone copy: local fallbacks
    _HANDOVER_GLOBS = ("docs/handover/*.md", "docs/Claude/handover/*.md", "docs/pipelines/handover/*.md",
                       "docs/handover*.md", "HANDOVER.md", "docs/HANDOVER.md")

    def _name_sequence(path: str) -> tuple:                # noqa: D103 — mirrors handover._name_sequence
        base = os.path.splitext(os.path.basename(path))[0]
        m = re.search(r"\d{4}-\d{2}-\d{2}", base)
        tail = re.sub(r"\d{4}-\d{2}-\d{2}", "", base[m.end():] if m else "")
        return tuple(int(d) for d in re.findall(r"\d+", tail))

    def parse_handover(text: str) -> dict:  # type: ignore[misc]
        return {"roster": [], "leftover": []}

SHELL_LANGS = {"powershell", "ps1", "pwsh", "bash", "sh", "shell", "zsh", "cmd", "bat", "console", "text"}
_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+-]*)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
_CMD_START_RE = re.compile(
    r"^\s*(?:\$env:|\$[A-Za-z_]\w*\s*=|python3?\s|py\s|pip3?\s|git\s|cd\s|ollama\s|docker\s|ssh\s|"
    r"curl\s|make\s|bash\s|pwsh\s|npm\s|node\s|pytest\s|\./|\.\\|Set-[A-Z]|Get-[A-Z]|Invoke-[A-Z]|"
    r"New-[A-Z]|Remove-[A-Z]|\(Get-)")
_PLACEHOLDER_RE = re.compile(r"<(?!!--)[A-Za-z][A-Za-z0-9 _./:\\-]{0,60}>")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
SUFFIX = "_copy_paste.md"
SHEET = "COPY_PASTE.md"
_CIRCLE_BACK = ("docs/CIRCLE_BACK.md", "CIRCLE_BACK.md", "docs/Claude/CIRCLE_BACK.md")
_SECTION_RE = re.compile(r"^## §(?P<stem>[^\s—]+) — .*$", re.M)


def sheet_path(root: str = ".") -> str:
    """docs/COPY_PASTE.md beside the repo's CIRCLE_BACK.md — "" when the repo has none."""
    for rel in _CIRCLE_BACK:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return os.path.join(os.path.dirname(p), SHEET)
    return ""


def extract_blocks(text: str) -> List[Dict[str, Any]]:
    """Every fenced block: {lang, code, line}. Pure."""
    out = []
    for m in _FENCE_RE.finditer(text or ""):
        out.append({"lang": (m.group(1) or "").lower(), "code": m.group(2).rstrip("\n"),
                    "line": text.count("\n", 0, m.start()) + 1})
    return out


def is_command_block(lang: str, code: str) -> bool:
    """A shell-tagged block, or an untagged one whose first non-comment line looks like a command."""
    if not (code or "").strip():
        return False
    if lang in SHELL_LANGS and lang != "text":
        return True
    if lang and lang not in ("text",):
        return False                                       # json / python / yaml … are not commands
    first = next((l for l in code.splitlines() if l.strip() and not l.strip().startswith("#")), "")
    return bool(_CMD_START_RE.match(first))


def placeholders(code: str) -> List[str]:
    return sorted(set(_PLACEHOLDER_RE.findall(code or "")))


# --- a command with nowhere to run it ---------------------------------------------------------
# Same defect as an `<angle-bracket>` placeholder: the block cannot be pasted and run as given.
# A placeholder at least FAILS loudly. A command with no working directory runs happily in
# whatever folder the terminal was already in and answers about the wrong repo — smart_analyst
# paid for this twice on 2026-09-15, both times reading `No module named 'analyst'`.

# Lines that set the working directory for everything after them in the block.
_SETS_CWD_RE = re.compile(r"^\s*(?:cd|pushd|popd|Set-Location|sl|chdir)\s", re.I)
# An explicit directory ON the command itself — then the cwd genuinely does not matter.
_CARRIES_DIR_RE = re.compile(
    r"(?:^|\s)(?:-C|--directory|--cwd|--rootdir|--root|--prefix)[=\s]\S"   # git -C … / make -C …
    r"|(?:^|\s)(?:[/~]|[A-Za-z]:[\\/])"                                    # an absolute path argument
)


def _needs_cwd(line: str) -> bool:
    """True when this command reads the repo out of the CURRENT directory."""
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    if _CARRIES_DIR_RE.search(s):
        return False
    head = s.split()
    cmd = os.path.basename(head[0])
    rest = head[1:]
    if cmd in ("python", "python3", "py"):
        # `python -m pkg…` and `python some/script.py` are both resolved from the cwd;
        # `python -c "…"` and a bare REPL are not.
        return bool(rest) and (rest[0] == "-m" or rest[0].endswith(".py"))
    if cmd in ("pytest", "make", "npm", "npx", "tox", "nox"):
        return True
    if cmd in ("pip", "pip3"):
        return "-r" in rest                       # -r requirements.txt is cwd-relative
    if cmd == "git":
        # `git clone <url>` is the one git command that does not need to be inside a repo.
        return bool(rest) and rest[0] not in ("clone", "--version", "init")
    if cmd in ("bash", "sh", "pwsh", "node") and rest:
        return not rest[0].startswith("-")        # bash scripts/check.sh
    if s.startswith("./") or s.startswith(".\\"):
        return True
    return False


def needs_working_dir(code: str) -> List[str]:
    """The commands in this block that need a working directory the block never sets.

    A `cd` (or `pushd` / `Set-Location`) ANYWHERE in the block counts: the owner pastes the block
    whole, so a `cd` on its first line covers the lines under it. Returns the offending commands,
    honest-empty when the block is fine.
    """
    lines = (code or "").splitlines()
    if any(_SETS_CWD_RE.match(l) for l in lines):
        return []
    return [l.strip() for l in lines if _needs_cwd(l)]


def _name_date(path: str) -> str:
    m = _DATE_RE.search(os.path.basename(path))
    return m.group(1) if m else ""


def _reads_as_handover(path: str) -> bool:
    """Has a Roster line or a Leftover checklist — the two machine-read sections."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            p = parse_handover(fh.read())
        return bool(p.get("roster") or p.get("leftover"))
    except Exception:  # noqa: BLE001
        return False


def find_handover(root: str = ".", path: str = "") -> str:
    """The session's handover, by the SAME rule `handover.py` uses — they must not disagree.

    Newest DATE in the filename, then the author's own counter or time after it (`_2`, `T14-30`),
    then the file that reads as a handover (a Roster line / a Leftover checklist) over a plain
    same-day write-up, then the name, for determinism.

    **`mtime` is deliberately not in that list.** In a fresh clone every handover's mtime is its
    checkout order, so ranking by it silently picks one of two equally-valid files and looks
    decisive doing it — the 2026-09-13 trap, which `handover.py` dropped mtime for and this
    harvester kept until 2026-09-16. Two readers of the same directory answering differently is
    worse than either answer.

    Where the two DO differ, by design: `handover.py` can report a tie and show both, because it
    prints. This writes ONE sheet, so it must choose — the name is the tiebreaker, and every
    same-day sibling is harvested anyway by `sibling_docs`, so nothing is dropped on the floor.

    "" when there is none — never raises. A previous copy-paste sheet is never the handover."""
    if path:
        return path if os.path.isfile(path) else ""
    hits = []
    for pat in _HANDOVER_GLOBS:
        hits.extend(glob.glob(os.path.join(root, pat)))
    hits = [h for h in dict.fromkeys(hits) if os.path.isfile(h) and not h.endswith(SUFFIX)]
    if not hits:
        return ""
    newest = max(_name_date(h) for h in hits)
    day = [h for h in hits if _name_date(h) == newest]
    return sorted(day, key=lambda h: (_name_sequence(h), _reads_as_handover(h), h))[-1]


def sibling_docs(handover: str) -> List[str]:
    """Other .md files in the handover's folder stamped with the same date (a session cleanup
    write-up beside it) — never a previous copy-paste sheet."""
    m = _DATE_RE.search(os.path.basename(handover))
    if not m:
        return []
    date = m.group(1)
    folder = os.path.dirname(handover) or "."
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.md"))):
        if p == handover or p.endswith(SUFFIX) or date not in os.path.basename(p):
            continue
        out.append(p)
    return out


def harvest(root: str = ".", path: str = "") -> Dict[str, Any]:
    """{handover, sources, blocks, out, note}. blocks = [{source, lang, code, line, placeholders}],
    de-duplicated on the code. Honest-empty: no handover → blocks [] + a note; never raises."""
    handover = find_handover(root, path)
    if not handover:
        return {"handover": "", "sources": [], "blocks": [], "out": "",
                "note": f"no handover found under {root} (docs/handover/*.md) — nothing to harvest"}
    sources = [handover] + sibling_docs(handover)
    blocks, seen = [], set()
    for src in sources:
        try:
            with open(src, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for b in extract_blocks(text):
            if not is_command_block(b["lang"], b["code"]):
                continue
            key = re.sub(r"\s+", " ", b["code"]).strip()
            if key in seen:
                continue
            seen.add(key)
            blocks.append({"source": os.path.relpath(src, root), "lang": b["lang"] or "text",
                           "code": b["code"], "line": b["line"], "placeholders": placeholders(b["code"]),
                           "needs_cwd": needs_working_dir(b["code"])})
    stem = os.path.splitext(os.path.basename(handover))[0]
    out = sheet_path(root) or (os.path.splitext(handover)[0] + SUFFIX)
    note = (f"{len(blocks)} command block(s) from {len(sources)} file(s)" if blocks
            else f"no command blocks in {os.path.relpath(handover, root)} — nothing to harvest")
    return {"handover": handover, "stem": stem, "date": _name_date(handover), "sources": sources,
            "blocks": blocks, "out": out if blocks else "", "note": note}


HEADER = """# Copy-paste — the commands each session handed the owner

The paste sheet beside `CIRCLE_BACK.md`: one dated section per session, newest first, every command
verbatim as the session's handover gave it (its `## Copy-paste (owner-side commands)` section + any
same-day write-up). **Generated by the housekeeper's `copy_paste.py` — edit the handover, not this
file**; harvesting the same handover again replaces its section in place. A block marked ⚠ carries an
`<angle-bracket>` placeholder and is not copy-paste until it is filled in; a block marked ⚠ *no
working directory* never says WHERE to run it, which is the same defect running silently — it will
execute in whatever folder the terminal was already in.
"""


def render_section(h: Dict[str, Any], root: str = ".") -> str:
    """ONE session's section — `## §<stem> — <date>` in the circle-back's shape."""
    hv = os.path.relpath(h["handover"], root).replace(os.sep, "/") if h.get("handover") else ""
    L = [f"## §{h.get('stem') or 'session'} — {h.get('date') or 'undated'}", "",
         f"_From `{hv}`" + (f" + {len(h['sources']) - 1} same-day file(s)" if len(h.get("sources") or []) > 1 else "") + "._", ""]
    by_src: Dict[str, List[Dict[str, Any]]] = {}
    for b in h.get("blocks") or []:
        by_src.setdefault(b["source"], []).append(b)
    n = 0
    for src, bs in by_src.items():
        L += [f"## from `{src}`", ""]
        for b in bs:
            n += 1
            warn = ""
            if b["placeholders"]:
                warn += "  ⚠ placeholder: " + ", ".join(f"`{p}`" for p in b["placeholders"])
            if b.get("needs_cwd"):
                warn += "  ⚠ no working directory: " + ", ".join(f"`{c}`" for c in b["needs_cwd"])
            L += [f"**{n}.** line {b['line']}{warn}", "", f"```{b['lang']}", b["code"], "```", ""]
    if not by_src:
        L += ["_(no command blocks)_", ""]
    return "\n".join(L).rstrip("\n") + "\n"


def merge(existing: str, section: str, stem: str) -> str:
    """The rolling sheet: header, then this session's section FIRST, then every other session's
    section as it was — the one for the same stem replaced, not duplicated. Pure."""
    body = existing or ""
    if body.startswith("# "):
        cut = body.find("\n## §")
        body = body[cut + 1:] if cut >= 0 else ""
    parts, pos = [], [m.start() for m in _SECTION_RE.finditer(body)] + [len(body)]
    for a, b in zip(pos, pos[1:]):
        chunk = body[a:b]
        m = _SECTION_RE.match(chunk)
        if m and m.group("stem") != stem:
            parts.append(chunk.rstrip("\n") + "\n")
    return HEADER + "\n" + section + ("\n" + "\n".join(parts) if parts else "")


def render(h: Dict[str, Any], root: str = ".") -> str:
    """The whole sheet as it would be written (existing sections kept) — what --print shows."""
    target = h.get("out") or sheet_path(root)
    existing = ""
    if target and os.path.isfile(target):
        with open(target, encoding="utf-8", errors="replace") as fh:
            existing = fh.read()
    return merge(existing, render_section(h, root), h.get("stem") or "session")


def write(h: Dict[str, Any], root: str = ".", out: str = "") -> str:
    """Write / update the sheet; returns its path or "" when there is nothing to write."""
    target = out or h.get("out") or ""
    if not target or not h.get("blocks"):
        return ""
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    existing = ""
    if os.path.isfile(target):
        with open(target, encoding="utf-8", errors="replace") as fh:
            existing = fh.read()
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(merge(existing, render_section(h, root), h.get("stem") or "session"))
    return target


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="harvest a session's copy-paste commands from its handover into one file")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--path", default="", help="a specific handover file (default: the newest)")
    ap.add_argument("--out", default="", help="where to write (default: docs/COPY_PASTE.md beside CIRCLE_BACK.md, "
                                                   "else <handover stem>_copy_paste.md)")
    ap.add_argument("--print", action="store_true", dest="show", help="print the sheet instead of writing it")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when a command carries an <angle-bracket> placeholder, or never says "
                         "which directory to run it in")
    a = ap.parse_args(argv)
    try:
        h = harvest(a.root, a.path)
        if a.show:
            print(render(h, a.root))
        else:
            path = write(h, a.root, a.out)
            print(f"copy-paste: {h['note']}" + (f" → {os.path.relpath(path, a.root)}" if path else ""))
        bad = [b for b in h["blocks"] if b["placeholders"]]
        rootless = [b for b in h["blocks"] if b.get("needs_cwd")]
        if bad:
            print(f"copy-paste: ⚠ {len(bad)} block(s) carry an <angle-bracket> placeholder — not copy-paste until filled in",
                  file=sys.stderr)
        if rootless:
            print(f"copy-paste: ⚠ {len(rootless)} block(s) never say which directory to run in — "
                  f"add a `cd` so the block can be pasted whole", file=sys.stderr)
            for b in rootless:
                print(f"    {b['source']}:{b['line']}  " + "; ".join(b["needs_cwd"]), file=sys.stderr)
        if (bad or rootless) and a.check:
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001 — the memory layer never breaks a session
        print(f"copy-paste: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
