"""Load the real page in real Chromium against a constructed green store, and check it.

It writes the SIMULATED fixture (scripts/make_fixture.py) to a temporary data root, starts
`python app.py` on a free port the way Janet does (PORT, HOST, EXTERNAL_DATA_ROOT in the
environment), opens the page, and checks that:
  * the events table fills and the map draws a marker per event;
  * opening the cross-border event lists its source records with their agency ids;
  * the page asks for nothing outside this app (every request is to the app's own origin);
  * the honest-empty sentence shows when no data is mounted.

    python scripts/browser_check.py --out /path/to/screenshot.png
Needs the `playwright` package and a Chromium (CHROMIUM_PATH, default /opt/pw-browsers/...).
"""
from __future__ import annotations

import argparse
import glob
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _chromium() -> str | None:
    if os.environ.get("CHROMIUM_PATH"):
        return os.environ["CHROMIUM_PATH"]
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    return found[-1] if found else None


def _start(data_root: str, port: int) -> subprocess.Popen:
    env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", EXTERNAL_DATA_ROOT=data_root,
               APP_STATE_DIR=os.path.join(data_root, "_state"))
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200:
                    return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise SystemExit("the app did not answer /healthz within 10 s")


def check(out: str | None) -> list:
    from playwright.sync_api import sync_playwright
    from scripts.make_fixture import write_fixture

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        write_fixture(tmp)
        port, empty_port = _free_port(), _free_port()
        app = _start(tmp, port)
        empty = _start(os.path.join(tmp, "not-mounted"), empty_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=_chromium())
                page = browser.new_page(viewport={"width": 1400, "height": 1000})
                foreign = []
                origin = f"http://127.0.0.1:{port}"
                page.on("request", lambda r: foreign.append(r.url)
                        if not r.url.startswith(origin) and not r.url.startswith("data:") else None)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(origin + "/")
                page.wait_for_selector("#events tbody tr", timeout=10_000)
                rows = page.locator("#events tbody tr").count()
                markers = page.locator(".leaflet-interactive").count()
                if rows != 3:
                    failures.append(f"expected 3 event rows, saw {rows}")
                if markers < 3:
                    failures.append(f"expected a marker per event, saw {markers}")
                page.locator("#events tbody tr", has_text="cross-border").first.click()
                page.wait_for_selector("#members tbody tr", timeout=10_000)
                # the table kit puts its own tick-box cell (data-tk-own) first in every row, so
                # count the page's own cells: the third is the agency id
                ids = page.locator("#members tbody tr").evaluate_all(
                    "rows => rows.map(r => { var c = Array.from(r.cells).filter("
                    "x => !x.hasAttribute('data-tk-own')); return c[2] ? c[2].textContent : ''; })")
                if not {"QFD-0001", "NSW-77"} <= set(ids):
                    failures.append(f"detail is missing agency ids: {ids}")
                page.wait_for_timeout(600)
                if out:
                    page.screenshot(path=out, full_page=True)
                if foreign:
                    failures.append(f"requests outside the app: {foreign}")
                if errors:
                    failures.append(f"page errors: {errors}")
                page.goto(f"http://127.0.0.1:{empty_port}/")
                page.wait_for_function(
                    "document.getElementById('state').textContent.indexOf('No data mounted') === 0",
                    timeout=10_000)
                browser.close()
        finally:
            for p in (app, empty):
                p.terminate()
                p.wait(timeout=10)
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the page in real Chromium (SIMULATED data).")
    ap.add_argument("--out", default=None, help="where to save a full-page screenshot (PNG)")
    args = ap.parse_args()
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP: playwright is not installed (pip install playwright)")
        return 0
    if not _chromium():
        print("SKIP: no Chromium found (set CHROMIUM_PATH)")
        return 0
    failures = check(args.out)
    for f in failures:
        print("FAIL:", f)
    print("browser check:", "FAILED" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
