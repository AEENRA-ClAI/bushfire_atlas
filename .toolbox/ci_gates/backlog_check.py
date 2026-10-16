# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/ci_gates/backlog_check.py
# THE GATE THAT KEEPS A WORKING BACKLOG HONEST — one implementation, checked out to every repo.
#
# WHY THIS EXISTS, and it is not a style rule. Herdity's docs/APP_BACKLOG.md was a SEDIMENT: seven
# sections appended between 2026-07-20 and 2026-07-26, each opening items and each marking earlier
# ones shipped WITHOUT striking the entry it had just closed. MEASURED before the 2026-09-20
# rewrite: 44 open markers and 23 shipped markers across 76 item lines, the same ask up to FOUR
# times, one item listed open AND ✅ at once — which the file itself noticed, in a note nobody
# acted on. The cost was not untidiness: a count taken off that file was inflated roughly
# threefold, so every session re-derived the real state from the code, which is the work the file
# existed to save. Re-triaging a file fixes today. A gate fixes tomorrow.
#
# WHY IT IS HERE AND NOT COPIED PER REPO. Four repos now keep a backlog (Herdity's APP_BACKLOG.md,
# plus docs/BACKLOG.md in data_library, toolbox and janet_lite). Four copies of one rule is the
# duplication this fleet's own "do it once" principle forbids, and they would drift exactly the way
# the lists themselves do. This module is stdlib-only and runner-agnostic — it returns a LIST OF
# PROBLEM STRINGS — so Herdity's unittest and the other three repos' pytest can each wrap it in
# three lines without either runner leaking in here.
#
# WHAT IT DELIBERATELY DOES NOT DO. Nothing here reads English. Every check is over IDs and table
# structure, because a prose duplicate-detector would cry wolf within a week and a guard people
# switch off is worse than no guard (Herdity's standing-check lesson, learned twice). It does not
# police what an item says, how many there should be, or whether one ought to be open — those are
# judgements, and a gate that made them would be wrong about something within a month.
#
#   python backlog_check.py docs/BACKLOG.md --prefix TB        # exit 1 and name each problem
# ============================================================================
"""Check a working backlog says each thing exactly once. Stdlib-only; returns problems, never raises."""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from typing import List, Optional, Sequence, Tuple

OPEN_HEADING = "Open"
CLOSED_PREFIX = "Closed"

#: `**Four items.**` or `**36 items.**` — the count the prose states about its own Open table.
#: Digits are accepted as well as words: a spelled-out count reads better in a sentence and stops
#: being spellable past twenty, and a gate that called `**36 items.**` "unparseable" would push a
#: writer toward deleting the claim rather than stating it — which loses the check entirely.
_COUNT_CLAIM = re.compile(r"^\*\*(\w+) items?\.\*\*", re.M)
_WORDS = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
          "eighteen": 18, "nineteen": 19, "twenty": 20}


def read(path: str) -> str:
    """The file's text, or '' when it is not there — honest-empty; `problems` reports the absence."""
    try:
        with io.open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def tables(text: str) -> List[Tuple[Optional[str], List[str]]]:
    """(nearest preceding `## ` heading, [row cells]) per markdown table row.

    The header row and its `---` separator are skipped; cells come back VERBATIM, because every
    assertion is about ids and emptiness, never about wording.
    """
    out: List[Tuple[Optional[str], List[str]]] = []
    heading: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        if cells[0].lower() in ("id", "#"):
            continue
        out.append((heading, cells))
    return out


def ids(cell: str, prefix: str) -> List[str]:
    """Every `<PREFIX><n>` in a cell, bold or bare."""
    return re.findall(r"\b%s(\d+)\b" % re.escape(prefix), cell)


def _is_open(heading: Optional[str]) -> bool:
    return (heading or "").strip() == OPEN_HEADING


def _is_closed(heading: Optional[str]) -> bool:
    return (heading or "").strip().startswith(CLOSED_PREFIX)


