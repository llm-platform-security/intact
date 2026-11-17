"""Unit tests for the DOMSnapshot → ElementSpec walker.

Feeds the builder synthetic CDP responses (no live browser) and verifies
the resulting ElementSpec instances have the right tags, attrs, ancestors,
and computed-style flags.
"""

from intact.gentree.spec_builder import (
    COMPUTED_STYLE_NAMES,
    NODE_TYPE_ELEMENT,
    NODE_TYPE_TEXT,
    build_dom_records,
    build_specs_from_snapshot,
)


# String table is shared across the synthetic document.
_STRINGS = [
    "HTML",         # 0
    "BODY",         # 1
    "A",            # 2
    "DIV",          # 3
    "href",         # 4
    "https://example.com",  # 5
    "class",        # 6
    "cta",          # 7
    "block",        # 8 — display value
    "visible",      # 9 — visibility value
    "auto",         # 10 — pointer-events value
    "id",           # 11
    "main",         # 12
    "FORM",         # 13
    "action",       # 14
    "/checkout",    # 15
    "BUTTON",       # 16
    "type",         # 17
    "submit",       # 18
    "P",            # 19
    "Hello",        # 20 — text node content (we skip these)
    "#text",        # 21
]


def _node_idx_in_strings(s: str) -> int:
    return _STRINGS.index(s)


