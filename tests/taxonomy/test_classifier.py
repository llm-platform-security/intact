"""Parametrized rule-match tests for the base classifier.

Each row asserts that `classify_base(spec)` produces a classification whose
source_rule matches and whose effective Authority / observable Effects /
exposed Channels contain the expected sets.

Composition is exercised in test_composition.py.
"""

import pytest

from intact.gentree.taxonomy import (
    AgentView, Authority, Channel, Effect, ElementSpec,
)
from intact.gentree.taxonomy.classifier import classify_base


# ── Static / phrasing ───────────────────────────────────────────────────────

def test_p_is_static_base():
    cls = classify_base(ElementSpec(tag="p"))
    assert cls.source_rule == "static:base"
    assert cls.authority.effective == set()
    assert cls.effects.observable == set()
    assert Channel.BODY_TEXT in cls.exposure.channels


def test_span_is_static_base():
    cls = classify_base(ElementSpec(tag="span"))
    assert cls.source_rule == "static:base"
    assert cls.authority.effective == set()


@pytest.mark.parametrize("tag", [
    "p", "span", "div", "h1", "h6", "em", "strong", "blockquote",
    "section", "article", "main", "nav", "header", "footer", "aside",
    "ul", "ol", "li", "dl", "dt", "dd",
])
def test_text_containers_match_static_base(tag):
    cls = classify_base(ElementSpec(tag=tag))
    assert cls.source_rule == "static:base"
    assert Channel.BODY_TEXT in cls.exposure.channels


def test_static_with_onclick_gains_click_and_execute():
    cls = classify_base(ElementSpec(tag="div", attrs={"onclick": "alert(1)"}))
    assert cls.source_rule == "static:with-event-handler"
    assert Authority.CLICK in cls.authority.direct
    assert Effect.EXECUTE in cls.effects.observable
    assert Channel.EVENT_HANDLER_SOURCE in cls.exposure.channels


def test_static_contenteditable_gains_type():
    cls = classify_base(ElementSpec(tag="div", attrs={"contenteditable": "true"}))
    assert cls.source_rule == "static:contenteditable"
    assert Authority.TYPE in cls.authority.direct
    assert Authority.PASTE in cls.authority.direct
    assert Effect.DOM_MUTATE in cls.effects.observable


def test_static_contenteditable_empty_value_counts_as_true():
    """`<div contenteditable>` is equivalent to `contenteditable="true"`."""
    cls = classify_base(ElementSpec(tag="div", attrs={"contenteditable": ""}))
    assert cls.source_rule == "static:contenteditable"


def test_static_with_tabindex_gains_focus():
    cls = classify_base(ElementSpec(tag="p", attrs={"tabindex": "0"}))
    assert cls.source_rule == "static:tabindex-focusable"
    assert Authority.FOCUS in cls.authority.direct


def test_static_negative_tabindex_does_not_match_focusable_rule():
    """tabindex=-1 means focusable-by-script-only, not by tab navigation."""
    cls = classify_base(ElementSpec(tag="p", attrs={"tabindex": "-1"}))
    assert cls.source_rule == "static:base"


# ── Anchors ────────────────────────────────────────────────────────────────

def test_a_no_href_is_inert():
    cls = classify_base(ElementSpec(tag="a"))
    assert cls.source_rule == "anchor:no-href"
    assert cls.authority.effective == set()


def test_a_with_href_is_clickable_navigable():
    cls = classify_base(ElementSpec(tag="a", attrs={"href": "https://example.com"}))
    assert cls.source_rule == "anchor:href"
    assert {Authority.CLICK, Authority.FOCUS, Authority.HOVER}.issubset(
        cls.authority.direct
    )
    assert {Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}.issubset(cls.effects.observable)
    assert {Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME, Channel.TITLE_TOOLTIP}.issubset(
        cls.exposure.channels
    )


def test_a_javascript_scheme_gains_execute():
    cls = classify_base(ElementSpec(
        tag="a",
        attrs={"href": "javascript:doThing()"},
    ))
    assert cls.source_rule == "anchor:javascript-scheme"
    assert Effect.EXECUTE in cls.effects.observable
    assert Channel.EVENT_HANDLER_SOURCE in cls.exposure.channels


def test_a_target_blank_adds_popup():
    cls = classify_base(ElementSpec(
        tag="a",
        attrs={"href": "https://example.com", "target": "_blank"},
    ))
    assert cls.source_rule == "anchor:target-blank"
    assert Authority.POPUP in cls.authority.direct