def problems(path: str, prefix: str, *, min_rows: int = 1,
             require_count_claim: bool = True) -> List[str]:
    """Every way this backlog has stopped saying each thing once. Empty list = the file is honest.

    `min_rows` is a ratchet a repo can raise: a guard that silently parses nothing is wallpaper, so
    a file whose table shape changed fails HERE rather than passing everything below vacuously.
    """
    found: List[str] = []
    text = read(path)
    if not text.strip():
        return ["%s is missing or empty — this guard has nothing to guard" % path]

    rows = tables(text)

    # 0. the guard is actually reading the file
    if ("## " + OPEN_HEADING) not in text:
        found.append("no '## %s' section — this guard has stopped guarding" % OPEN_HEADING)
    if len(rows) < min_rows:
        found.append("only %d item row(s) parsed (floor %d) — the table shape changed"
                     % (len(rows), min_rows))

    # 1. every item row carries an id — an id is what makes a duplicate findable
    for heading, cells in rows:
        if not ids(cells[0], prefix):
            found.append("an item with no %s<n> id under %r: %s" % (prefix, heading, cells[0][:60]))

    # 2. no id is used twice
    seen = {}
    for heading, cells in rows:
        for n in ids(cells[0], prefix):
            if n in seen:
                found.append("%s%s appears under both %r and %r — an id is never reused, and an "
                             "ask never appears twice" % (prefix, n, seen[n], heading))
            else:
                seen[n] = heading

    # 3. nothing is open and closed at once — the exact state the sediment was in
    opened, closed = set(), set()
    for heading, cells in rows:
        if _is_open(heading):
            opened.update(ids(cells[0], prefix))
        elif _is_closed(heading):
            closed.update(ids(cells[0], prefix))
    for n in sorted(opened & closed, key=int):
        found.append("%s%s is open and closed at the same time" % (prefix, n))

    # 4. an open item names its SIZE and its EVIDENCE it is still open
    for heading, cells in rows:
        if not _is_open(heading):
            continue
        if len(cells) < 4:
            found.append("%s: an open row needs id | item | size | evidence" % cells[0][:40])
            continue
        if not cells[2]:
            found.append("%s: open with no size" % cells[0][:40])
        if not cells[3]:
            found.append("%s: open with no evidence that it is still open" % cells[0][:40])

    # 5. a closed item says WHAT CLOSED IT — otherwise it is a claim, not a record
    for heading, cells in rows:
        if not _is_closed(heading):
            continue
        if len(cells) < 3:
            found.append("%s: a closed row needs id | item | what closed it" % cells[0][:40])
        elif not cells[-1]:
            found.append("%s: closed with no evidence — that is a claim, not a record" % cells[0][:40])

    # 6. the prose's stated count matches the table it describes
    n_open = len({n for h, c in rows if _is_open(h) for n in ids(c[0], prefix)})
    claims = _COUNT_CLAIM.findall(text)
    if not claims:
        if require_count_claim:
            found.append("the %s section no longer states its own count (expected a line like "
                         "'**%s items.**')" % (OPEN_HEADING, _spell(n_open).capitalize()))
    else:
        for c in claims:
            stated = _WORDS.get(c.lower(), int(c) if c.isdigit() else None)
            if stated is None:
                found.append("unparseable stated count %r" % c)
            elif stated != n_open:
                found.append("the text says %s open items; the table holds %d" % (c, n_open))
    return found


def _spell(n: int) -> str:
    """A count for the suggested wording — spelled out while English has a short word for it."""
    for word, val in _WORDS.items():
        if val == n:
            return word
    return str(n)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", help="the backlog markdown file")
    ap.add_argument("--prefix", required=True, help="the item id prefix, e.g. B / DL / TB / JL")
    ap.add_argument("--min-rows", type=int, default=1)
    ap.add_argument("--no-count-claim", action="store_true",
                    help="do not require the prose to state its own open count")
    args = ap.parse_args(argv)

    found = problems(args.path, args.prefix, min_rows=args.min_rows,
                     require_count_claim=not args.no_count_claim)
    rel = os.path.basename(args.path)
    if not found:
        print("ok    %s says each thing once" % rel)
        return 0
    print("DRIFT %s — %d problem(s):" % (rel, len(found)))
    for f in found:
        print("  - %s" % f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
