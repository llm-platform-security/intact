"""The paper's 24 attribution cases (Appendix C), one test per case.

Each test's docstring states its case and the expected attribution. The pages
are in tests/pages.py, served by Playwright request routing: the first party is
firstparty.test, third parties are thirdparty.test and other .test hosts.

    pytest tests/test_attribution_cases.py    # 24 passed, 1 xfailed

The expected failure is a gap that the paper states: content created inside a
shadow root is not collected.
"""

import re

import pytest

from intact.browser.session import BrowserSession
from tests import pages as P

HASHED = re.compile(r"#[0-9a-f]{8}$")  # first 8 hex digits of the content hash


MAIN_SELECTORS = (
    "#static-btn", "#static-link", "#static-input", "#inline-created-btn",
    "#innerHTML-link", "#adj-span", "#fp-div", "#tp-btn", "#listener-btn",
    "#attr-mod-div", "#chain-a-script-tag", "#chain-a-div", "#chain-b-script-tag",
    "#chain-a-img", "#chain-b-span", "#chain-b-inline-img", "#chain-b-async-inline-img",
)


@pytest.fixture(scope="module")
def main():
    """One capture of the main page, shared by the cases that use it."""
    return P.capture(BrowserSession, P.MAIN, MAIN_SELECTORS)


def record(cap, selector):
    """Provenance record of the element matching `selector` (None if untracked)."""
    bni = cap["bni"][selector]
    assert bni is not None, f"{selector} not found in the DOM"
    return cap["provenance"]["elements"].get(bni)


def tracked(page, selectors):
    """Capture `page`; {selector: provenance record or None}."""
    cap = P.capture(BrowserSession, page, selectors)
    return {sel: cap["provenance"]["elements"].get(cap["bni"][sel]) for sel in selectors}


# --- Creation and insertion ---------------------------------------------------

def test_01_parser_created_element_has_no_record(main):
    """The HTML parser creates an element. Expected: no record (parser)."""
    elements = main["provenance"]["elements"]
    for sel in ("#static-btn", "#static-link", "#static-input"):
        bni = main["bni"][sel]
        assert bni is not None, f"DOM element {sel} not found"
        assert bni not in elements, f"{sel} (bni={bni}) should NOT be in provenance"


def test_02_first_party_inline_script_creates_element(main):
    """A first-party inline script creates an element. Expected: first party
    (inline)."""
    rec = record(main, "#inline-created-btn")
    assert rec is not None, "inline-created-btn not tracked in provenance"
    assert rec["creator"] == "1p:inline", f"got creator={rec['creator']!r}"
    assert rec["via"] == "createElement"
    rec = tracked(P.INLINE_CREATE, ["#made-by-1p"])["#made-by-1p"]
    assert rec is not None, "element not tracked"
    assert rec["creator"] == "1p:inline", rec


def test_03_first_party_external_script_creates_element(main):
    """A first-party external script creates an element. Expected: first party
    (script file)."""
    rec = record(main, "#fp-div")
    assert rec is not None, "fp-div not tracked in provenance"
    assert rec["creator"] == "1p:first_party.js", f"got creator={rec['creator']!r}"
    assert rec["via"] == "createElement"


def test_04_third_party_script_creates_element(main):
    """A third-party script creates an element. Expected: third party, with path
    and hash."""
    rec = record(main, "#tp-btn")
    assert rec is not None, "tp-btn not tracked in provenance"
    assert rec["creator"].startswith(P.tp("third_party.js")), f"got creator={rec['creator']!r}"
    assert HASHED.search(rec["creator"]), f"no content hash in {rec['creator']!r}"
    rec = record(main, "#chain-a-div")
    assert rec is not None, "chain-a-div not tracked"
    assert rec["creator"].startswith(P.tp("chain_a.js")), f"got creator={rec['creator']!r}"
    assert rec["via"] == "createElement"
    rec = tracked(P.TP_CREATE, ["#made-by-3p"])["#made-by-3p"]
    assert rec is not None, "element not tracked"
    assert rec["creator"].startswith("3p:thirdparty.test/maker.js"), rec


def test_05_third_party_script_clones_first_party_template():
    """A third-party script clones a first-party template and inserts the clone.
    Expected: not first party."""
    rec = tracked(P.CLONE, ["#cloned"])["#cloned"]
    assert rec is not None, "cloned node not tracked"
    assert not rec["creator"].startswith("1p:"), f"clone labeled 1p: {rec}"


