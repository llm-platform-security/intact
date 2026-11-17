"""Instrumentation checks beyond the paper's 24 cases: loads, the AX tree,
script requests, origin rebasing, site-isolated frames, and opaque script URLs."""

import pytest

from intact.browser.session import BrowserSession
from intact.gentree.provenance_taint import is_provenance_tainted
from intact.instrumentation import oopif as O
from intact.instrumentation.cdp_provenance import CDPProvenance
from tests import pages as P


@pytest.fixture(scope="module")
def main():
    return P.capture(BrowserSession, P.MAIN, ("#inline-3p-img",))


def test_third_party_src_load(main):
    """An image that an inline script creates with a third-party src records the
    load; load targets name the destination's party, not a script."""
    bni = main["bni"]["#inline-3p-img"]
    assert bni is not None, "inline-3p-img not found in DOM"
    rec = main["provenance"]["elements"].get(bni)
    assert rec is not None, "inline-3p-img not tracked in provenance"
    assert f"src→{P.TP_LOAD}" in rec["loads"], f"loads={rec['loads']}"


def test_tracked_element_in_ax_tree(main):
    """At least some tracked backendNodeIds appear in the AX tree."""
    elements = main["provenance"]["elements"]
    ax_bnis = {n["backendDOMNodeId"] for n in main["ax_nodes"] if n.get("backendDOMNodeId")}
    overlap = set(elements.keys()) & ax_bnis
    assert overlap, (f"no provenance element found in AX tree. "
                     f"provenance has {len(elements)} elements, AX has {len(ax_bnis)} bnis")


def test_no_synthetic_urls_leak_into_network():
    """Requests that fire inside a dynamically inserted inline script, at once
    or in a timer, never carry its raw cdpprov:// synthetic URL as their
    initiator: they are resolved to the script that inserted it."""
    network = P.capture(BrowserSession, P.INSERTED_FETCH)["provenance"]["network"]
    leaks = [r for r in network if (r.get("initiator_script") or "").startswith("cdpprov://")]
    assert not leaks, (f"{len(leaks)} network entries leak raw synthetic URLs as initiators: "
                       f"{[r['initiator_script'] for r in leaks[:3]]}")
    fetches = sorted((r["url"], r["initiator_script"]) for r in network
                     if r["url"].startswith("https://cdn.test/"))
    assert fetches == [("https://cdn.test/async", P.TP + "inserter.js"),
                       ("https://cdn.test/sync", P.TP + "inserter.js")], fetches


def test_script_3p_loads_recorded(main):
    """`scripts` records which third-party domains each script requested."""
    scripts = main["provenance"]["scripts"]
    with_loads = {u: s for u, s in scripts.items() if s.get("3p_loads")}
    assert with_loads, f"no scripts with 3p_loads in scripts={list(scripts.keys())}"
    chain_a = {u: s for u, s in scripts.items() if "chain_a" in u}
    assert chain_a, f"chain_a.js not found in scripts dict; keys={list(scripts.keys())}"
    info = next(iter(chain_a.values()))
    assert info.get("3p_loads"), f"chain_a.js should have 3p_loads; got {info}"
    assert info["cls"].startswith(P.tp("chain_a.js")), \
        f"chain_a.js cls should include full path; got {info['cls']!r}"


def test_rebase_switches_origin_and_drops_now_first_party_requests():
    new = "https://newsite.test/"
    t = CDPProvenance("oldsite.test")
    t._network = [{"url": new + "a.js", "domain": "newsite.test", "initiator_script": ""},
                  {"url": "https://cdn.test/x", "domain": "cdn.test",
                   "initiator_script": new + "a.js"}]
    t._script_3p = {new + "a.js": ["→3p:cdn.test", "→3p:newsite.test"]}
    t.rebase("newsite.test")
    assert t.page_origin == "newsite.test"
    assert [r["domain"] for r in t._network] == ["cdn.test"]
    assert t._script_3p[new + "a.js"] == ["→3p:cdn.test"]


def test_same_site_iframe_stays_in_the_page_capture():
    state = P.capture(BrowserSession, P.ISOLATED_FRAMES)["state"]
    same = P.element_by_id(state, P.SAME_SITE_URL, "insame")
    assert same is not None
    assert same["bni"] < O.NS
    assert all(f["url"] != P.SAME_SITE_URL for f in state["frames"])


def test_actions_reach_elements_inside_an_isolated_iframe():
    with P.open_page(BrowserSession, P.ISOLATED_FRAMES) as session:
        state = session.capture()
        btn = P.element_by_id(state, P.FRAME_URL, "btn")
        assert btn is not None and btn["bni"] >= O.NS
        session.click(btn["bni"])
        frame = next(f for f in session.page.frames if f.url == P.FRAME_URL)
        assert frame.evaluate("document.body.dataset.clicked") == "1"


def test_opaque_script_writes_are_unattributed():
    """Code that runs from an opaque blob: or data: URL has no party of its own,
    even when the blob: URL embeds the first party's origin or the data: script's
    text names a first-party URL: its writes, at once or in a timer callback, are
    unattributed and tainted. The script elements that the third-party script
    inserts stay attributed to it."""
    opaque = ("#from-blob", "#from-blob-timer", "#from-data")
    tags = ("#blob-tag", "#data-tag")
    cap = P.capture(BrowserSession, P.OPAQUE_SCRIPTS, opaque + tags)
    recs = {}
    for sel in opaque + tags:
        assert cap["bni"][sel] is not None, f"{sel} not found in the DOM"
        recs[sel] = cap["provenance"]["elements"].get(cap["bni"][sel])
        assert recs[sel] is not None, f"{sel} not tracked in provenance"
    creators = {sel: rec["creator"] for sel, rec in recs.items()}
    for sel in tags:
        assert creators[sel].startswith(P.tp("opaque.js")), creators
    assert {sel: creators[sel] for sel in opaque} == {sel: "unknown" for sel in opaque}, creators
    for sel in opaque:
        assert is_provenance_tainted(recs[sel], "1p"), f"{sel}: {recs[sel]}"
