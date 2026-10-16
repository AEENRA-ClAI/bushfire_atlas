#!/usr/bin/env python3
"""merge_guard — run before every merge into `development`: is this branch about to clobber work it
did not do?

Owner 2026-10-14: "every time a session does that merge, that it checks that it's not clobbering code
it didn't touch". Several sessions run at once on the same repo. A branch that started from an old
`development`, or that copied a stale file over a newer one, can undo another session's work in a
merge that looks clean. It happened on 2026-10-13: a handover commit in the toolbox removed the
`leads` roster, a persona, seven manifests and a test that another session had merged an hour
earlier.

Three checks, against the freshly fetched `origin/development`:

1. **Up to date.** The branch must already contain the latest `origin/development`. If it does not,
   merge it in (`git merge origin/development`), run the tests again, then run this again.
2. **Only files you touched.** Every file the merge would change must have been changed by one of
   this branch's own commits. A file that differs only because of a merge resolution is named.
3. **Nothing newer removed.** For every line the merge would delete or rewrite, `git blame` on
   `origin/development` says who added it. A line added AFTER this branch started (not an ancestor
   of the branch's starting point) is someone else's newer work. Each one is named with the commit
   that added it.

Exit 0: clean. Exit 1: something to look at (named on stdout). Exit 2: could not check (no git,
fetch failed); say so rather than reading it as clean.

    python .toolbox/instincts/merge_guard.py            # fetches origin/development first
    python .toolbox/instincts/merge_guard.py --base main2
    python .toolbox/instincts/merge_guard.py --no-fetch --base-ref development   # tests, offline
    python .toolbox/instincts/merge_guard.py --promote   # before promoting development to main [F25]

`--promote` asks the promotion's question instead: does `main` carry any commit of its own that
`development` lacks? Promotion is a merge of `development` into `main`; a commit made straight on
`main` (a hotfix, a stale push) would be silently kept or fought over. Clean means every non-merge
commit on `main` is already on `development`, so the promotion only adds `development`'s work.

A finding is not automatically wrong: you may mean to rewrite a line another session added. Then
say so in the PR body, line by line. What is never fine is not knowing.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
SHOWN = 20


def _git(root: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def _ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True).returncode == 0


def start_point(root: Path, base_ref: str) -> str | None:
    """The commit this branch started from. None when the branch has no commits of its own.

    The branch's reflog says where it was created, which survives a fast-forward merge of the base
    (the case where the session's own copy is the stale one). Without a reflog (a fresh clone), it
    is the first parent of the branch's oldest first-parent commit that is not on the base."""
    own = _git(root, "rev-list", "--first-parent", f"{base_ref}..HEAD").split()
    if not own:
        return None
    branch = _git(root, "symbolic-ref", "-q", "--short", "HEAD", check=False).strip()
    if branch:
        created = _git(root, "reflog", "show", "--format=%H", branch, "--", check=False).split()
        if created and _ok(root, "merge-base", "--is-ancestor", created[-1], "HEAD"):
            return created[-1]
    parents = _git(root, "rev-list", "--parents", "-n", "1", own[-1]).split()
    return parents[1] if len(parents) > 1 else None


def removed_ranges(root: Path, base_ref: str) -> dict[str, list[tuple[int, int]]]:
    """{path: [(first_line, count), ...]} of lines on the base that merging HEAD would remove."""
    out: dict[str, list[tuple[int, int]]] = {}
    path = None
    for line in _git(root, "diff", "-U0", "--no-color", "--no-renames", base_ref, "HEAD").splitlines():
        if line.startswith("--- "):
            path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith("@@") and path:
            m = _HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
                if count:
                    out.setdefault(path, []).append((start, count))
    return out


def newer_lines(root: Path, base_ref: str, start: str) -> list[str]:
    """Lines the merge would remove that were added after `start`, by a commit HEAD does not own."""
    ancestor: dict[str, bool] = {}
    found = []
    for path, ranges in removed_ranges(root, base_ref).items():
        for first, count in ranges:
            blame = _git(root, "blame", "--porcelain", "-L", f"{first},+{count}", base_ref, "--",
                         path, check=False)
            sha, summary, lineno = None, {}, None
            for b in blame.splitlines():
                head = b.split()
                if len(head) >= 3 and re.fullmatch(r"[0-9a-f]{40}", head[0]):
                    sha, lineno = head[0], head[2]
                elif b.startswith("summary ") and sha:
                    summary[sha] = b[8:]
                elif b.startswith("\t") and sha:
                    if sha not in ancestor:
                        ancestor[sha] = _ok(root, "merge-base", "--is-ancestor", sha, start)
                    if not ancestor[sha]:
                        found.append(f"{path}:{lineno}  added by {sha[:8]} "
                                     f"\"{summary.get(sha, '')[:60]}\"  →  {b[1:].strip()[:70]}")
    return found


def files_not_yours(root: Path, base_ref: str) -> list[str]:
    changed = set(_git(root, "diff", "--name-only", "--no-renames", base_ref, "HEAD").split("\n")) - {""}
    mine = set(_git(root, "log", "--no-merges", "--format=", "--name-only", f"{base_ref}..HEAD")
               .split("\n")) - {""}
    return sorted(changed - mine)


def check(root: Path, base_ref: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    if not _ok(root, "rev-parse", "--verify", "-q", base_ref):
        return 2, [f"could not check: `{base_ref}` is not a ref here (fetch it first)"]
    if not _ok(root, "merge-base", "--is-ancestor", base_ref, "HEAD"):
        behind = len(_git(root, "rev-list", f"HEAD..{base_ref}").split())
        return 1, [f"BEHIND: this branch lacks {behind} commit(s) on {base_ref}. Run "
                   f"`git merge {base_ref}`, run the tests again, then run this again."]
    start = start_point(root, base_ref)
    if start is None:
        return 0, [f"clean: this branch has no commits that are not on {base_ref}; nothing to merge."]
    code = 0
    stray = files_not_yours(root, base_ref)
    if stray:
        code = 1
        lines.append(f"NOT YOURS: {len(stray)} file(s) differ from {base_ref} but no commit on this "
                     "branch changed them (a merge resolution or a stale copy):")
        lines += [f"  - {p}" for p in stray[:SHOWN]] + ([f"  … {len(stray) - SHOWN} more"] if len(stray) > SHOWN else [])
    newer = newer_lines(root, base_ref, start)
    if newer:
        code = 1
        lines.append(f"CLOBBER: {len(newer)} line(s) the merge would remove or rewrite were added on "
                     f"{base_ref} after this branch started ({start[:8]}), by work this branch does not own:")
        lines += [f"  - {n}" for n in newer[:SHOWN]] + ([f"  … {len(newer) - SHOWN} more"] if len(newer) > SHOWN else [])
    if code == 0:
        n = len(_git(root, "diff", "--name-only", base_ref, "HEAD").split())
        lines.append(f"clean: up to date with {base_ref}; {n} file(s) change, all changed by this "
                     "branch; no newer line from another session is removed.")
    else:
        lines.append("If each one is meant, say so line by line in the PR body. If not, restore it from "
                     f"{base_ref} (`git checkout {base_ref} -- <file>`, then redo your change) and run this again.")
    return code, lines


def check_promote(root: Path, dev_ref: str, main_ref: str) -> tuple[int, list[str]]:
    for ref in (dev_ref, main_ref):
        if not _ok(root, "rev-parse", "--verify", "-q", ref):
            return 2, [f"could not check: `{ref}` is not a ref here (fetch it first)"]
    own = _git(root, "log", "--no-merges", "--format=%h %s", f"{dev_ref}..{main_ref}").splitlines()
    if own:
        return 1, [f"STOP: {main_ref} has {len(own)} commit(s) that {dev_ref} does not. Bring them into "
                   f"development first (merge {main_ref} into a branch off {dev_ref}, PR, merge), then promote:"] + \
                  [f"  - {c[:100]}" for c in own[:SHOWN]]
    ahead = len(_git(root, "rev-list", "--no-merges", f"{main_ref}..{dev_ref}").split())
    if not ahead:
        return 0, [f"clean: nothing to promote; {main_ref} already has everything on {dev_ref}."]
    return 0, [f"clean: {main_ref} carries nothing of its own; promoting adds {ahead} commit(s) from {dev_ref}. "
               f"Run the gate on {dev_ref}, then merge {dev_ref} into {main_ref} with a merge commit."]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="before a merge: is this branch up to date, and does it "
                                             "remove anything another session added?")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--base", default="development", help="the branch you merge into (default: development)")
    ap.add_argument("--base-ref", help="compare against this ref as is (skips <remote>/<base>)")
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch the base first")
    ap.add_argument("--promote", action="store_true",
                    help="before promoting: does main carry any commit development lacks?")
    ap.add_argument("--main", default="main", help="the deploy branch, with --promote (default: main)")
    a = ap.parse_args(argv)
    root = Path(a.root)
    base_ref = a.base_ref or f"{a.remote}/{a.base}"
    if a.promote:
        main_ref = a.main if a.base_ref else f"{a.remote}/{a.main}"
        if not a.no_fetch and not a.base_ref:
            r = subprocess.run(["git", "-C", str(root), "fetch", "-q", a.remote, a.base, a.main],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"could not check: fetching failed: {r.stderr.strip()}")
                return 2
        try:
            code, lines = check_promote(root, base_ref, main_ref)
        except (RuntimeError, FileNotFoundError) as e:
            print(f"could not check: {e}")
            return 2
        print(f"## Promotion guard: {base_ref} → {main_ref}")
        print("\n".join(lines))
        return code
    try:
        if not a.no_fetch and not a.base_ref:
            r = subprocess.run(["git", "-C", str(root), "fetch", "-q", a.remote, a.base],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"could not check: fetching {base_ref} failed: {r.stderr.strip()}")
                return 2
        code, lines = check(root, base_ref)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"could not check: {e}")
        return 2
    print(f"## Merge guard against {base_ref}")
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