def test_06_third_party_script_builds_subtree_with_domparser():
    """A third-party script builds a subtree with DOMParser. Expected: not first
    party, for every element."""
    recs = tracked(P.DOMPARSER, ["#dp-root", "#dp-child"])
    assert recs["#dp-root"] is not None and recs["#dp-child"] is not None, recs
    for sel in ("#dp-root", "#dp-child"):
        c = recs[sel]["creator"]
        assert not c.startswith("1p:"), f"{sel} script-built but labeled 1p: {recs[sel]}"
        assert c.startswith("3p:thirdparty.test") or c == "unknown", recs[sel]


# --- HTML strings ---------------------------------------------------------------

def test_07_first_party_inline_script_sets_innerhtml(main):
    """A first-party inline script sets innerHTML. Expected: first party."""
    rec = record(main, "#innerHTML-link")
    assert rec is not None, "innerHTML-link not tracked in provenance"
    assert rec["creator"] == "1p:inline"
    assert rec["via"] == "innerHTML"


def test_08_first_party_inline_script_calls_insertadjacenthtml(main):
    """A first-party inline script calls insertAdjacentHTML. Expected: first party."""
    rec = record(main, "#adj-span")
    assert rec is not None, "adj-span not tracked in provenance"
    assert rec["via"] == "insertAdjacentHTML"
    assert rec["creator"] == "1p:inline"


def test_09_third_party_script_inserts_sibling_with_insertadjacenthtml():
    """A third-party script inserts a sibling with insertAdjacentHTML. Expected:
    not first party."""
    rec = tracked(P.ADJACENT_SIBLING, ["#sib"])["#sib"]
    assert rec is not None, "insertAdjacentHTML sibling not tracked (looks parser/1p)"
    assert not rec["creator"].startswith("1p:"), f"sibling labeled 1p: {rec}"


def test_10_third_party_script_calls_document_write():
    """A third-party script calls document.write. Expected: third party."""
    rec = tracked(P.DOC_WRITE, ["#dw"])["#dw"]
    assert rec is not None, "document.write node not tracked (looks parser-created)"
    assert rec["creator"].startswith("3p:thirdparty.test/writer.js"), rec


# --- Modifications of existing elements ---------------------------------------------

def test_11_third_party_script_rewrites_text_of_first_party_element():
    """A third-party script rewrites the text of a first-party element. Expected:
    element first party; text by third party."""
    rec = tracked(P.TEXT_REWRITE, ["#target"])["#target"]
    assert rec is not None, "text-modified element not tracked"
    assert rec["creator"] == "1p:inline", f"element creator should stay 1p: {rec}"
    assert any(t.startswith("3p:thirdparty.test") for t in rec.get("text_mods", [])), \
        f"3p text modifier not recorded: {rec}"


def test_12_third_party_script_sets_plain_text_through_innerhtml():
    """A third-party script sets plain text through innerHTML. Expected: text by
    third party."""
    rec = tracked(P.PLAIN_TEXT_INNERHTML, ["#t"])["#t"]
    assert rec is not None, "innerHTML-target not tracked"
    assert any(t.startswith("3p:thirdparty.test") for t in rec.get("text_mods", [])), \
        f"plain-text innerHTML from 3p not in text_mods: {rec}"


def test_13_third_party_script_sets_class_and_data_attributes():
    """A third-party script sets class and data attributes on a first-party
    element. Expected: element first party; attributes by third party."""
    rec = tracked(P.ATTRIBUTE_WRITES, ["#target"])["#target"]
    assert rec is not None, "attr-modified element not tracked"
    assert rec["creator"] == "1p:inline", f"creator should stay 1p: {rec}"
    mods = {(m["attr"], m["by"]) for m in rec.get("attr_mods", [])}
    assert any(a == "class" and b.startswith("3p:thirdparty.test") for a, b in mods), \
        f"3p class write not recorded: {rec}"
    assert any(a == "data-tracking" and b.startswith("3p:thirdparty.test")
               for a, b in mods), f"3p data-* write not recorded: {rec}"


def test_14_first_party_inline_script_sets_aria_label(main):
    """A first-party inline script sets aria-label. Expected: attribute by first
    party."""
    rec = record(main, "#attr-mod-div")
    assert rec is not None, "attr-mod-div not tracked in provenance"
    aria_mods = [m for m in rec.get("attr_mods", []) if m["attr"] == "aria-label"]
    assert aria_mods, f"no aria-label mod in attr_mods={rec['attr_mods']}"
    assert aria_mods[0]["by"] == "1p:inline", f"got by={aria_mods[0]['by']!r}"


def test_15_first_party_inline_script_attaches_event_listener(main):
    """A first-party inline script attaches an event listener. Expected: listener
    by first party."""
    rec = record(main, "#listener-btn")
    assert rec is not None, "listener-btn not tracked in provenance"
    assert "1p:inline" in rec["listeners"], f"listeners={rec['listeners']}"


# --- Code without a URL -------------------------------------------------------------

