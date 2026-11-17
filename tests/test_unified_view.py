"""Unit tests for build_unified_elements (DOM-shaped).

Feeds synthetic state dicts with mocked dom_records + ax_nodes +
classification + provenance and asserts the join is correct and the
output preserves DOM-tree pre-order.
"""

from intact.gentree.taxonomy import (
    Authority, AuthoritySet, Channel, Effect, EffectSet, Exposure,
    AgentView, ElementClassification,
)
from intact.gentree.unified_view import build_unified_elements


def _cls(rule="static:base", direct=None, observable=None) -> ElementClassification:
    return ElementClassification(
        authority=AuthoritySet(direct=set(direct or [])),
        effects=EffectSet(observable=set(observable or [])),
        exposure=Exposure(
            channels={Channel.BODY_TEXT},
            visible_to={AgentView.AX_TREE, AgentView.DOM_TEXT},
        ),
        source_rule=rule,
    )


def _ax(node_id, bni, role, name, properties=None):
    return {
        "nodeId":            str(node_id),
        "backendDOMNodeId":  bni,
        "role":              {"value": {"value": role}},
        "name":              {"value": {"value": name}},
        "description":       {"value": {"value": ""}},
        "properties":        properties or [],
        "ignored":           False,
    }


def _dr(bni, tag, depth=0, parent_bni=None, attrs=None,
        doc_index=0, doc_url="https://www.cnn.com/world/article"):
    return {
        "bni":         bni,
        "tag":         tag,
        "attrs":       attrs or {},
        "depth":       depth,
        "parent_bni":  parent_bni,
        "doc_index":   doc_index,
        "doc_url":     doc_url,
    }


# ── Tree shape ─────────────────────────────────────────────────────────────

def test_unified_preserves_dom_preorder():
    state = {
        "dom_records": [
            _dr(10, "html", depth=0),
            _dr(20, "body", depth=1, parent_bni=10),
            _dr(30, "h1",   depth=2, parent_bni=20),
            _dr(40, "p",    depth=2, parent_bni=20),
        ],
        "ax_nodes":     [],
        "classification": {10: _cls(), 20: _cls(), 30: _cls(), 40: _cls()},
        "provenance":   {"elements": {}},
    }
    bnis = [e["bni"] for e in build_unified_elements(state)]
    assert bnis == [10, 20, 30, 40]


