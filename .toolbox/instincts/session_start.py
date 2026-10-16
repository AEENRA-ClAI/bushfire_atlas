#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_start — run a repo's own SessionStart hooks by hand.

The 2026-10-13 sprint review found why some sessions "came out of nowhere": a cloud session that
opens on the folder ABOVE the repos (several repos side by side) never runs any repo's
SessionStart hooks. So no dependencies were installed, no instincts were injected, and the last
handover's roster, open items and conversation map were never printed. Seven janet_lite
handovers asked to add a package to a bootstrap hook that already had it; the hook simply never ran.

This reads `<repo>/.claude/settings.json`, takes the SessionStart commands the repo already
declares, and runs each one from inside the repo with the repo's declared `env` applied, printing
what it prints. Nothing is invented: a
repo with no hooks says so.

    python <repo>/.toolbox/instincts/session_start.py --root <repo>
    python toolbox/library/instincts/session_start.py --root toolbox

Stdlib only. Never raises; a hook that fails is named, and the next one still runs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import List


def _settings(root: str) -> dict:
    try:
        with open(os.path.join(root, ".claude", "settings.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def hook_env(root: str) -> dict:
    """The repo's declared `env` block over the current environment. It does not apply either when
    a session opens above the repo (Herdity's HERDITY_PROFILE=claude, found 2026-10-13)."""
    env = dict(os.environ)
    env.update({k: str(v) for k, v in (_settings(root).get("env") or {}).items()})
    return env


def hook_commands(root: str) -> List[str]:
    data = _settings(root)
    out = []
    for group in (data.get("hooks") or {}).get("SessionStart") or []:
        for h in group.get("hooks") or []:
            if h.get("type", "command") == "command" and h.get("command"):
                out.append(h["command"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    cmds = hook_commands(root)
    name = os.path.basename(root)
    if not cmds:
        print(f"[{name}] no SessionStart hooks declared in .claude/settings.json — nothing to run")
        return 0
    failed = 0
    for cmd in cmds:
        print(f"[{name}] $ {cmd}", flush=True)
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, timeout=a.timeout, env=hook_env(root))
            if r.returncode != 0:
                failed += 1
                print(f"[{name}] ✗ exit {r.returncode}: {cmd}")
        except subprocess.TimeoutExpired:
            failed += 1
            print(f"[{name}] ✗ timed out after {a.timeout}s: {cmd}")
    print(f"[{name}] {len(cmds) - failed} of {len(cmds)} start-up hook(s) ran cleanly")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
