"""Capture status: was a capture a usable page, a failed load, or a bot block
or challenge page? The crawler records this per capture (and retries once on
a failed or blocked load) so analyses can exclude pages that are not the site.

A cross-site redirect is flagged but is not a failure: the capture's
provenance is labeled against the site the page actually landed on.
"""

from __future__ import annotations

import re

from intact.etld import etld1

# Titles that bot-management and CDN challenge pages use.
_BLOCK_TITLES = re.compile(
    r"just a moment|attention required|access denied|pardon our interruption|"
    r"are you a (?:robot|human)|security check|ddos-guard|request unsuccessful|"
    r"verif(?:y|ying) you are human|one more step|bot verification|"
    r"please wait\W*\|\s*cloudflare",
    re.I)
# Body text of block pages. Only consulted on small pages, since a real page
# can mention these phrases.
_BLOCK_TEXTS = re.compile(
    r"you have been blocked|access denied|checking your browser|"
    r"verify you are human|enable javascript and cookies to continue|"
    r"why have i been blocked|you don't have permission to access|"
    r"request unsuccessful\. incapsula",
    re.I)
_SMALL_PAGE = 300  # elements; block pages are tiny


def classify_capture(requested_url: str, final_url: str, title: str,
                     texts: list[str], n_elements: int | None = None) -> dict:
    final_url = final_url or ""
    title = (title or "").strip()
    status = "ok"
    if final_url.startswith("chrome-error:") or "chromewebdata" in final_url:
        status = "error"
    elif _BLOCK_TITLES.search(title):
        status = "blocked"
    elif (n_elements is None or n_elements < _SMALL_PAGE) and any(
            _BLOCK_TEXTS.search(t or "") for t in texts[:60]):
        status = "blocked"
    requested_e1 = etld1(requested_url or "")
    final_e1 = etld1(final_url) if final_url.startswith("http") else ""
    return {
        "status": status,
        "requested_url": requested_url,
        "final_url": final_url,
        "title": title[:200],
        "cross_site_redirect": bool(requested_e1 and final_e1
                                    and requested_e1 != final_e1),
    }


def should_retry(info: dict) -> bool:
    return info.get("status") in ("error", "blocked")


def is_block_title(title: str | None) -> bool:
    return bool(_BLOCK_TITLES.search(title or ""))


def info_from_state(state: dict, requested_url: str, final_url: str) -> dict:
    """Status of a capture from its unified elements: the top document's
    <title> and visible text, plus the element count."""
    elements = state.get("elements") or []
    top = [e for e in elements if e.get("doc_index", 0) == 0]
    title = next((e.get("text", "") for e in top if e.get("tag") == "title"), "")
    texts = [e.get("text") for e in top
             if e.get("text") and e.get("tag") not in ("script", "style", "title")]
    return classify_capture(requested_url, final_url, title, texts,
                            n_elements=len(elements))