def test_unified_carries_tag_attrs_depth():
    state = {
        "dom_records": [_dr(55, "a", depth=3, attrs={"href": "https://example.com"})],
        "ax_nodes": [],
        "classification": {55: _cls("anchor:href",
                                     direct={Authority.CLICK}, observable={Effect.NAVIGATE})},
        "provenance": {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["tag"] == "a"
    assert entry["attrs"]["href"] == "https://example.com"
    assert entry["depth"] == 3
    assert entry["classification"].source_rule == "anchor:href"


# ── AX join ────────────────────────────────────────────────────────────────

def test_unified_ax_fields_when_node_is_in_ax():
    state = {
        "dom_records": [_dr(55, "a")],
        "ax_nodes":    [_ax("12", 55, "link", "CNN home")],
        "classification": {55: _cls("anchor:href")},
        "provenance":  {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["ax_in_tree"] is True
    assert entry["role"] == "link"
    assert entry["name"] == "CNN home"
    assert entry["ax_node_id"] == "12"


def test_unified_ax_fields_empty_when_not_in_ax():
    """Hidden inputs, script tags, meta tags etc. have no AX entry but
    must still appear in state['elements']."""
    state = {
        "dom_records": [_dr(99, "script", attrs={"src": "/a.js"})],
        "ax_nodes":    [],   # script never in AX
        "classification": {99: _cls("scripting:script-external",
                                     observable={Effect.FETCH, Effect.EXECUTE})},
        "provenance":  {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["ax_in_tree"] is False
    assert entry["role"] == ""
    assert entry["name"] == ""
    assert entry["ax_node_id"] is None
    # But classification still present:
    assert entry["classification"].source_rule == "scripting:script-external"


def test_unified_ax_properties_extracted():
    props = [
        {"name": "focusable", "value": {"value": True}},
        {"name": "disabled",  "value": {"value": False}},
    ]
    state = {
        "dom_records": [_dr(7, "button")],
        "ax_nodes":    [_ax("9", 7, "button", "Go", properties=props)],
        "classification": {7: _cls()},
        "provenance":  {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["properties"] == {"focusable": True, "disabled": False}


# ── Provenance join ────────────────────────────────────────────────────────

def test_unified_attaches_provenance_when_present():
    state = {
        "dom_records": [_dr(10, "script", attrs={"src": "/a.js"})],
        "ax_nodes":    [],
        "classification": {10: _cls("scripting:script-external")},
        "provenance":  {"elements": {10: {"creator": "3p:ads.example", "via": "createElement"}}},
    }
    [entry] = build_unified_elements(state)
    assert entry["provenance"]["creator"] == "3p:ads.example"
    assert entry["provenance"]["via"] == "createElement"


def test_unified_provenance_none_for_parser_static():
    state = {
        "dom_records": [_dr(10, "p")],
        "ax_nodes":    [],
        "classification": {10: _cls()},
        "provenance":  {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["provenance"] is None


# ── Both AX-and-non-AX present in same output ──────────────────────────────

# ── Document URL + scope (HTTP-response granularity for parser case) ──────

def test_unified_attaches_document_url_and_scope_for_top_frame():
    state = {
        "dom_records": [_dr(10, "html", doc_url="https://www.cnn.com/x")],
        "ax_nodes": [], "classification": {10: _cls()},
        "provenance": {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["document"]["url"]   == "https://www.cnn.com/x"
    assert entry["document"]["scope"] == "1p"


def test_unified_classifies_iframe_document_as_3p():
    """An element parsed from a 3p iframe's document gets scope=3p — that's
    the HTTP-response granularity the consumer needs to distinguish bytes
    delivered by the main HTML response vs. by a 3p iframe response."""
    state = {
        "dom_records": [
            _dr(10, "html",   doc_index=0, doc_url="https://www.cnn.com/x"),
            _dr(20, "iframe", doc_index=0, doc_url="https://www.cnn.com/x", parent_bni=10),
            _dr(30, "html",   doc_index=1, doc_url="https://doubleclick.net/ad"),
            _dr(40, "div",    doc_index=1, doc_url="https://doubleclick.net/ad", parent_bni=30),
        ],
        "ax_nodes": [],
        "classification": {10: _cls(), 20: _cls(), 30: _cls(), 40: _cls()},
        "provenance": {"elements": {}},
    }
    by_bni = {e["bni"]: e for e in build_unified_elements(state)}
    assert by_bni[10]["document"]["scope"] == "1p"
    assert by_bni[20]["document"]["scope"] == "1p"
    assert by_bni[30]["document"]["scope"] == "3p"
    assert by_bni[30]["document"]["url"]   == "https://doubleclick.net/ad"
    assert by_bni[40]["document"]["scope"] == "3p"


def test_unified_document_field_present_even_when_doc_url_missing():
    state = {
        "dom_records": [_dr(10, "html", doc_url="")],
        "ax_nodes": [], "classification": {10: _cls()},
        "provenance": {"elements": {}},
    }
    [entry] = build_unified_elements(state)
    assert entry["document"] == {"url": "", "scope": "1p"}


# ── Full DOM tree (AX + non-AX together) ──────────────────────────────────

def test_full_dom_tree_includes_both_ax_and_non_ax_elements():
    """The unified list must include hidden inputs, scripts, etc. alongside
    AX-visible elements — that's the whole point of the DOM-shaped pivot."""
    state = {
        "dom_records": [
            _dr(1, "html", depth=0),
            _dr(2, "head", depth=1, parent_bni=1),
            _dr(3, "script", depth=2, parent_bni=2, attrs={"src": "/a.js"}),
            _dr(4, "meta",   depth=2, parent_bni=2, attrs={"property": "og:title"}),
            _dr(5, "body", depth=1, parent_bni=1),
            _dr(6, "h1",   depth=2, parent_bni=5),
            _dr(7, "input", depth=2, parent_bni=5, attrs={"type": "hidden"}),
        ],
        "ax_nodes": [
            _ax("a", 1, "WebArea", ""),
            _ax("b", 5, "main", ""),
            _ax("c", 6, "heading", "Hi"),
            # Note: script, meta, hidden input NOT in AX.
        ],
        "classification": {
            1: _cls(), 2: _cls(), 3: _cls("scripting:script-external"),
            4: _cls("scripting:meta-og"), 5: _cls(), 6: _cls(), 7: _cls("input:hidden"),
        },
        "provenance": {"elements": {}},
    }
    elements = build_unified_elements(state)
    bnis = [e["bni"] for e in elements]
    # All 7 DOM elements present, in DOM order.
    assert bnis == [1, 2, 3, 4, 5, 6, 7]
    # Script, meta, hidden input — not in AX but still in the list.
    by_bni = {e["bni"]: e for e in elements}
    assert by_bni[3]["ax_in_tree"] is False  # script
    assert by_bni[4]["ax_in_tree"] is False  # meta
    assert by_bni[7]["ax_in_tree"] is False  # hidden input
    # AX-visible ones have role.
    assert by_bni[6]["role"] == "heading"


# ── delivery_3p attribution ────────────────────────────────────────────────

def _state(records, page_url="https://www.cnn.com/world/article"):
    """Minimal state wrapper — no AX/classification/provenance, just the
    DOM records under the page URL needed to test delivery_3p."""
    return {
        "dom_records": records,
        "ax_nodes": [],
        "classification": {},
        "provenance": {"elements": {}},
    }


def test_delivery_3p_omitted_when_no_url_attrs():
    """Elements with no URL-bearing attrs get no `delivery_3p` key."""
    state = _state([_dr(1, "div", attrs={"class": "x"})])
    elements = build_unified_elements(state)
    assert "delivery_3p" not in elements[0]


def test_delivery_3p_omitted_when_attr_is_1p():
    """`src` pointing at same eTLD+1 as the top frame → no entry."""
    state = _state([_dr(1, "img", attrs={"src": "https://static.cnn.com/x.jpg"})])
    elements = build_unified_elements(state)
    assert "delivery_3p" not in elements[0]


def test_delivery_3p_emitted_for_3p_src():
    """The canonical pixel-tracker / parser-static-3p-script case: src
    pointing at a cross-eTLD+1 host produces a delivery_3p entry."""
    state = _state([_dr(1, "script", attrs={
        "src": "https://googlesyndication.com/pagead/ads.js"})])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "src", "host": "googlesyndication.com"},
    ]


def test_delivery_3p_handles_iframe_shell():
    """An iframe with a 3p src — its body may be empty / declined but the
    iframe element itself attributes to the 3p delivery host."""
    state = _state([_dr(1, "iframe", attrs={
        "src": "https://doubleclick.net/safeframe/abc"})])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "src", "host": "doubleclick.net"},
    ]


def test_delivery_3p_handles_multiple_url_attrs():
    """Same element with multiple URL-bearing attrs (e.g., <video src=
    1p poster=3p>) — each 3p-pointing attr gets its own entry."""
    state = _state([_dr(1, "video", attrs={
        "src":    "https://media.cnn.com/clip.mp4",
        "poster": "https://thumbs.tracker.example/clip.jpg",
    })])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "poster", "host": "thumbs.tracker.example"},
    ]


def test_delivery_3p_handles_srcset_with_multiple_hosts():
    """srcset is comma-separated; each URL portion is parsed and 3p ones
    surface as separate entries."""
    state = _state([_dr(1, "img", attrs={
        "src": "https://static.cnn.com/x.jpg",
        "srcset": ("https://cdn1.example/x-1x.jpg 1x, "
                   "https://cdn2.example/x-2x.jpg 2x"),
    })])
    elements = build_unified_elements(state)
    hosts = sorted(d["host"] for d in elements[0]["delivery_3p"])
    assert hosts == ["cdn1.example", "cdn2.example"]


def test_delivery_3p_skips_data_and_javascript_uris():
    """data:, javascript:, about:, mailto: schemes have no 3p host."""
    state = _state([
        _dr(1, "img",    attrs={"src": "data:image/png;base64,iVBOR..."}),
        _dr(2, "a",      attrs={"href": "javascript:void(0)"}),
        _dr(3, "iframe", attrs={"src": "about:blank"}),
        _dr(4, "a",      attrs={"href": "mailto:test@example.com"}),
    ])
    elements = build_unified_elements(state)
    for e in elements:
        assert "delivery_3p" not in e


def test_delivery_3p_skips_relative_urls():
    """Relative paths are same-origin by definition."""
    state = _state([
        _dr(1, "a",   attrs={"href": "/world/article"}),
        _dr(2, "img", attrs={"src":  "../assets/logo.png"}),
    ])
    elements = build_unified_elements(state)
    for e in elements:
        assert "delivery_3p" not in e


def test_delivery_3p_handles_protocol_relative_urls():
    """//host/path — give it a scheme and extract the host."""
    state = _state([_dr(1, "script", attrs={
        "src": "//tag-manager.example/gtm.js"})])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "src", "host": "tag-manager.example"},
    ]


def test_delivery_3p_form_action_attribution():
    """Forms POSTing to a 3p endpoint count too — relevant for
    cross-origin payment flows and 3p analytics beacons."""
    state = _state([_dr(1, "form", attrs={
        "action": "https://checkout.stripe.com/pay"})])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "action", "host": "checkout.stripe.com"},
    ]


def test_delivery_3p_dedupes_same_attr_host_pair():
    """If srcset repeats a host across multiple candidates, only one
    entry is emitted."""
    state = _state([_dr(1, "img", attrs={
        "srcset": ("https://cdn.example/x-1x.jpg 1x, "
                   "https://cdn.example/x-2x.jpg 2x")})])
    elements = build_unified_elements(state)
    assert elements[0]["delivery_3p"] == [
        {"attr": "srcset", "host": "cdn.example"},
    ]
