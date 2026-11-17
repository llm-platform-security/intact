"""Unit tests for intact/gentree/serialize.py.

Feeds synthetic state dicts and asserts the JSON-friendly output is exactly
what the schema promises: enum sets become sorted string-name arrays, AX block
is null-ish when ax_in_tree=False, provenance passes through, classification
absence is preserved.
"""

import json

from intact.gentree.serialize import (
    serialize_element,
    serialize_representation,
)
from intact.gentree.taxonomy import (
    AgentView, Authority, AuthoritySet, Channel, Effect, EffectSet,
    ElementClassification, Exposure,
)


def _cls(rule="static:base",
         direct=None, inherited=None, blocked=None,
         observable=None,
         channels=None, views=None) -> ElementClassification:
    return ElementClassification(
        authority=AuthoritySet(
            direct=set(direct or []),
            inherited=set(inherited or []),
            blocked=set(blocked or []),
        ),
        effects=EffectSet(observable=set(observable or [])),
        exposure=Exposure(
            channels=set(channels or [Channel.BODY_TEXT]),
            visible_to=set(views or [AgentView.AX_TREE, AgentView.DOM_TEXT]),
        ),
        source_rule=rule,
    )


def _entry(bni=1, tag="div", attrs=None, depth=0, parent_bni=None,
           ax_in_tree=False, role="", name="",
           classification=None, provenance=None,
           properties=None, ignored=False, ax_node_id=None,
           document=None):
    return {
        "bni":            bni,
        "tag":            tag,
        "attrs":          attrs or {},
        "depth":          depth,
        "parent_bni":     parent_bni,
        "doc_index":      0,
        "ax_node_id":     ax_node_id,
        "role":           role,
        "name":           name,
        "description":    "",
        "properties":     properties or {},
        "ignored":        ignored,
        "ax_in_tree":     ax_in_tree,
        "document":       document if document is not None
                           else {"url": "https://www.cnn.com/x", "scope": "1p"},
        "classification": classification,
        "provenance":     provenance,
    }


# ── Enum serialization ─────────────────────────────────────────────────────

def test_authority_sets_serialize_to_sorted_string_arrays():
    cls = _cls(
        rule="anchor:href",
        direct={Authority.CLICK},
        inherited={Authority.FOCUS},
        blocked={Authority.HOVER},
    )
    out = serialize_element(_entry(classification=cls))
    auth = out["classification"]["authority"]
    assert auth["direct"]    == ["click"]
    assert auth["inherited"] == ["focus"]
    assert auth["blocked"]   == ["hover"]
    # effective = (direct ∪ inherited) − blocked
    assert auth["effective"] == ["click", "focus"]


def test_effects_serialize_to_sorted_string_array():
    cls = _cls(observable={Effect.NAVIGATE, Effect.NAVIGATE_FRAME, Effect.SEND_REQUEST})
    out = serialize_element(_entry(classification=cls))
    assert out["classification"]["effects"]["observable"] == [
        "navigate", "navigate-frame", "send-request"
    ]


def test_exposure_channels_and_views_serialize_to_sorted_arrays():
    cls = _cls(
        channels={Channel.BODY_TEXT, Channel.ALT, Channel.META_OG},
        views={AgentView.DOM_TEXT, AgentView.AX_TREE},
    )
    out = serialize_element(_entry(classification=cls))
    expo = out["classification"]["exposure"]
    assert expo["channels"]   == ["alt", "body-text", "meta-og"]
    assert expo["visible_to"] == ["ax-tree", "dom-text"]


def test_empty_authority_sets_become_empty_arrays_not_null():
    """JSON arrays — never `null` — for empty sets, so consumers can safely
    iterate without null-guards."""
    cls = _cls()  # all sets empty
    out = serialize_element(_entry(classification=cls))
    auth = out["classification"]["authority"]
    assert auth["direct"]    == []
    assert auth["inherited"] == []
    assert auth["blocked"]   == []
    assert auth["effective"] == []
    assert out["classification"]["effects"]["observable"] == []


# ── AX block ───────────────────────────────────────────────────────────────

def test_ax_block_when_in_tree_carries_role_name_properties():
    entry = _entry(
        ax_in_tree=True, role="link", name="CNN home",
        properties={"focusable": True}, ax_node_id="42",
    )
    out = serialize_element(entry)
    assert out["ax"]["in_tree"]    is True
    assert out["ax"]["role"]       == "link"
    assert out["ax"]["name"]       == "CNN home"
    assert out["ax"]["properties"] == {"focusable": True}
    assert out["ax"]["node_id"]    == "42"


def test_ax_block_when_not_in_tree_is_all_nulls():
    """Script tags, meta tags, hidden inputs — keep the key but null-out
    the fields. Consumers can do `if elem["ax"]["in_tree"]: ...`."""
    entry = _entry(ax_in_tree=False)
    out = serialize_element(entry)
    assert out["ax"]["in_tree"]    is False
    assert out["ax"]["role"]       is None
    assert out["ax"]["name"]       is None
    assert out["ax"]["properties"] is None
    assert out["ax"]["node_id"]    is None


# ── Classification absence ─────────────────────────────────────────────────

def test_classification_none_serializes_as_null():
    out = serialize_element(_entry(classification=None))
    assert out["classification"] is None


def test_composition_notes_passed_through():
    cls = _cls()
    cls.composition_notes = ["wrapping-anchor:extend-click", "disabled:block-all"]
    out = serialize_element(_entry(classification=cls))
    assert out["classification"]["composition_notes"] == [
        "wrapping-anchor:extend-click", "disabled:block-all"
    ]


