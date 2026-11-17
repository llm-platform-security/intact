"""Composition pass tests.

Each test exercises one composition rule firing (or NOT firing) and verifies
the resulting effective authority + visible_to set.
"""

from intact.gentree.taxonomy import (
    AgentView, Authority, Channel, Effect, ElementSpec,
)
from intact.gentree.taxonomy.classifier import classify


# ── Wrapping anchor ──────────────────────────────────────────────────────────

def test_img_inside_anchor_inherits_click_navigate():
    a = ElementSpec(tag="a", attrs={"href": "https://example.com"})
    # NOTE: use a known static tag whose base classification is no-authority,
    # so that the test isolates the wrapping composition rule itself.
    img = ElementSpec(tag="span", ancestors=[a])
    cls = classify(img)
    assert Authority.CLICK in cls.authority.effective
    assert Effect.NAVIGATE in cls.effects.observable
    assert any(note.startswith("wrapping-anchor") for note in cls.composition_notes)


def test_no_wrapping_anchor_does_not_inherit():
    cls = classify(ElementSpec(tag="span", ancestors=[ElementSpec(tag="div")]))
    assert Authority.CLICK not in cls.authority.effective
    assert all(not note.startswith("wrapping-anchor") for note in cls.composition_notes)


def test_a_inside_a_does_not_self_inherit():
    """An <a> inside another <a> (illegal HTML but happens): the inner one's
    classification already has the caps; composition shouldn't double-count."""
    outer = ElementSpec(tag="a", attrs={"href": "/x"})
    inner = ElementSpec(tag="a", attrs={"href": "/y"}, ancestors=[outer])
    cls = classify(inner)
    assert all(not note.startswith("wrapping-anchor") for note in cls.composition_notes)


# ── Inherited contenteditable ───────────────────────────────────────────────

def test_inherited_contenteditable_adds_type():
    editor = ElementSpec(tag="div", attrs={"contenteditable": "true"})
    inner = ElementSpec(tag="span", ancestors=[editor])
    cls = classify(inner)
    assert Authority.TYPE in cls.authority.effective
    assert "inherited-contenteditable" in cls.composition_notes


def test_inherited_contenteditable_false_does_not_add():
    not_editor = ElementSpec(tag="div", attrs={"contenteditable": "false"})
    inner = ElementSpec(tag="span", ancestors=[not_editor])
    cls = classify(inner)
    assert Authority.TYPE not in cls.authority.effective


# ── tabindex ────────────────────────────────────────────────────────────────

def test_tabindex_zero_adds_focus():
    cls = classify(ElementSpec(tag="div", attrs={"tabindex": "0"}))
    assert Authority.FOCUS in cls.authority.effective


def test_tabindex_minus_one_blocks_focus():
    cls = classify(ElementSpec(tag="div", attrs={"tabindex": "-1"}))
    assert Authority.FOCUS not in cls.authority.effective


def test_tabindex_minus_one_blocks_even_role_button_focus():
    """role=button adds {click, focus}, but tabindex=-1 should still block FOCUS."""
    cls = classify(ElementSpec(
        tag="div",
        attrs={"role": "button", "tabindex": "-1"},
    ))
    # click is intact, focus removed.
    assert Authority.CLICK in cls.authority.effective
    assert Authority.FOCUS not in cls.authority.effective


# ── role remap ───────────────────────────────────────────────────────────────

def test_role_button_on_div():
    cls = classify(ElementSpec(tag="div", attrs={"role": "button"}))
    assert Authority.CLICK in cls.authority.effective
    assert Authority.FOCUS in cls.authority.effective
    assert "role=button" in cls.composition_notes


def test_role_link_on_span_adds_navigate():
    cls = classify(ElementSpec(tag="span", attrs={"role": "link"}))
    assert Authority.CLICK in cls.authority.effective
    assert Effect.NAVIGATE in cls.effects.observable


def test_unknown_role_is_ignored():
    cls = classify(ElementSpec(tag="div", attrs={"role": "fancy-thing"}))
    # No effective caps from an unrecognized role; base div has none.
    assert cls.authority.effective == set()


