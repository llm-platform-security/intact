"""Regression cases for separating activation from potential UI operations."""

import pytest

from intact.gentree.taxonomy import Authority, Effect, ElementSpec
from intact.gentree.taxonomy.classifier import classify
from intact.gentree.taxonomy.enums import LEGACY_TAXONOMY_VERSION, TAXONOMY_VERSION


def test_operation_labels_exist_only_on_effect_axis():
    moved = {"choose", "submit", "navigate"}
    assert moved.isdisjoint({item.value for item in Authority})
    assert moved <= {item.value for item in Effect}
    assert TAXONOMY_VERSION != LEGACY_TAXONOMY_VERSION


def test_form_is_a_submission_context_not_a_click_target():
    cls = classify(ElementSpec(tag="form", attrs={"action": "/send", "method": "post"}))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}


@pytest.mark.parametrize("attrs", [{}, {"multiple": ""}, {"size": "4"}])
def test_select_exposes_activation_and_value_change_with_potential_choice(attrs):
    cls = classify(ElementSpec(tag="select", attrs=attrs))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE}
    assert cls.effects.observable == {Effect.CHOOSE, Effect.DOM_MUTATE}


@pytest.mark.parametrize("tag,attrs,submits", [
    ("button", {}, True),
    ("button", {"type": "submit"}, True),
    ("button", {"type": "button"}, False),
    ("button", {"type": "reset"}, False),
    ("input", {"type": "submit"}, True),
    ("input", {"type": "image", "src": "/send.png"}, True),
    ("input", {"type": "button"}, False),
    ("input", {"type": "reset"}, False),
])
def test_submit_effect_follows_control_subtype_without_changing_activation(tag, attrs, submits):
    cls = classify(ElementSpec(tag=tag, attrs=attrs, ancestors=[ElementSpec(tag="form")]))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS}
    assert (Effect.SUBMIT in cls.effects.observable) is submits
    assert (Effect.SEND_REQUEST in cls.effects.observable) is submits


@pytest.mark.parametrize("input_type", ["text", "email", "search", "password"])
def test_implicit_submit_does_not_turn_text_entry_into_click_or_guaranteed_request(input_type):
    field = ElementSpec(tag="input", attrs={"type": input_type})
    plain = classify(field)
    associated = classify(ElementSpec(
        tag="input", attrs=field.attrs, ancestors=[ElementSpec(tag="form")],
    ))
    assert associated.authority.effective == plain.authority.effective == {
        Authority.TYPE, Authority.FOCUS,
    }
    assert plain.effects.observable == {Effect.DOM_MUTATE}
    # SUBMIT is a conditional implicit operation (e.g. Enter), not the result
    # of ordinary typing.
    assert associated.effects.observable == {Effect.DOM_MUTATE, Effect.SUBMIT}


@pytest.mark.parametrize("tag,attrs,navigates", [
    ("a", {"href": "/details"}, True),
    ("a", {"href": "#details"}, True),
    ("a", {"href": "/details", "target": "_blank"}, True),
    ("area", {"href": "/details"}, True),
    ("a", {"href": "/details", "download": ""}, False),
    ("a", {"href": "javascript:showDetails()"}, False),
    ("a", {"href": "mailto:hello@example.com"}, False),
    ("button", {}, False),
])
def test_navigation_effect_preserves_link_subtypes(tag, attrs, navigates):
    cls = classify(ElementSpec(tag=tag, attrs=attrs))
    assert Authority.CLICK in cls.authority.effective
    assert (Effect.NAVIGATE in cls.effects.observable) is navigates


@pytest.mark.parametrize("attrs", [
    {"href": "/details"},
    {"href": "/details", "target": "_blank"},
    {"href": "/details", "download": ""},
    {"href": "javascript:showDetails()"},
    {"href": "mailto:hello@example.com"},
])
def test_wrapped_content_inherits_same_operation_effects_as_anchor(attrs):
    anchor = ElementSpec(tag="a", attrs=attrs)
    direct = classify(anchor)
    child = classify(ElementSpec(tag="span", ancestors=[anchor]))
    assert child.authority.inherited == direct.authority.direct
    assert child.effects.observable == direct.effects.observable


@pytest.mark.parametrize("role,navigates", [("link", True), ("menuitem", False)])
def test_role_activation_and_navigation_remain_separate(role, navigates):
    cls = classify(ElementSpec(tag="span", attrs={"role": role}))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS}
    assert (Effect.NAVIGATE in cls.effects.observable) is navigates


@pytest.mark.parametrize("sandbox,submits", [("", False), ("allow-forms", True)])
def test_sandbox_blocks_submission_operation_without_blocking_click(sandbox, submits):
    iframe = ElementSpec(tag="iframe", attrs={"sandbox": sandbox})
    form = ElementSpec(tag="form")
    cls = classify(ElementSpec(tag="button", ancestors=[form, iframe]))
    assert Authority.CLICK in cls.authority.effective
    assert (Effect.SUBMIT in cls.effects.observable) is submits
    assert not any(note.startswith("error:") for note in cls.composition_notes)


@pytest.mark.parametrize("sandbox,navigates", [("", False), ("allow-top-navigation", True)])
def test_sandbox_preserves_existing_navigation_gate_on_effect_axis(sandbox, navigates):
    iframe = ElementSpec(tag="iframe", attrs={"sandbox": sandbox})
    cls = classify(ElementSpec(tag="a", attrs={"href": "/details"}, ancestors=[iframe]))
    assert Authority.CLICK in cls.authority.effective
    assert (Effect.NAVIGATE in cls.effects.observable) is navigates
    assert not any(note.startswith("error:") for note in cls.composition_notes)


@pytest.mark.parametrize("attrs,ancestor", [
    ({"disabled": ""}, None),
    ({"aria-disabled": "true"}, None),
    ({"inert": ""}, None),
    ({}, ElementSpec(tag="div", attrs={"inert": ""})),
])
def test_select_activation_and_value_change_respect_existing_blocking(attrs, ancestor):
    cls = classify(ElementSpec(tag="select", attrs=attrs, ancestors=[ancestor] if ancestor else []))
    assert cls.authority.effective == set()
    assert {Authority.CLICK, Authority.CHANGE_VALUE} <= cls.authority.blocked
    # Existing static Effects remain potential semantics of this blocked control.
    assert cls.effects.observable == {Effect.CHOOSE, Effect.DOM_MUTATE}


def test_automatic_meta_refresh_keeps_existing_downstream_only_mapping():
    cls = classify(ElementSpec(tag="meta", attrs={"http-equiv": "refresh", "content": "0;url=/next"}))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}
