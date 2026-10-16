"""The local gate (the fleet has no GitHub Actions, F7). Run it at the start and the end of a
session:

    python scripts/gate.py            compile, tests, browser check, kit drift
    python scripts/gate.py --quick    compile and tests only

Each step prints ok / FAIL / SKIP (with why); the exit code is 1 when any step failed.
"""
from __future__ import annotations

import argparse
import compileall
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(label: str, cmd: list) -> str:
    print(f"== {label}: {' '.join(cmd)}", flush=True)
    rc = subprocess.call(cmd, cwd=ROOT)
    return "ok" if rc == 0 else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser(description="bushfire_atlas local gate")
    ap.add_argument("--quick", action="store_true", help="compile and tests only")
    args = ap.parse_args()
    results = {}
    print("== compile", flush=True)
    results["compile"] = "ok" if compileall.compile_dir(
        ROOT, quiet=1, rx=__import__("re").compile(r"[\\/](\.git|\.venv|static)[\\/]")) else "FAIL"
    results["tests"] = _run("tests", [sys.executable, "-m", "pytest", "-q"])
    if not args.quick:
        results["browser"] = _run("browser check", [sys.executable, "scripts/browser_check.py"])
        toolbox = os.path.join(os.path.dirname(ROOT), "toolbox", "scripts", "checkout.py")
        if os.path.isfile(toolbox):
            results["kit drift"] = _run("kit drift", [sys.executable, toolbox, "--app",
                                                      "bushfire_atlas", "--check"])
        else:
            print("== kit drift: SKIP (no toolbox checkout beside this repo; "
                  "tests/test_vendored_and_config.py still checks the lock)")
            results["kit drift"] = "SKIP"
    print("\n".join(f"{k:10} {v}" for k, v in results.items()))
    return 1 if "FAIL" in results.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