# ── Sandbox iframe ──────────────────────────────────────────────────────────

def test_sandboxed_iframe_blocks_submit_in_descendant_form():
    iframe = ElementSpec(tag="iframe", attrs={"sandbox": ""})
    form = ElementSpec(tag="form", attrs={"action": "/x"}, ancestors=[iframe])
    cls = classify(form)
    # The form's submission operation is blocked; it is not an activation control.
    assert cls.authority.direct == set()
    assert Effect.SUBMIT not in cls.effects.observable
    assert any("iframe-sandbox" in n for n in cls.composition_notes)


def test_sandbox_allow_forms_re_enables_submit():
    iframe = ElementSpec(tag="iframe", attrs={"sandbox": "allow-forms"})
    form = ElementSpec(tag="form", attrs={"action": "/x"}, ancestors=[iframe])
    cls = classify(form)
    assert Effect.SUBMIT in cls.effects.observable


def test_sandbox_allow_popups_re_enables_popup():
    iframe = ElementSpec(tag="iframe", attrs={"sandbox": "allow-popups"})
    a = ElementSpec(
        tag="a",
        attrs={"href": "/x", "target": "_blank"},
        ancestors=[iframe],
    )
    cls = classify(a)
    assert Authority.POPUP in cls.authority.effective


# ── pointer-events: none ────────────────────────────────────────────────────

def test_pointer_events_none_blocks_click_and_hover():
    cls = classify(ElementSpec(
        tag="a",
        attrs={"href": "/x"},
        computed_style_flags={"pointer-events": "none"},
    ))
    # Pointer activation is blocked; keyboard focus/navigation remain possible.
    assert Authority.CLICK not in cls.authority.effective
    assert Authority.HOVER not in cls.authority.effective
    assert Authority.FOCUS in cls.authority.effective
    assert Effect.NAVIGATE in cls.effects.observable


# ── display:none / visibility:hidden / aria-hidden ──────────────────────────

def test_display_none_drops_from_ax_tree():
    cls = classify(ElementSpec(
        tag="p",
        computed_style_flags={"display": "none"},
    ))
    assert AgentView.AX_TREE not in cls.exposure.visible_to
    # Still visible to DOM_TEXT scrape.
    assert AgentView.DOM_TEXT in cls.exposure.visible_to


def test_visibility_hidden_drops_from_ax_tree():
    cls = classify(ElementSpec(
        tag="p",
        computed_style_flags={"visibility": "hidden"},
    ))
    assert AgentView.AX_TREE not in cls.exposure.visible_to


def test_aria_hidden_drops_from_ax_tree():
    cls = classify(ElementSpec(tag="p", attrs={"aria-hidden": "true"}))
    assert AgentView.AX_TREE not in cls.exposure.visible_to


# ── disabled / inert ────────────────────────────────────────────────────────

def test_disabled_button_blocks_all_authority():
    form = ElementSpec(tag="form", attrs={"action": "/x", "method": "post"})
    btn = ElementSpec(
        tag="button",
        attrs={"disabled": ""},
        ancestors=[form],
    )
    cls = classify(btn)
    assert cls.authority.effective == set()
    assert "disabled" in cls.composition_notes


def test_aria_disabled_blocks_all_authority():
    cls = classify(ElementSpec(
        tag="a",
        attrs={"href": "/x", "aria-disabled": "true"},
    ))
    assert cls.authority.effective == set()


def test_inert_blocks_authority_and_drops_ax():
    cls = classify(ElementSpec(
        tag="a",
        attrs={"href": "/x", "inert": ""},
    ))
    assert cls.authority.effective == set()
    assert AgentView.AX_TREE not in cls.exposure.visible_to


def test_ancestor_inert_blocks_descendant():
    inert_container = ElementSpec(tag="div", attrs={"inert": ""})
    btn = ElementSpec(tag="button", ancestors=[inert_container])
    cls = classify(btn)
    assert cls.authority.effective == set()
    assert "inert:ancestor" in cls.composition_notes
