"""GenTree end to end on a news-style page: classification, the unified element
records, and the serialized schema. The page is tests/pages.py: NEWS."""

import pytest

from intact.browser.session import BrowserSession
from intact.gentree.serialize import serialize_representation
from intact.gentree.taxonomy import Authority, Channel, Effect
from tests import pages as P

SELECTORS = ("h1.headline", "nav.primary-nav a", ".newsletter-form button[type=submit]",
             "iframe#ad-iframe", "form.newsletter-form")


@pytest.fixture(scope="module")
def news():
    return P.capture(BrowserSession, P.NEWS, SELECTORS)


def classification(news, selector):
    bni = news["bni"][selector]
    assert bni, f"{selector} should be findable"
    cls = news["state"]["classification"].get(bni)
    assert cls is not None, f"no classification for bni={bni}"
    return cls


def test_capture_attaches_classification(news):
    classifications = news["state"]["classification"]
    assert isinstance(classifications, dict)
    assert len(classifications) > 0, "classification dict should be populated"


def test_headline_classifies_as_static_text(news):
    cls = classification(news, "h1.headline")
    assert cls.source_rule == "static:base"
    assert cls.authority.effective == set()
    assert Channel.BODY_TEXT in cls.exposure.channels


def test_nav_anchor_classifies_as_navigable_link(news):
    cls = classification(news, "nav.primary-nav a")
    assert cls.source_rule == "anchor:href"
    assert Authority.CLICK in cls.authority.direct
    assert Effect.NAVIGATE in cls.effects.observable
    assert Effect.SEND_REQUEST in cls.effects.observable
    assert Effect.NAVIGATE_FRAME in cls.effects.observable


def test_newsletter_submit_button_classifies_in_form(news):
    cls = classification(news, ".newsletter-form button[type=submit]")
    assert cls.source_rule == "button:in-form"
    assert Effect.SUBMIT in cls.effects.observable
    assert Effect.SEND_REQUEST in cls.effects.observable


def test_ad_iframe_classifies_as_embedded(news):
    cls = classification(news, "iframe#ad-iframe")
    assert cls.source_rule == "embedded:iframe"
    assert Effect.RENDER_FRAME in cls.effects.observable
    assert Effect.POST_MESSAGE in cls.effects.observable
    assert Effect.FETCH in cls.effects.observable  # iframe has src=


def test_form_has_submit_effect_without_click_authority(news):
    cls = classification(news, "form.newsletter-form")
    assert cls.source_rule == "form:root"
    assert cls.authority.effective == set()
    assert Effect.SUBMIT in cls.effects.observable


def test_classification_count_is_sane(news):
    """Every element of the page is classified (86 on this page)."""
    n = len(news["state"]["classification"])
    assert n >= 80, f"only {n} elements classified; spec builder may have regressed"
    assert n == len(news["state"]["elements"]), \
        f"{n} classifications for {len(news['state']['elements'])} elements"


def test_unified_elements_join_dom_ax_classification_provenance(news):
    elements = news["state"]["elements"]
    assert len(elements) >= 80, "unified elements list should cover the whole DOM"
    logo = [e for e in elements if e["role"] == "link" and "Home" in (e["name"] or "")]
    assert logo, "expected to find a 'Home' link record"
    rec = logo[0]
    assert rec["tag"] == "a"
    assert rec["classification"] is not None
    assert rec["classification"].source_rule == "anchor:href"
    assert Effect.NAVIGATE in rec["classification"].effects.observable
    tracker = P.element_by_id(news["state"], P.NEWS.url, "tracker")
    banner = P.element_by_id(news["state"], P.NEWS.url, "banner")
    assert tracker is not None and banner is not None, "script-created elements missing"
    assert str((tracker["provenance"] or {}).get("creator", "")).startswith(
        P.tp("analytics.js")), f"tracker provenance: {tracker['provenance']}"
    assert (banner["provenance"] or {}).get("creator") == "1p:app.js", \
        f"banner provenance: {banner['provenance']}"


def test_unified_elements_include_non_ax_elements(news):
    scripts = [e for e in news["state"]["elements"] if e["tag"] == "script"]
    assert scripts, "expected <script> elements in state['elements']"
    for s in scripts:
        assert s["ax_in_tree"] is False


def test_unified_elements_carry_document_url_and_scope(news):
    elements = news["state"]["elements"]
    for entry in elements:
        assert "document" in entry
        assert "url" in entry["document"]
        assert "scope" in entry["document"]
        assert entry["document"]["scope"] in {"1p", "3p"}
    top = [e for e in elements if e["doc_index"] == 0]
    assert top, "expected top-frame elements"
    assert all(e["document"]["scope"] == "1p" for e in top), \
        "top-frame elements should all be 1p"
    assert any("firstparty.test" in e["document"]["url"] for e in top), \
        "top-frame URL should reference firstparty.test"


def test_unified_elements_carry_dom_tree_metadata(news):
    for entry in news["state"]["elements"]:
        assert "depth" in entry
        assert isinstance(entry["depth"], int)
        assert "parent_bni" in entry   # may be None for roots
        assert "tag" in entry
        assert isinstance(entry["tag"], str)


def test_ad_iframe_elements_are_third_party(news):
    ad = [e for e in news["state"]["elements"] if e["document"]["url"] == P.TP + "ad.html"]
    assert ad, "expected the ad iframe's elements"
    assert all(e["document"]["scope"] == "3p" for e in ad)


TOP_KEYS = {"url", "taxonomy_version", "captured_at", "element_count", "frames",
            "uncaptured_frames", "capture", "elements"}
ELEMENT_KEYS = {"bni", "tag", "attrs", "depth", "parent_bni", "doc_index", "document",
                "ax", "classification", "provenance"}
OPTIONAL_ELEMENT_KEYS = {"text", "delivery_3p"}
AX_KEYS = {"in_tree", "node_id", "role", "name", "description", "properties", "ignored"}
CLASSIFICATION_KEYS = {"source_rule", "authority", "effects", "exposure", "composition_notes"}


def test_serialized_gentree_matches_the_documented_schema(news):
    out = serialize_representation(news["state"], url=P.NEWS.url)
    assert set(out) == TOP_KEYS
    assert out["element_count"] == len(out["elements"])
    for e in out["elements"]:
        assert ELEMENT_KEYS <= set(e) <= ELEMENT_KEYS | OPTIONAL_ELEMENT_KEYS, set(e)
        assert set(e["document"]) == {"url", "scope"}
        assert set(e["ax"]) == AX_KEYS
        if e["classification"] is not None:
            assert set(e["classification"]) == CLASSIFICATION_KEYS