def test_a_download_does_not_navigate_frame():
    """The `download` attribute makes the browser fetch the resource but stay on the page."""
    cls = classify_base(ElementSpec(
        tag="a",
        attrs={"href": "/file.pdf", "download": ""},
    ))
    assert cls.source_rule == "anchor:download"
    assert Effect.SEND_REQUEST in cls.effects.observable
    assert Effect.NAVIGATE_FRAME not in cls.effects.observable


def test_a_mailto_external_handler_effect():
    """mailto:/tel:/sms: hand off to an OS handler — no in-browser network or
    navigation, but EXTERNAL_HANDLER (the URL can carry data off-browser)."""
    cls = classify_base(ElementSpec(tag="a", attrs={"href": "mailto:a@b.com"}))
    assert cls.source_rule == "anchor:mailto-tel-sms"
    assert cls.effects.observable == {Effect.EXTERNAL_HANDLER}
    assert Effect.SEND_REQUEST not in cls.effects.observable
    assert Effect.NAVIGATE_FRAME not in cls.effects.observable


def test_area_with_href_classifies():
    cls = classify_base(ElementSpec(tag="area", attrs={"href": "/dest"}))
    assert cls.source_rule == "anchor:area-href"
    assert Authority.CLICK in cls.authority.direct
    assert Channel.ALT in cls.exposure.channels


# ── Forms ──────────────────────────────────────────────────────────────────

def test_form_root_classifies():
    cls = classify_base(ElementSpec(
        tag="form",
        attrs={"action": "/submit", "method": "post"},
    ))
    assert cls.source_rule == "form:root"
    assert cls.authority.direct == set()
    assert {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}.issubset(cls.effects.observable)


def test_form_observable_effects_are_independent_of_action_url():
    """No URL-pattern heuristics: /checkout, /login, /contact all classify identically."""
    for action in ("/checkout/place-order", "/login", "/contact", "/anything"):
        cls = classify_base(ElementSpec(
            tag="form",
            attrs={"action": action, "method": "post"},
        ))
        assert cls.source_rule == "form:root"
        assert cls.effects.observable == {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}


# Input variants --------------------------------------------------------------

@pytest.mark.parametrize("itype", list({
    "text", "email", "search", "tel", "url", "number", "date",
}))
def test_text_inputs(itype):
    cls = classify_base(ElementSpec(tag="input", attrs={"type": itype}))
    assert cls.source_rule == "input:text-family"
    assert Authority.TYPE in cls.authority.direct
    assert Authority.FOCUS in cls.authority.direct
    assert Channel.PLACEHOLDER in cls.exposure.channels


def test_input_password_is_distinguished():
    cls = classify_base(ElementSpec(tag="input", attrs={"type": "password"}))
    assert cls.source_rule == "input:password"
    assert Authority.TYPE in cls.authority.direct
    # Value channel deliberately NOT in exposure — sensitive content.
    assert Channel.VALUE not in cls.exposure.channels


def test_input_checkbox_gains_change_value():
    cls = classify_base(ElementSpec(tag="input", attrs={"type": "checkbox"}))
    assert cls.source_rule == "input:checkbox-radio"
    assert Authority.CLICK in cls.authority.direct
    assert Authority.CHANGE_VALUE in cls.authority.direct


def test_input_submit_has_submit_effects():
    form = ElementSpec(tag="form", attrs={"action": "/place-order", "method": "post"})
    btn = ElementSpec(tag="input", attrs={"type": "submit"}, ancestors=[form])
    cls = classify_base(btn)
    assert cls.source_rule == "input:submit"
    assert Authority.CLICK in cls.authority.direct
    assert cls.effects.observable == {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}


def test_input_file_gains_upload():
    cls = classify_base(ElementSpec(tag="input", attrs={"type": "file"}))
    assert cls.source_rule == "input:file"
    assert Authority.UPLOAD in cls.authority.direct


def test_input_hidden_is_dom_text_only():
    cls = classify_base(ElementSpec(tag="input", attrs={"type": "hidden"}))
    assert cls.source_rule == "input:hidden"
    assert cls.authority.effective == set()
    # Hidden input is invisible to AX but visible to DOM-text scrapers.
    assert AgentView.DOM_TEXT in cls.exposure.visible_to
    assert AgentView.AX_TREE not in cls.exposure.visible_to


