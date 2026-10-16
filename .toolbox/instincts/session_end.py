#!/usr/bin/env python3
"""session_end — the one command behind the owner's one word.

Owner 2026-10-14: "simplify the end of the session to include the session cleanup, the housekeeper,
the handover documents, and everything else, so I just have to say one thing once." When she says
"handover" (or "cleanup", "wrap up", "end the session"), Claude runs this, then does what it prints,
without asking.

It does the mechanical steps itself and reports each one:

1. the merge guard against the base (is the branch up to date, and does it clobber anything?);
2. the full suite, read from the "Full suite" line of the repo's CLAUDE.md;
3. the records: `doc_records.py all`, then `copy_paste.py`;
4. git state: uncommitted files, unpushed commits.

Then it prints the steps only Claude can do (score the sprint, the fault hunt, write the handover,
merge, re-check the remote), with the template's path. Nothing is skipped silently: a step that could
not run says why.

    python .toolbox/instincts/session_end.py              # everything
    python .toolbox/instincts/session_end.py --no-suite   # when the suite already ran this hour
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_SUITE = re.compile(r"\*\*Full suite[^*]*\*\*[^`]*`([^`]+)`", re.S)


def suite_command(root: Path) -> str | None:
    """The first command quoted on the CLAUDE.md line that starts **Full suite."""
    md = root / "CLAUDE.md"
    if not md.is_file():
        return None
    m = _SUITE.search(md.read_text(encoding="utf-8", errors="replace"))
    return m.group(1).strip() if m else None


def _run(cmd, root: Path, tail: int = 6, shell: bool = False) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, shell=shell)
    except FileNotFoundError as e:
        return 127, str(e)
    out = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode, "\n".join(out[-tail:])


def _py(script: str, root: Path, *args: str, tail: int = 6) -> tuple[int, str]:
    return _run([sys.executable, str(HERE / script), *args], root, tail)


def report(title: str, code: int, text: str) -> None:
    mark = "ok" if code == 0 else ("COULD NOT RUN" if code in (2, 127) else "LOOK")
    print(f"\n### {title} — {mark} (exit {code})")
    if text:
        print("\n".join("    " + line for line in text.splitlines()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="the end of a session in one command")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--base", default="development", help="the branch work merges into")
    ap.add_argument("--no-suite", action="store_true", help="skip the full suite")
    ap.add_argument("--no-fetch", action="store_true", help="merge guard without fetching")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    worst = 0
    print(f"## End of session — {root.name}")

    guard = ["--root", str(root), "--base", a.base] + (["--no-fetch"] if a.no_fetch else [])
    code, text = _py("merge_guard.py", root, *guard, tail=40)
    report("1. Merge guard", code, text)
    worst = max(worst, code)

    if a.no_suite:
        report("2. Full suite", 0, "skipped (--no-suite): say in the handover when it last ran")
    else:
        cmd = suite_command(root)
        if not cmd:
            report("2. Full suite", 2, "no **Full suite** line with a command in CLAUDE.md; run it by hand")
            worst = max(worst, 2)
        else:
            code, text = _run(cmd.replace("python ", f"{sys.executable} ", 1), root, tail=12, shell=True)
            report(f"2. Full suite: `{cmd}`", code, text)
            worst = max(worst, 1 if code else 0)

    code, text = _py("doc_records.py", root, "all", "--root", str(root))
    report("3a. Records (decisions, counts, unverified, threads)", code, text)
    worst = max(worst, 1 if code else 0)
    code, text = _py("copy_paste.py", root, "--root", str(root))
    report("3b. Copy-paste sheet", code, text)
    worst = max(worst, 1 if code else 0)

    dirty = subprocess.run(["git", "-C", str(root), "status", "--short"], capture_output=True, text=True).stdout
    ahead = subprocess.run(["git", "-C", str(root), "log", "--oneline", "@{u}..HEAD"],
                           capture_output=True, text=True)
    state = []
    state.append(f"{len(dirty.splitlines())} uncommitted file(s)" if dirty.strip() else "nothing uncommitted")
    state.append("no upstream branch yet: push with -u" if ahead.returncode else
                 (f"{len(ahead.stdout.splitlines())} commit(s) not pushed" if ahead.stdout.strip() else "everything pushed"))
    report("4. Git state", 0, "; ".join(state))

    template = next((p for p in (root / ".toolbox/instincts/HANDOVER_TEMPLATE.md",
                                 root / "library/instincts/HANDOVER_TEMPLATE.md") if p.is_file()), None)
    print(f"""
### Now do these, without asking
5. **Score the sprint**: each objective PASS / PARTIAL / FAIL against its gate, with evidence; a
   three-line retro.
6. **Fault hunt**: run the `fault-hunter` agent on the repo; paste what it scanned and found.
7. **Write the handover** from `{template.relative_to(root) if template else 'HANDOVER_TEMPLATE.md'}`
   into `docs/handover/`, with step 2's counts and every failure marked CAUSED-HERE, PRE-EXISTING or
   ENVIRONMENT. Then run step 3 again so the records pick it up.
8. **Commit, push, merge** into `{a.base}`: run the merge guard again just before the merge.
9. **Promote** `{a.base}` to `main` once, if the gate is green: `merge_guard.py --promote` must say
   clean, then a PR `{a.base}` → `main` merged with a merge commit [F25].
10. **Re-check every state claim against the remote**, last.
Stop and ask only for anything destructive, or a decision that is hers.""")
    return worst


if __name__ == "__main__":
    sys.exit(main())