# ── Provenance passthrough ─────────────────────────────────────────────────

def test_provenance_dict_passed_through_unchanged():
    prov = {"creator": "3p:ads.example", "via": "createElement",
            "loads": ["src→3p:taboola.com"]}
    out = serialize_element(_entry(provenance=prov))
    assert out["provenance"] == prov


def test_provenance_none_when_absent():
    out = serialize_element(_entry(provenance=None))
    assert out["provenance"] is None


# ── DOM-tree metadata preserved ────────────────────────────────────────────

def test_dom_tree_metadata_preserved():
    out = serialize_element(_entry(
        bni=55, tag="a", attrs={"href": "/x", "class": "link"},
        depth=3, parent_bni=12,
    ))
    assert out["bni"]        == 55
    assert out["tag"]        == "a"
    assert out["attrs"]      == {"href": "/x", "class": "link"}
    assert out["depth"]      == 3
    assert out["parent_bni"] == 12


# ── Document (HTTP-response granularity) ───────────────────────────────────

def test_document_field_serialized_when_present():
    out = serialize_element(_entry(
        document={"url": "https://doubleclick.net/ad", "scope": "3p"},
    ))
    assert out["document"] == {"url": "https://doubleclick.net/ad", "scope": "3p"}


def test_document_field_defaults_when_missing():
    """If unified_view didn't populate it (older state), the serializer
    emits a sentinel empty 1p block rather than dropping the field."""
    entry = _entry()
    entry["document"] = None
    out = serialize_element(entry)
    assert out["document"] == {"url": "", "scope": "1p"}


# ── Top-level wrapper ──────────────────────────────────────────────────────

def test_serialize_representation_wraps_with_url_and_count():
    state = {
        "elements": [
            _entry(bni=1, tag="html"),
            _entry(bni=2, tag="body", parent_bni=1, depth=1),
        ],
    }
    out = serialize_representation(state, url="https://www.cnn.com/")
    assert out["url"] == "https://www.cnn.com/"
    assert out["element_count"] == 2
    assert len(out["elements"]) == 2
    # captured_at is ISO-8601-ish
    assert "T" in out["captured_at"]


# ── Text field (optional) ──────────────────────────────────────────────────

def test_text_field_emitted_when_present():
    entry = _entry(bni=42, tag="p")
    entry["text"] = "Hello world"
    out = serialize_element(entry)
    assert out["text"] == "Hello world"


def test_text_field_omitted_when_absent():
    """The schema makes `text` optional — elements without direct text-node
    children should not carry the key at all (cleaner output, smaller artifact)."""
    out = serialize_element(_entry(bni=42, tag="div"))
    assert "text" not in out


def test_text_field_omitted_when_empty_string():
    entry = _entry(bni=42, tag="div")
    entry["text"] = ""
    out = serialize_element(entry)
    assert "text" not in out


# ── delivery_3p (optional) ────────────────────────────────────────────────

def test_delivery_3p_emitted_when_present():
    entry = _entry(bni=42, tag="script")
    entry["delivery_3p"] = [{"attr": "src", "host": "googlesyndication.com"}]
    out = serialize_element(entry)
    assert out["delivery_3p"] == [{"attr": "src", "host": "googlesyndication.com"}]


def test_delivery_3p_omitted_when_absent():
    out = serialize_element(_entry(bni=42, tag="div"))
    assert "delivery_3p" not in out


def test_delivery_3p_omitted_when_empty_list():
    entry = _entry(bni=42, tag="div")
    entry["delivery_3p"] = []
    out = serialize_element(entry)
    assert "delivery_3p" not in out


def test_full_payload_round_trips_through_json():
    """The whole thing must be json.dumps-able — no Python-only values leak."""
    cls = _cls(
        rule="anchor:href",
        direct={Authority.CLICK},
        observable={Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
    )
    state = {"elements": [_entry(
        bni=10, tag="a", attrs={"href": "https://x.com"},
        classification=cls,
        provenance={"creator": "parser"},
    )]}
    payload = serialize_representation(state, url="https://test/")
    text = json.dumps(payload)         # must not raise
    decoded = json.loads(text)
    assert decoded["taxonomy_version"] == "interaction-effects-v2"
    assert decoded["elements"][0]["classification"]["source_rule"] == "anchor:href"
    assert decoded["elements"][0]["provenance"]["creator"] == "parser"


def test_serialize_representation_carries_isolated_frames_and_guard():
    state = {"elements": [],
             "frames": [{"segment": 1, "url": "https://ads.test/f.html",
                         "owner_bni": 7, "doc_index": 1}],
             "uncaptured_frames": [{"target_id": "B", "url": "https://x.test/"}]}
    out = serialize_representation(state, url="https://example.com/")
    assert out["frames"] == state["frames"]
    assert out["uncaptured_frames"] == state["uncaptured_frames"]


def test_serialize_representation_defaults_frames_to_empty_lists():
    out = serialize_representation({"elements": []}, url="https://example.com/")
    assert out["frames"] == [] and out["uncaptured_frames"] == []


def test_serialize_representation_carries_capture_status():
    cap = {"status": "blocked", "requested_url": "https://upi.com",
           "final_url": "https://upi.com/", "title": "Attention Required!",
           "cross_site_redirect": False, "attempts": 2}
    out = serialize_representation({"elements": [], "capture": cap}, url="https://upi.com")
    assert out["capture"] == cap
    assert serialize_representation({"elements": []})["capture"] == {}
