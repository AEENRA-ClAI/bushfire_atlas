# -*- coding: utf-8 -*-
# ============================================================================
# toolbox — library/checkout_verify/verify_checkout.py
#
# VERIFY A CHECKOUT AGAINST ITS OWN COMMITTED LOCK — the drift gate that runs with no toolbox.
#
# Why this exists, and why it is not `checkout.py --check` (owner 2026-09-15):
#
#   `scripts/checkout.py --app X --check` compares the toolbox SOURCE against the app's checked-out
#   copy. It is the stronger gate and it stays the canonical one — but it needs BOTH repos side by
#   side, and every repo in this fleet is PRIVATE, so a GitHub Actions job in the consumer cannot
#   clone the toolbox without a cross-repo token. Writing a workflow against a secret nobody has
#   configured gives you a job that is red on its first run and ignored by its second.
#
#   So this asks the question a consumer CAN answer on its own: **has anyone edited a checked-out
#   file in place since the checkout that wrote the lock?** That is not a lesser question — it is
#   the exact failure this gate was written for. On 2026-09-15 the "Defaults baked in" section had
#   been added by hand to data_library's checked-out copy of HANDOVER_TEMPLATE.md; the next
#   `checkout.py --app data_library` overwrote the file and the section was GONE. It was recovered
#   from git and promoted into the toolbox, but nothing would have caught it, and nothing would
#   catch the next one. A local edit to a checked-out file is a pending deletion. This names it
#   BEFORE the checkout, which is the only moment at which naming it is useful.
#
#   What it deliberately does NOT catch: a STALE checkout (the toolbox source moved on and this
#   copy has not been refreshed). That needs the toolbox present, so it stays `--check`'s job. A
#   stale checkout is also not destructive — refreshing it is the normal, lossless act.
#
# The lock covers the verifier itself, so editing this file to hide drift reports this file.
#
#   python .toolbox/checkout_verify/verify_checkout.py          # from the consumer repo root
#   python .toolbox/checkout_verify/verify_checkout.py --root . # explicit root
#
# Exit 0 = in sync (or honestly: nothing checked out here). Exit 1 = drift, each file named.
# ============================================================================
"""verify_checkout — is every checked-out file still the bytes its committed lock records?"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

# Never reported as an extra: build artefacts and the lock itself are not checked-out content.
_IGNORED = {"__pycache__", ".checkout.lock.json", "checkout.lock.json", "README.md"}


def _sha256(path: str) -> str:
    """The file's hash with line endings NORMALISED for text (CRLF -> LF), raw for binary.

    A checkout on Windows (git core.autocrlf) hands out CRLF files, so a raw-byte hash of the
    same content differs by platform: every entry in a lock written there changed, the lock
    was dirty after every Windows checkout, and it got swept into commits (owner 2026-09-28).
    A file holding a NUL byte is binary and hashed as it is."""
    with open(path, "rb") as fh:
        data = fh.read()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _check_files(base: str, entries: List[Dict[str, str]], label: str) -> List[str]:
    """Compare each locked {file, sha256} under `base`. Returns one problem line per bad file.

    MISSING and CHANGED are reported separately because they mean different things to the person
    reading the failure: MISSING is usually a deleted or moved file, CHANGED is an edit in place.
    """
    problems: List[str] = []
    for ent in entries or []:
        rel = ent.get("file")
        want = ent.get("sha256")
        if not rel or not want:
            continue
        path = os.path.join(base, rel)
        if not os.path.isfile(path):
            problems.append(f"MISSING  {label}/{rel}")
            continue
        got = _sha256(path)
        if got != want:
            problems.append(f"CHANGED  {label}/{rel}  (locked {want[:12]}…, on disk {got[:12]}…)")
    return problems


def _extra_agents(agents_dir: str, locked: List[Dict[str, str]]) -> List[str]:
    """A `.md` in `.claude/agents/` that the lock does not name.

    This is drift and it is DESTRUCTIVE drift, because the agent checkout PRUNES: an unlisted `.md`
    is deleted by the next checkout. (Skills are deliberately NOT swept this way — that prune is
    conservative by design, a hand-written skill beside the checked-out ones is legitimate, so an
    unlisted skill dir is not reported here.)
    """
    if not os.path.isdir(agents_dir):
        return []
    known = {e.get("file") for e in locked or []}
    extras = []
    for name in sorted(os.listdir(agents_dir)):
        if name in _IGNORED or not name.endswith(".md"):
            continue
        if name not in known:
            extras.append(f"EXTRA    .claude/agents/{name}  (unlocked — the next checkout DELETES it)")
    return extras


def verify(root: str = ".") -> Tuple[List[str], List[str]]:
    """Verify every checkout lock under `root`. Returns (problems, checked_labels).

    An absent lock is not a failure: a repo that subscribes to no bundles has no `.toolbox`, and a
    lean clone may have neither. `checked` says what was actually looked at, so a caller can tell
    "in sync" from "there was nothing here" — the two are not the same claim.
    """
    problems: List[str] = []
    checked: List[str] = []

    bundles_lock = _read_json(os.path.join(root, ".toolbox", "checkout.lock.json"))
    if isinstance(bundles_lock, dict):
        for name, meta in (bundles_lock.get("bundles") or {}).items():
            # a bundle placed elsewhere by the manifest's bundle_dirs records its `path`
            placed = (meta or {}).get("path")
            rel = placed if placed else f".toolbox/{name}"
            base = os.path.join(root, *rel.split("/"))
            problems += _check_files(base, (meta or {}).get("files") or [], rel)
            checked.append(rel)

    agents_dir = os.path.join(root, ".claude", "agents")
    agents_lock = _read_json(os.path.join(agents_dir, ".checkout.lock.json"))
    if isinstance(agents_lock, dict):
        files = ((agents_lock.get("agents") or {}).get("files")) or []
        problems += _check_files(agents_dir, files, ".claude/agents")
        problems += _extra_agents(agents_dir, files)
        checked.append(".claude/agents")

    skills_dir = os.path.join(root, ".claude", "skills")
    skills_lock = _read_json(os.path.join(skills_dir, ".checkout.lock.json"))
    if isinstance(skills_lock, dict):
        for name, entries in ((skills_lock.get("skills") or {}).get("skills") or {}).items():
            problems += _check_files(os.path.join(skills_dir, name), entries, f".claude/skills/{name}")
            checked.append(f".claude/skills/{name}")

    return problems, checked


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Verify checked-out toolbox files against their committed lock.")
    ap.add_argument("--root", default=".", help="the consumer repo root (default: the current directory)")
    args = ap.parse_args(argv)

    problems, checked = verify(args.root)
    if not checked:
        # Honest-empty, and it says so rather than printing a green tick it has not earned.
        print("verify_checkout: no checkout lock found — nothing to verify here.")
        return 0
    if problems:
        print(f"verify_checkout: DRIFT in {len(problems)} file(s) across {len(checked)} checked-out group(s).")
        for line in problems:
            print("  " + line)
        print("\nThese files are checked out from the toolbox and the next checkout OVERWRITES them.")
        print("Fix by editing the canonical copy in the toolbox (library/…) and re-running:")
        print("  python ../toolbox/scripts/checkout.py --app <this app>")
        return 1
    print(f"verify_checkout: in sync — {len(checked)} checked-out group(s) match their lock.")
    for label in checked:
        print("  ok  " + label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