def _make_snapshot() -> dict:
    """Synthetic snapshot:
        html
          body
            a[href="https://example.com"][class="cta"]
            div[id="main"]
              form[action="/checkout"]
                button[type="submit"]
            p (no attrs)
    """
    NT_ELEMENT = NODE_TYPE_ELEMENT
    NT_TEXT = 3  # not used here, but documents that we'd skip it

    # Node arrays — index 0 is html, then body, then a, div, form, button, p.
    # parent_index: -1 means root.
    nodes = {
        "parentIndex": [-1,  0,  1,  1,  3,  4,  1],
        "nodeType":    [NT_ELEMENT, NT_ELEMENT, NT_ELEMENT, NT_ELEMENT,
                        NT_ELEMENT, NT_ELEMENT, NT_ELEMENT],
        "nodeName":    [_node_idx_in_strings("HTML"),
                        _node_idx_in_strings("BODY"),
                        _node_idx_in_strings("A"),
                        _node_idx_in_strings("DIV"),
                        _node_idx_in_strings("FORM"),
                        _node_idx_in_strings("BUTTON"),
                        _node_idx_in_strings("P")],
        "backendNodeId": [10, 20, 30, 40, 50, 60, 70],
        "attributes": [
            [],                                                          # html
            [],                                                          # body
            [_node_idx_in_strings("href"), _node_idx_in_strings("https://example.com"),
             _node_idx_in_strings("class"), _node_idx_in_strings("cta")],   # a
            [_node_idx_in_strings("id"), _node_idx_in_strings("main")],     # div
            [_node_idx_in_strings("action"), _node_idx_in_strings("/checkout")],  # form
            [_node_idx_in_strings("type"), _node_idx_in_strings("submit")], # button
            [],                                                          # p
        ],
    }

    # Layout: assume nodes 2 (a) and 5 (button) have layout entries.
    # Each layout style array has one string-index per computed style name.
    layout = {
        "nodeIndex": [2, 5],
        "styles": [
            [_node_idx_in_strings("block"),
             _node_idx_in_strings("visible"),
             _node_idx_in_strings("auto")],
            [_node_idx_in_strings("block"),
             _node_idx_in_strings("visible"),
             _node_idx_in_strings("auto")],
        ],
    }

    return {
        "documents": [{"nodes": nodes, "layout": layout}],
        "strings": _STRINGS,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_builder_produces_an_entry_per_element():
    specs = build_specs_from_snapshot(_make_snapshot())
    assert set(specs.keys()) == {10, 20, 30, 40, 50, 60, 70}


def test_anchor_attributes_decoded():
    specs = build_specs_from_snapshot(_make_snapshot())
    a_spec = specs[30]
    assert a_spec.tag == "a"
    assert a_spec.attrs["href"] == "https://example.com"
    assert a_spec.attrs["class"] == "cta"
    assert a_spec.role is None


def test_form_attributes_decoded():
    specs = build_specs_from_snapshot(_make_snapshot())
    form_spec = specs[50]
    assert form_spec.tag == "form"
    assert form_spec.attrs["action"] == "/checkout"


def test_button_ancestors_chain_up_through_form_and_body():
    specs = build_specs_from_snapshot(_make_snapshot())
    btn_spec = specs[60]
    ancestor_tags = [a.tag for a in btn_spec.ancestors]
    assert ancestor_tags == ["form", "div", "body", "html"]
    # The form ancestor should carry its `action` attribute for composition rules
    # like `_ancestor_form` in forms.py to read.
    form_anc = btn_spec.ancestors[0]
    assert form_anc.attrs["action"] == "/checkout"


def test_anchor_ancestors_are_lightweight():
    """Each ancestor's own `ancestors` field is empty — the chain is flat,
    not recursively populated, matching what composition reads."""
    specs = build_specs_from_snapshot(_make_snapshot())
    a_spec = specs[30]
    for anc in a_spec.ancestors:
        assert anc.ancestors == []


def test_computed_styles_attached_for_layout_nodes():
    specs = build_specs_from_snapshot(_make_snapshot())
    a_spec = specs[30]   # has layout entry 0
    btn_spec = specs[60] # has layout entry 1
    assert a_spec.computed_style_flags == {
        "display": "block", "visibility": "visible", "pointer-events": "auto",
    }
    assert btn_spec.computed_style_flags["display"] == "block"


def test_nodes_without_layout_entry_get_empty_styles():
    """The `html` element wasn't in layout.nodeIndex — should have empty flags."""
    specs = build_specs_from_snapshot(_make_snapshot())
    html_spec = specs[10]
    assert html_spec.computed_style_flags == {}


def test_tag_names_normalize_to_lowercase():
    """DOMSnapshot returns uppercase tags; ElementSpec must be lowercase
    so the classifier's tag predicates (which test `s.tag == 'a'`) match."""
    specs = build_specs_from_snapshot(_make_snapshot())
    assert all(spec.tag == spec.tag.lower() for spec in specs.values())


def test_role_attribute_promoted_to_spec_field():
    snapshot = _make_snapshot()
    snapshot["strings"] = list(snapshot["strings"]) + ["role", "button"]
    role_idx = snapshot["strings"].index("role")
    button_idx = snapshot["strings"].index("button")
    # Add role="button" to the div (index 3).
    snapshot["documents"][0]["nodes"]["attributes"][3] = [
        snapshot["strings"].index("id"),
        snapshot["strings"].index("main"),
        role_idx, button_idx,
    ]
    specs = build_specs_from_snapshot(snapshot)
    div_spec = specs[40]
    assert div_spec.role == "button"


def test_multiple_documents_aggregate():
    """Iframes appear as additional documents in the same snapshot."""
    snap = _make_snapshot()
    # Add a second document with one element.
    snap["documents"].append({
        "nodes": {
            "parentIndex":   [-1],
            "nodeType":      [NODE_TYPE_ELEMENT],
            "nodeName":      [_node_idx_in_strings("HTML")],
            "backendNodeId": [99],
            "attributes":    [[]],
        },
        "layout": {"nodeIndex": [], "styles": []},
    })
    specs = build_specs_from_snapshot(snap)
    assert 99 in specs


def test_computed_style_names_list_matches_classifier_use():
    """spec_builder advertises which computed styles it captures. The
    classifier's composition.py reads exactly these three; keep them in sync."""
    assert COMPUTED_STYLE_NAMES == ["display", "visibility", "pointer-events"]


# ── build_dom_records: text-node capture ─────────────────────────────────────

def _text_snapshot() -> dict:
    """Synthetic snapshot exercising direct-text-child semantics:

        html
          body
            p          "Hello "
              b        "world"
            (p direct continues:) "!"
            script     "console.log(1)"
            div        "   "          (whitespace-only — should be elided)
            span                       (no children)
    """
    strings = [
        "HTML",            # 0
        "BODY",            # 1
        "P",               # 2
        "B",               # 3
        "SCRIPT",          # 4
        "DIV",             # 5
        "SPAN",            # 6
        "Hello ",          # 7  — p's first text child
        "world",           # 8  — b's text child
        "!",               # 9  — p's second text child
        "console.log(1)",  # 10 — script body
        "   ",             # 11 — div's whitespace-only text child
        "https://example.test/",  # 12 — documentURL
    ]

    def six(name): return strings.index(name)

    # Layout: node_index → which DOM node, parent_index → its DOM parent, etc.
    # Indices: 0=html, 1=body, 2=p, 3=text("Hello "), 4=b, 5=text("world"),
    #          6=text("!"), 7=script, 8=text("console.log(1)"),
    #          9=div, 10=text("   "), 11=span
    nodes = {
        "parentIndex":   [-1, 0,  1,  2,  2,  4,  2,  1,  7,  1, 9, 1],
        "nodeType":      [
            NODE_TYPE_ELEMENT, NODE_TYPE_ELEMENT, NODE_TYPE_ELEMENT,
            NODE_TYPE_TEXT,    NODE_TYPE_ELEMENT, NODE_TYPE_TEXT,
            NODE_TYPE_TEXT,    NODE_TYPE_ELEMENT, NODE_TYPE_TEXT,
            NODE_TYPE_ELEMENT, NODE_TYPE_TEXT,    NODE_TYPE_ELEMENT,
        ],
        "nodeName":      [
            six("HTML"), six("BODY"), six("P"), -1, six("B"), -1, -1,
            six("SCRIPT"), -1, six("DIV"), -1, six("SPAN"),
        ],
        "nodeValue":     [-1, -1, -1, six("Hello "), -1, six("world"),
                          six("!"), -1, six("console.log(1)"),
                          -1, six("   "), -1],
        "backendNodeId": [10, 20, 30, 31, 40, 41, 32, 50, 51, 60, 61, 70],
        "attributes":    [[]] * 12,
    }

    return {
        "documents": [{
            "nodes": nodes,
            "layout": {"nodeIndex": [], "styles": []},
            "documentURL": six("https://example.test/"),
        }],
        "strings": strings,
    }


def test_dom_records_capture_direct_text_only():
    """`<p>Hello <b>world</b>!</p>` — the <p>'s text is the join of its
    direct text-node children only; the <b>'s text lives on its own record."""
    records = build_dom_records(_text_snapshot())
    by_bni = {r["bni"]: r for r in records}

    # p has two direct text-node children separated by a <b>: "Hello " and "!".
    assert by_bni[30]["text"] == "Hello !"
    # b has one direct text child.
    assert by_bni[40]["text"] == "world"


def test_dom_records_capture_script_body():
    """Inline <script> bodies are text children — captured the same way."""
    records = build_dom_records(_text_snapshot())
    by_bni = {r["bni"]: r for r in records}
    assert by_bni[50]["text"] == "console.log(1)"


def test_dom_records_elide_whitespace_only_text():
    """Pure-whitespace text children (HTML formatting noise) are skipped —
    the `text` key isn't emitted at all."""
    records = build_dom_records(_text_snapshot())
    by_bni = {r["bni"]: r for r in records}
    assert "text" not in by_bni[60]   # the div with "   "


def test_dom_records_omit_text_when_no_text_children():
    """Elements with no text-node children get no `text` key (not empty string)."""
    records = build_dom_records(_text_snapshot())
    by_bni = {r["bni"]: r for r in records}
    assert "text" not in by_bni[70]   # the span
    assert "text" not in by_bni[10]   # html — its only child is body
    assert "text" not in by_bni[20]   # body — children are all elements


def test_dom_records_text_preserved_verbatim():
    """No stripping or whitespace collapsing — text-bearing fields are
    captured byte-for-byte so PI payloads with deliberate whitespace
    (zero-width, leading/trailing) survive."""
    records = build_dom_records(_text_snapshot())
    by_bni = {r["bni"]: r for r in records}
    # "Hello " has a trailing space — preserved.
    assert by_bni[30]["text"] == "Hello !"   # "Hello " + "!"


def test_dom_records_text_across_multiple_documents():
    """Iframes (additional documents) capture text independently."""
    snap = _text_snapshot()
    strings = list(snap["strings"])
    strings.append("iframe body text")
    inner_idx = len(strings) - 1
    strings.append("https://3p.example/iframe")
    url_idx = len(strings) - 1
    strings.append("DIV")
    div_idx = len(strings) - 1
    snap["strings"] = strings
    snap["documents"].append({
        "nodes": {
            "parentIndex":   [-1, 0],
            "nodeType":      [NODE_TYPE_ELEMENT, NODE_TYPE_TEXT],
            "nodeName":      [div_idx, -1],
            "nodeValue":     [-1, inner_idx],
            "backendNodeId": [900, 901],
            "attributes":    [[], []],
        },
        "layout": {"nodeIndex": [], "styles": []},
        "documentURL": url_idx,
    })
    records = build_dom_records(snap)
    by_bni = {r["bni"]: r for r in records}
    assert by_bni[900]["text"] == "iframe body text"
    assert by_bni[900]["doc_url"] == "https://3p.example/iframe"