def test_16_third_party_script_creates_element_inside_eval():
    """A third-party script creates an element inside eval'd code. Expected:
    third party."""
    rec = tracked(P.EVAL, ["#via-eval"])["#via-eval"]
    assert rec is not None, "eval-created element not tracked"
    assert rec["creator"].startswith("3p:thirdparty.test/evaler.js"), rec


def test_17_third_party_script_inserts_inline_script_that_creates_element(main):
    """A third-party script inserts an inline script that creates an element.
    Expected: third party, via a synthetic URL."""
    prov = main["provenance"]
    rec = record(main, "#chain-b-inline-img")
    assert rec is not None, "chain-b-inline-img not tracked"
    assert rec["creator"].startswith(P.tp("chain_b.js")), (
        f"expected chain_b.js attribution to survive textContent injection; "
        f"got {rec['creator']!r}")
    assert f"src→{P.TP_LOAD}" in rec["loads"], f"loads={rec['loads']}"
    pixel2 = [r for r in prov["network"] if "pixel2.gif" in r["url"]]
    assert pixel2, f"no network request for pixel2.gif; network={[r['url'] for r in prov['network']]}"
    inline_id = rec.get("via_inline_id")
    assert inline_id, f"expected via_inline_id on rec; got {rec}"
    assert inline_id.startswith("cdpprov://dynamic-inline/"), \
        f"unexpected via_inline_id format: {inline_id!r}"
    info = prov["inline_scripts"].get(inline_id)
    assert info is not None, f"inline_id {inline_id!r} missing from inline_scripts registry"
    assert info["creator"].startswith(P.tp("chain_b.js")), \
        f"inline_scripts entry should point to chain_b.js; got creator={info['creator']!r}"


def test_18_inserted_inline_script_creates_element_in_timer_callback(main):
    """As above, but the element is created in a timer callback. Expected: third
    party, via a synthetic URL."""
    prov = main["provenance"]
    rec = record(main, "#chain-b-async-inline-img")
    assert rec is not None, "chain-b-async-inline-img not tracked"
    assert rec["creator"].startswith(P.tp("chain_b.js")), (
        f"expected chain_b.js attribution for async inline injection; got {rec['creator']!r}")
    inline_id = rec.get("via_inline_id")
    assert inline_id, f"expected via_inline_id on async rec; got {rec}"
    assert inline_id.startswith("cdpprov://dynamic-inline/"), \
        f"unexpected via_inline_id format: {inline_id!r}"
    info = prov["inline_scripts"].get(inline_id)
    assert info is not None, f"inline_id {inline_id!r} missing from inline_scripts registry"
    assert info["creator"].startswith(P.tp("chain_b.js")), \
        f"async inline_scripts entry should point to chain_b.js; got {info['creator']!r}"
    pixel3 = [r for r in prov["network"] if "pixel3.gif" in r["url"]]
    assert pixel3, f"no network request for pixel3.gif; network={[r['url'] for r in prov['network']]}"


# --- Script chains, frames, and network ------------------------------------------

def test_19_script_chain_attributes_element_to_the_last_script(main):
    """An inline script inserts third-party script A, which inserts third-party
    script B from the same domain, which creates an element. Expected: script B,
    distinct from A."""
    rec = record(main, "#chain-a-script-tag")
    assert rec is not None, "chain-a-script-tag not tracked"
    assert rec["creator"] == "1p:inline", (
        f"<script> element created by inline code; got creator={rec['creator']!r}")
    assert f"src→{P.TP_LOAD}" in rec["loads"], f"expected 3p src load; loads={rec['loads']}"
    rec = record(main, "#chain-b-script-tag")
    assert rec is not None, "chain-b-script-tag not tracked"
    assert rec["creator"].startswith(P.tp("chain_a.js")), (
        f"expected chain_a.js as creator; got {rec['creator']!r}")
    assert f"src→{P.TP_LOAD}" in rec["loads"], f"loads={rec['loads']}"
    rec = record(main, "#chain-b-span")
    assert rec is not None, "chain-b-span not tracked"
    assert rec["creator"].startswith(P.tp("chain_b.js")), f"got creator={rec['creator']!r}"


def test_20_script_in_third_party_iframe_creates_element():
    """A script in a third-party iframe creates an element. Expected: captured,
    third party."""
    els = list(P.capture(BrowserSession, P.IFRAME_3P)["provenance"]["elements"].values())
    framed = [e for e in els
              if str(e.get("creator", "")).startswith("3p:thirdparty.test/frame.html")]
    assert framed, ("iframe element not captured; "
                    f"got creators: {[e.get('creator') for e in els]}")