def test_input_image_fetches_and_submits():
    form = ElementSpec(tag="form", attrs={"action": "/submit", "method": "post"})
    el = ElementSpec(tag="input", attrs={"type": "image", "src": "/btn.png"}, ancestors=[form])
    cls = classify_base(el)
    assert cls.source_rule == "input:image"
    assert Effect.FETCH in cls.effects.observable
    assert Effect.SEND_REQUEST in cls.effects.observable


# textarea / select / option --------------------------------------------------

def test_textarea_caps():
    cls = classify_base(ElementSpec(tag="textarea"))
    assert cls.source_rule == "textarea"
    assert {Authority.TYPE, Authority.FOCUS, Authority.PASTE}.issubset(cls.authority.direct)


def test_select_caps():
    cls = classify_base(ElementSpec(tag="select"))
    assert cls.source_rule == "select"
    assert {Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE}.issubset(
        cls.authority.direct
    )
    assert Effect.CHOOSE in cls.effects.observable
    assert Channel.OPTION_TEXT in cls.exposure.channels


def test_option_exposes_option_text():
    cls = classify_base(ElementSpec(tag="option", attrs={"value": "us"}))
    assert cls.source_rule == "option"
    assert cls.authority.effective == set()
    assert Channel.OPTION_TEXT in cls.exposure.channels


# Buttons ---------------------------------------------------------------------

def test_button_standalone_no_form():
    cls = classify_base(ElementSpec(tag="button"))
    assert cls.source_rule == "button:standalone"
    assert Authority.CLICK in cls.authority.direct
    assert Effect.SUBMIT not in cls.effects.observable


def test_button_inside_form_default_submit():
    form = ElementSpec(tag="form", attrs={"action": "/x", "method": "post"})
    btn = ElementSpec(tag="button", ancestors=[form])
    cls = classify_base(btn)
    assert cls.source_rule == "button:in-form"
    assert Authority.CLICK in cls.authority.direct
    assert Effect.SUBMIT in cls.effects.observable


def test_button_type_button_inside_form_does_not_submit():
    form = ElementSpec(tag="form", attrs={"action": "/x"})
    btn = ElementSpec(tag="button", attrs={"type": "button"}, ancestors=[form])
    cls = classify_base(btn)
    assert cls.source_rule == "button:type-button-in-form"
    assert Effect.SUBMIT not in cls.effects.observable


def test_button_type_reset_restores_control_state():
    cls = classify_base(ElementSpec(tag="button", attrs={"type": "reset"}))
    assert cls.source_rule == "button:reset"
    assert Effect.DOM_MUTATE in cls.effects.observable
    assert Effect.SUBMIT not in cls.effects.observable


def test_button_in_form_has_submit_observable_effects():
    form = ElementSpec(tag="form", attrs={"action": "/place-order", "method": "post"})
    btn = ElementSpec(tag="button", ancestors=[form])
    cls = classify_base(btn)
    assert cls.effects.observable == {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}


# Labels ----------------------------------------------------------------------

def test_label_with_for_attribute():
    cls = classify_base(ElementSpec(tag="label", attrs={"for": "email-input"}))
    assert cls.source_rule == "label:for-reference"
    assert Authority.CLICK in cls.authority.direct


def test_label_without_for_is_plain():
    cls = classify_base(ElementSpec(tag="label"))
    assert cls.source_rule == "label:plain"
    assert Authority.CLICK in cls.authority.direct


# ── Fallback ──────────────────────────────────────────────────────────────

def test_unknown_tag_returns_empty_fallback():
    """A non-hyphenated tag with no rule match falls through to the empty fallback.
    Hyphenated tags would match the custom-element rule, so we use a plain name."""
    cls = classify_base(ElementSpec(tag="madeupsingleworditem"))
    assert cls.source_rule == "fallback:unknown"
    assert cls.authority.effective == set()
    assert cls.effects.observable == set()


def test_hyphenated_tag_is_custom_element():
    """Custom elements (hyphenated tags) get the custom-element rule, not fallback."""
    cls = classify_base(ElementSpec(tag="my-fancy-widget"))
    assert cls.source_rule == "custom:element-unknown"
    assert cls.authority.effective == set()
    # Custom elements still get body-text exposure so the agent can read content.
    assert Channel.BODY_TEXT in cls.exposure.channels


def test_specificity_resolves_tiebreaks():
    """Both 'anchor:href' and 'anchor:target-blank' match an a[href][target=_blank];
    the higher-specificity rule wins."""
    spec = ElementSpec(tag="a", attrs={"href": "/x", "target": "_blank"})
    cls = classify_base(spec)
    assert cls.source_rule == "anchor:target-blank"
