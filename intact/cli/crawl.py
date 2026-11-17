"""Crawl multiple URLs in a single browser session.

Same pipeline as `intact.cli.capture` (CDP + AX + provenance + classification
+ serialize), but reuses one BrowserSession across N URLs so the browser
doesn't restart between captures. The browser is headful unless --headless
is given.

Usage:
    python -m intact.cli.crawl <out_base> <url1> [<url2> ...] [--headless]
    python -m intact.cli.crawl <out_base> --url-file urls.txt [<url> ...]
        [--resume] [--skip-file FILE] [--headless]

URLs may be given positionally and/or via --url-file (one URL per line, blank
lines and '#' comments ignored).

Writes each capture to <out_base>/<slug>/ where the slug is hostname plus
a path-derived suffix so internal pages don't clobber homepage captures
for the same host.
"""

import json
import os
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import urlparse

# NOTE: BrowserSession / capture / serialize are imported lazily inside the
# functions that use them (they pull in Playwright). Keeping the module top-level
# import-cheap lets helpers like read_url_file be imported and unit-tested
# without spinning up the browser stack.


def read_url_file(path) -> list[str]:
    """Read URLs from a file, one per line; blank lines and '#' comments skipped."""
    out = []
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


# A page that takes longer than this (navigation + reading + capture) is
# treated as hung: it is added to the skip file and the process exits with
# WATCHDOG_EXIT so the supervisor loop restarts the shard with --resume.
# Observed pages take 18 s at the median and at most ~170 s.
PAGE_TIMEOUT = 300.0
WATCHDOG_EXIT = 3


class PageWatchdog:
    """Calls ``on_timeout(url)`` unless the current page finishes in time."""

    def __init__(self, timeout: float, on_timeout):
        self.timeout = timeout
        self.on_timeout = on_timeout
        self._timer = None

    def start(self, url: str) -> None:
        self.stop()
        self._timer = threading.Timer(self.timeout, self.on_timeout, args=(url,))
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def make_timeout_handler(skip_path, exit_fn=os._exit):
    """Record the hung URL in the skip file, then exit for a restart."""
    def handler(url: str) -> None:
        print(f"\n  WATCHDOG: {url} exceeded {PAGE_TIMEOUT:.0f}s; "
              f"recording it as skipped and restarting", flush=True)
        with open(skip_path, "a") as f:
            f.write(url + "\n")
        exit_fn(WATCHDOG_EXIT)
    return handler


def read_skip_file(path) -> set[str]:
    p = Path(path)
    return set(read_url_file(p)) if p.exists() else set()


# Longer settle for the single retry of a failed load or a bot challenge;
# challenge pages often clear after a few seconds in a real browser.
RETRY_WAIT = 20.0


def _slug(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "site"
    path = (p.path or "").strip("/")
    return (host + "_" + path.replace("/", "_"))[:120] if path else host


def _write_outputs(state: dict, out_base: Path, url: str) -> tuple[Path, int, int]:
    out_dir = out_base / _slug(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    from intact.gentree.serialize import serialize_representation

    payload = serialize_representation(state, url=url)
    rep = out_dir / "representation.json"
    rep.write_text(json.dumps(payload, indent=2))

    ax = out_dir / "ax_tree.json"
    ax.write_text(json.dumps(state["ax_nodes"], indent=2))

    prov = out_dir / "provenance.json"
    prov.write_text(json.dumps(state["provenance"], indent=2))

    return rep, payload["element_count"], rep.stat().st_size


def main():
    args = sys.argv[1:]
    url_file = None
    resume = False
    if "--resume" in args:
        resume = True; args.remove("--resume")
    headless = False
    if "--headless" in args:
        headless = True; args.remove("--headless")
    if "--url-file" in args:
        i = args.index("--url-file"); url_file = args[i + 1]; del args[i:i + 2]
    skip_file = None
    if "--skip-file" in args:
        i = args.index("--skip-file"); skip_file = args[i + 1]; del args[i:i + 2]

    if not args:
        print("usage: python -m intact.cli.crawl <out_base> [<url> ...] "
              "[--url-file FILE] [--resume] [--skip-file FILE] [--headless]")
        sys.exit(1)

    out_base = Path(args[0])
    urls = args[1:]
    if url_file:
        urls += read_url_file(url_file)
    if not urls:
        print("no URLs given (pass them positionally and/or via --url-file).")
        sys.exit(1)
    wait = 8.0

    out_base.mkdir(parents=True, exist_ok=True)

    from intact.browser.session import BrowserSession
    from intact.cli.status import info_from_state, should_retry
    from intact.cli.capture import STEALTH_ARGS, simulate_reading

    session = BrowserSession(headless=headless, browser_args=STEALTH_ARGS)
    skip = read_skip_file(skip_file) if skip_file else set()
    watchdog = (PageWatchdog(PAGE_TIMEOUT, make_timeout_handler(skip_file))
                if skip_file else None)
    failures: list[tuple[str, str]] = []
    skipped = 0
    try:
        for i, url in enumerate(urls, 1):
            if resume and (out_base / _slug(url) / "representation.json").exists():
                skipped += 1
                continue
            if url in skip:
                print(f"\n=== [{i}/{len(urls)}] {url} === skipped "
                      f"(hung past the watchdog timeout earlier)")
                failures.append((url, "skipped: watchdog timeout"))
                continue
            print(f"\n=== [{i}/{len(urls)}] {url} ===")
            if watchdog:
                watchdog.start(url)
            try:
                session.navigate(url, wait=wait)
                simulate_reading(session)
                state = session.capture()
                info = info_from_state(state, url, session.page.url)
                attempts = 1
                if should_retry(info):
                    print(f"  {info['status']} ({info['title'][:60]!r}); "
                          f"retrying once with a {RETRY_WAIT:.0f}s wait")
                    session.navigate(url, wait=RETRY_WAIT)
                    simulate_reading(session)
                    state = session.capture()
                    info = info_from_state(state, url, session.page.url)
                    attempts = 2
                info["attempts"] = attempts
                state["capture"] = info
                rep, n, sz = _write_outputs(state, out_base, url)
                redirect = ", cross-site redirect" if info["cross_site_redirect"] else ""
                print(f"  wrote {rep}  ({sz:,} bytes, {n} elements, "
                      f"status={info['status']}{redirect})")
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                print(f"  ERROR: {msg}")
                traceback.print_exc(limit=2)
                failures.append((url, msg))
            finally:
                if watchdog:
                    watchdog.stop()
    finally:
        session.close()

    attempted = len(urls) - skipped
    print(f"\n=== done — {attempted - len(failures)}/{attempted} captured "
          f"({skipped} skipped as already done) ===")
    if failures:
        print("Failures:")
        for url, msg in failures:
            print(f"  {url}  →  {msg}")


if __name__ == "__main__":
    main()