def test_21_site_isolated_cross_origin_iframe_content_is_captured():
    """A site-isolated cross-origin iframe holds content. Expected: captured,
    linked to its iframe element."""
    state = P.capture(BrowserSession, P.ISOLATED_FRAMES)["state"]
    link = P.element_by_id(state, P.FRAME_URL, "in3p")
    made = P.element_by_id(state, P.FRAME_URL, "made-in-frame")
    assert link is not None and made is not None, "isolated iframe content missing"
    assert link["document"]["scope"] == "3p"
    assert str((made.get("provenance") or {}).get("creator", "")).startswith(
        "3p:thirdparty.test")
    bnis = [e["bni"] for e in state["elements"]]
    assert len(bnis) == len(set(bnis)), "backendNodeIds collide across processes"
    assert state["uncaptured_frames"] == []
    frames = [f for f in state["frames"] if f["url"] == P.FRAME_URL]
    assert len(frames) == 1
    owner = next(e for e in state["elements"] if e["bni"] == frames[0]["owner_bni"])
    assert owner["tag"] == "iframe" and owner["attrs"].get("id") == "ad"


def test_22_third_party_script_creates_image_with_third_party_source(main):
    """A third-party script creates an image with a third-party source. Expected:
    request attributed to the script.

    The request is tied to the script through the image's record: its creator
    is the script, and its `loads` names the destination. Chrome reports no
    script call stack for a request that an img.src assignment starts, so the
    network log's entry for it has an empty initiator_script."""
    prov = main["provenance"]
    rec = record(main, "#chain-a-img")
    assert rec is not None, "chain-a-img not tracked"
    assert rec["creator"].startswith(P.tp("chain_a.js"))
    assert f"src→{P.TP_LOAD}" in rec["loads"], f"loads={rec['loads']}"
    pixel = [r for r in prov["network"] if "pixel_a.gif" in r["url"]]
    assert pixel, f"no network request for pixel_a.gif; network={[r['url'] for r in prov['network']]}"
    assert pixel[0]["domain"] == P.TP_DOMAIN
    assert pixel[0]["initiator_script"] == ""


def test_23_engine_compiles_script_recorded_with_content_hash(main):
    """The engine compiles a script. Expected: recorded with its content hash."""
    instances = main["provenance"]["script_instances"]
    assert instances, "script_instances registry is empty"
    for sid, info in instances.items():
        assert "url" in info, f"scriptId {sid} missing 'url'"
        assert "hash" in info, f"scriptId {sid} missing 'hash'"
        assert "contextId" in info, f"scriptId {sid} missing 'contextId'"
    tp_scripts = {sid: info for sid, info in instances.items()
                  if P.TP_DOMAIN in info.get("url", "")}
    assert tp_scripts, "no 3p scripts found in script_instances registry"
    for sid, info in tp_scripts.items():
        assert info["hash"], f"3p script {info['url']} has empty hash (scriptId={sid})"
    chain_a = [(sid, i) for sid, i in tp_scripts.items() if "chain_a" in i["url"]]
    chain_b = [(sid, i) for sid, i in tp_scripts.items() if "chain_b" in i["url"]]
    assert chain_a, "chain_a.js not in script_instances"
    assert chain_b, "chain_b.js not in script_instances"
    (a_sid, a_info), (b_sid, b_info) = chain_a[0], chain_b[0]
    assert a_sid != b_sid, "chain_a.js and chain_b.js must have distinct scriptIds"
    assert a_info["hash"] != b_info["hash"], \
        "chain_a.js and chain_b.js must have distinct content hashes"


def test_24_page_redirects_to_another_site():
    """A page redirects to another site. Expected: parties relabeled against the
    landing site.

    Playwright's request routing cannot follow a mocked redirect, so the test
    loads the landing site (newsite.test) with the tracker still labeled for the
    requested site (oldsite.test), as after a cross-site redirect."""
    with P.open_page(BrowserSession, P.REDIRECT_LANDING) as session:
        session._tracker.page_origin = "oldsite.test"   # labeled for the requested site
        state = session.capture()
    assert state["provenance"]["page_origin"] == "newsite.test"
    made = next(e for e in state["elements"]
                if (e.get("attrs") or {}).get("id") == "made-by-app")
    assert str(made["provenance"]["creator"]).startswith("1p:")


@pytest.mark.xfail(reason="known gap: collection does not pierce shadow roots",
                   strict=False)
def test_known_gap_element_in_open_shadow_root():
    """A script creates an element inside an open shadow root. Expected:
    captured; the instrumentation does not yet cover shadow roots."""
    els = list(P.capture(BrowserSession, P.SHADOW_ROOT)["provenance"]["elements"].values())
    created = [e for e in els if e.get("via") == "createElement"]
    assert created, "shadow-root element should be captured"
