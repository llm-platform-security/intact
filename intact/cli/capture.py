"""Capture the full pipeline (CDP + AX + provenance + classification + serialize)
against a real URL — no fixture mocking.

Runs the browser **headful** by default (``--headless`` to change that) with
light bot-mitigation (stealth-leaning launch flag plus a short scroll sequence
that simulates reading) so real sites serve real content instead of
bot-blocked stubs.

Usage:
    python -m intact.cli.capture <url> [wait_seconds] [out_base] [--headless]

Writes to <out_base>/<hostname>/ (out_base defaults to the current directory):
    representation.json   -- canonical machine-readable representation
    ax_tree.json          -- raw AX nodes (debug sidecar)
    provenance.json       -- raw provenance map (debug sidecar)
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from intact.browser.session import BrowserSession
from intact.gentree.serialize import serialize_representation


# Stealth-leaning launch args. The first one removes the
# `navigator.webdriver` flag — the single most common bot-detection
# signal — without disabling automation entirely.
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
]


def simulate_reading(session: BrowserSession, scrolls: int = 5,
                     pause: float = 0.8) -> None:
    """Scroll down a few times after navigation. Many anti-bot heuristics
    flag pages where no user interaction happens within the first few
    seconds; a short scroll sequence is often enough to pass."""
    for i in range(scrolls):
        amount = 600 if i < 3 else 400
        session.scroll(direction="down", amount=amount)
        time.sleep(pause)
    # Scroll back near the top so the capture sees above-the-fold content too.
    try:
        session.page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    time.sleep(0.5)


def main():
    args = sys.argv[1:]
    headless = False
    if "--headless" in args:
        headless = True; args.remove("--headless")
    if not args:
        print("usage: python -m intact.cli.capture <url> [wait_seconds] [out_base] "
              "[--headless]")
        sys.exit(1)

    url = args[0]
    wait = float(args[1]) if len(args) > 1 else 6.0
    out_base = Path(args[2]) if len(args) > 2 else Path.cwd()

    browser_args = list(STEALTH_ARGS)

    session = BrowserSession(headless=headless, browser_args=browser_args)
    try:
        session.navigate(url, wait=wait)
        simulate_reading(session)
        state = session.capture()
        parsed = urlparse(url)
        host = parsed.hostname or "site"
        # Disambiguate by path so internal pages don't clobber the homepage
        # capture for the same host. "/" / "" → just host; otherwise append
        # a slug of the path.
        path = (parsed.path or "").strip("/")
        slug = (host + "_" + path.replace("/", "_"))[:120] if path else host

        out_dir = out_base / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        payload = serialize_representation(state, url=url)
        rep = out_dir / "representation.json"
        rep.write_text(json.dumps(payload, indent=2))
        print(f"wrote {rep}  ({rep.stat().st_size} bytes, "
              f"{payload['element_count']} DOM elements)")

        ax = out_dir / "ax_tree.json"
        ax.write_text(json.dumps(state["ax_nodes"], indent=2))
        print(f"wrote {ax}  ({len(state['ax_nodes'])} AX nodes)")

        prov = out_dir / "provenance.json"
        prov.write_text(json.dumps(state["provenance"], indent=2))
        print(f"wrote {prov}  "
              f"({len(state['provenance'].get('elements', {}))} JS-created elements)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
