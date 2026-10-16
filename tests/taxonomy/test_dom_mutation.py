"""DOM content and represented control-state effects."""

import pytest

from intact.gentree.taxonomy import Authority, Effect, ElementSpec
from intact.gentree.taxonomy.classifier import classify


@pytest.mark.parametrize("input_type", [
    "text", "email", "search", "tel", "url", "password", "number", "date",
    "datetime-local", "month", "week", "time",
])
def test_native_input_values_have_dom_mutation(input_type):
    cls = classify(ElementSpec(tag="input", attrs={"type": input_type}))
    assert Authority.TYPE in cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


@pytest.mark.parametrize(("tag", "attrs", "authority"), [
    ("textarea", {}, Authority.TYPE),
    ("input", {"type": "checkbox"}, Authority.CHANGE_VALUE),
    ("input", {"type": "radio"}, Authority.CHANGE_VALUE),
    ("input", {"type": "range"}, Authority.CHANGE_VALUE),
    ("input", {"type": "color"}, Authority.CHANGE_VALUE),
    ("select", {}, Authority.CHANGE_VALUE),
    ("select", {"multiple": ""}, Authority.CHANGE_VALUE),
    ("label", {"for": "email"}, Authority.CLICK),
])
def test_control_state_and_label_activation_have_dom_mutation(tag, attrs, authority):
    cls = classify(ElementSpec(tag=tag, attrs=attrs))
    assert authority in cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


@pytest.mark.parametrize(("tag", "attrs", "authority"), [
    ("input", {"type": "file"}, Authority.UPLOAD),
    ("div", {"tabindex": "0"}, Authority.FOCUS),
])
def test_file_selection_and_direct_focus_keep_previous_effects(tag, attrs, authority):
    cls = classify(ElementSpec(tag=tag, attrs=attrs))
    assert authority in cls.authority.effective
    assert Effect.DOM_MUTATE not in cls.effects.observable


@pytest.mark.parametrize("tag", ["input", "button"])
@pytest.mark.parametrize("in_form", [False, True])
def test_generic_reset_has_control_state_mutation(tag, in_form):
    ancestors = [ElementSpec(tag="form")] if in_form else []
    cls = classify(ElementSpec(tag=tag, attrs={"type": "reset"}, ancestors=ancestors))
    assert Authority.CLICK in cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


@pytest.mark.parametrize(("role", "authority"), [
    ("checkbox", Authority.CHANGE_VALUE),
    ("radio", Authority.CHANGE_VALUE),
    ("switch", Authority.TOGGLE),
    ("tab", Authority.TOGGLE),
])
def test_stateful_role_has_expected_control_state_mutation(role, authority):
    cls = classify(ElementSpec(tag="div", attrs={"role": role, "aria-checked": "false"}))
    assert authority in cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


def test_handler_alone_does_not_establish_what_script_mutates():
    cls = classify(ElementSpec(tag="button", attrs={"onclick": "respond()"}))
    assert cls.effects.observable == {Effect.EXECUTE}


@pytest.mark.parametrize("expanded", ["true", "false", " TRUE ", " False "])
@pytest.mark.parametrize("controls", [None, "answer", "answer another-answer"])
def test_native_disclosure_declares_expected_state_effect(expanded, controls):
    attrs = {"aria-expanded": expanded}
    if controls is not None:
        attrs["aria-controls"] = controls
    cls = classify(ElementSpec(tag="button", attrs=attrs))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS}
    assert cls.effects.observable == {Effect.DOM_MUTATE}
    assert f"aria-expanded={expanded.strip().lower()}:disclosure-state" in cls.composition_notes


@pytest.mark.parametrize(("tag", "attrs"), [
    ("div", {"role": "button"}),
    ("a", {"href": "#answer"}),
    ("input", {"type": "button"}),
])
def test_disclosure_effect_composes_with_control_affordances(tag, attrs):
    baseline = classify(ElementSpec(tag=tag, attrs=attrs))
    cls = classify(ElementSpec(tag=tag, attrs={**attrs, "aria-expanded": "false"}))
    assert cls.authority.effective == baseline.authority.effective
    assert cls.effects.observable == baseline.effects.observable | {Effect.DOM_MUTATE}


def test_disclosure_with_handler_keeps_both_effects():
    cls = classify(ElementSpec(tag="button", attrs={
        "aria-expanded": "false", "aria-controls": "answer", "onclick": "respond()",
    }))
    assert cls.effects.observable == {Effect.EXECUTE, Effect.DOM_MUTATE}


@pytest.mark.parametrize("attrs", [
    {},
    {"aria-label": "Expand answer"},
    {"aria-labelledby": "question"},
    {"aria-controls": "answer"},
    {"aria-haspopup": "true"},
    {"aria-label": "Expand answer", "aria-controls": "answer"},
])
def test_names_and_relationships_alone_do_not_establish_disclosure_effect(attrs):
    cls = classify(ElementSpec(tag="button", attrs=attrs))
    assert Effect.DOM_MUTATE not in cls.effects.observable


@pytest.mark.parametrize("expanded", ["", " ", "undefined", "mixed", "1", "false true"])
def test_invalid_expanded_state_does_not_establish_disclosure_effect(expanded):
    cls = classify(ElementSpec(tag="button", attrs={
        "aria-expanded": expanded, "aria-controls": "answer",
    }))
    assert Effect.DOM_MUTATE not in cls.effects.observable


@pytest.mark.parametrize(("tag", "attrs"), [
    ("div", {}),
    ("span", {}),
    ("div", {"tabindex": "0"}),
    ("div", {"role": "region"}),
])
def test_nonactivatable_expanded_state_does_not_establish_disclosure_effect(tag, attrs):
    cls = classify(ElementSpec(tag=tag, attrs={
        **attrs, "aria-expanded": "false", "aria-controls": "answer",
    }))
    assert Effect.DOM_MUTATE not in cls.effects.observable


def test_inherited_anchor_activation_does_not_make_descendant_a_disclosure_control():
    cls = classify(ElementSpec(tag="span", attrs={"aria-expanded": "false"}, ancestors=[
        ElementSpec(tag="a", attrs={"href": "#answer"}),
    ]))
    assert Authority.CLICK in cls.authority.inherited
    assert Effect.DOM_MUTATE not in cls.effects.observable


@pytest.mark.parametrize("attrs", [
    {"disabled": ""}, {"aria-disabled": "true"}, {"inert": ""},
])
def test_disclosure_effect_preserves_blocked_authority(attrs):
    cls = classify(ElementSpec(tag="button", attrs={**attrs, "aria-expanded": "false"}))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.DOM_MUTATE}


def test_disclosure_effect_preserves_inherited_inert_block():
    cls = classify(ElementSpec(tag="button", attrs={"aria-expanded": "false"}, ancestors=[
        ElementSpec(tag="div", attrs={"inert": ""}),
    ]))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.DOM_MUTATE}


@pytest.mark.parametrize("pressed", ["true", "false", "mixed", " TRUE ", " False ", " MIXED "])
def test_pressed_button_declares_expected_state_effect(pressed):
    cls = classify(ElementSpec(tag="button", attrs={"aria-pressed": pressed}))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS}
    assert cls.effects.observable == {Effect.DOM_MUTATE}
    assert f"aria-pressed={pressed.strip().lower()}:toggle-state" in cls.composition_notes


@pytest.mark.parametrize(("tag", "attrs"), [
    ("button", {"type": "button"}),
    ("button", {"type": "submit"}),
    ("button", {"type": "reset"}),
    ("input", {"type": "button"}),
    ("input", {"type": "submit"}),
    ("input", {"type": "reset"}),
    ("input", {"type": "image", "src": "submit.png"}),
    ("div", {"role": "button"}),
    ("a", {"href": "/destination", "role": "button"}),
])
def test_pressed_effect_composes_with_button_affordances(tag, attrs):
    baseline = classify(ElementSpec(tag=tag, attrs=attrs))
    cls = classify(ElementSpec(tag=tag, attrs={**attrs, "aria-pressed": "false"}))
    assert cls.authority == baseline.authority
    assert cls.effects.observable == baseline.effects.observable | {Effect.DOM_MUTATE}
    assert "aria-pressed=false:toggle-state" in cls.composition_notes


@pytest.mark.parametrize("pressed", [None, "", " ", "undefined", "1", "false true"])
def test_absent_or_invalid_pressed_state_does_not_establish_toggle_effect(pressed):
    attrs = {"aria-label": "Toggle setting"}
    if pressed is not None:
        attrs["aria-pressed"] = pressed
    cls = classify(ElementSpec(tag="button", attrs=attrs))
    assert Effect.DOM_MUTATE not in cls.effects.observable


@pytest.mark.parametrize(("tag", "attrs"), [
    ("div", {}),
    ("div", {"tabindex": "0"}),
    ("div", {"onclick": "respond()"}),
    ("a", {"href": "/destination"}),
    ("input", {"type": "file"}),
    ("input", {"type": "checkbox"}),
    ("button", {"role": "link"}),
    ("button", {"role": "switch"}),
    ("div", {"role": "future-widget button"}),
])
def test_pressed_state_does_not_reinterpret_nonbutton_or_unresolved_roles(tag, attrs):
    baseline = classify(ElementSpec(tag=tag, attrs=attrs))
    cls = classify(ElementSpec(tag=tag, attrs={**attrs, "aria-pressed": "false"}))
    assert cls.authority == baseline.authority
    assert cls.effects.observable == baseline.effects.observable
    assert not any(note.startswith("aria-pressed=") for note in cls.composition_notes)


def test_inherited_anchor_activation_does_not_make_descendant_a_toggle_button():
    cls = classify(ElementSpec(tag="span", attrs={"aria-pressed": "false"}, ancestors=[
        ElementSpec(tag="a", attrs={"href": "#setting"}),
    ]))
    assert Authority.CLICK in cls.authority.inherited
    assert Effect.DOM_MUTATE not in cls.effects.observable


def test_pressed_button_in_form_preserves_submission_and_handler_effects():
    cls = classify(ElementSpec(tag="button", attrs={
        "aria-pressed": "false", "onclick": "respond()",
    }, ancestors=[ElementSpec(tag="form")]))
    assert cls.authority.effective == {Authority.CLICK, Authority.FOCUS}
    assert cls.effects.observable == {
        Effect.SUBMIT, Effect.DOM_MUTATE, Effect.EXECUTE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME,
    }


def test_pressed_and_expanded_button_states_compose():
    cls = classify(ElementSpec(tag="button", attrs={
        "aria-pressed": "mixed", "aria-expanded": "false",
    }))
    assert cls.effects.observable == {Effect.DOM_MUTATE}
    assert "aria-pressed=mixed:toggle-state" in cls.composition_notes
    assert "aria-expanded=false:disclosure-state" in cls.composition_notes


@pytest.mark.parametrize("attrs", [
    {"disabled": ""}, {"aria-disabled": "true"}, {"inert": ""},
])
def test_pressed_effect_preserves_blocked_authority(attrs):
    cls = classify(ElementSpec(tag="button", attrs={**attrs, "aria-pressed": "false"}))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.DOM_MUTATE}


def test_pressed_effect_preserves_inherited_inert_block():
    cls = classify(ElementSpec(tag="button", attrs={"aria-pressed": "false"}, ancestors=[
        ElementSpec(tag="div", attrs={"inert": ""}),
    ]))
    assert cls.authority.effective == set()
    assert cls.effects.observable == {Effect.DOM_MUTATE}


@pytest.mark.parametrize("tag", ["div", "span", "td", "th"])
@pytest.mark.parametrize("editable", ["", "true", "plaintext-only"])
def test_explicit_content_editing_mutates_document_content(tag, editable):
    cls = classify(ElementSpec(tag=tag, attrs={"contenteditable": editable}))
    assert {Authority.TYPE, Authority.PASTE} <= cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


def test_contenteditable_with_handler_keeps_both_effects():
    cls = classify(ElementSpec(tag="div", attrs={
        "contenteditable": "true", "oninput": "respond()",
    }))
    assert {Authority.TYPE, Authority.PASTE} <= cls.authority.effective
    assert cls.effects.observable == {Effect.DOM_MUTATE, Effect.EXECUTE}


@pytest.mark.parametrize(("tag", "attrs"), [
    ("a", {"href": "/destination"}), ("label", {"for": "email"}), ("output", {}),
])
@pytest.mark.parametrize("editable", ["", "true", "plaintext-only"])
def test_explicit_and_inherited_editing_agree_on_non_static_tags(tag, attrs, editable):
    explicit = classify(ElementSpec(tag=tag, attrs={**attrs, "contenteditable": editable}))
    inherited = classify(ElementSpec(tag=tag, attrs=attrs, ancestors=[
        ElementSpec(tag="div", attrs={"contenteditable": editable}),
    ]))
    editing = {Authority.TYPE, Authority.FOCUS, Authority.PASTE}
    assert editing <= explicit.authority.direct
    assert editing <= inherited.authority.inherited
    assert explicit.authority.effective == inherited.authority.effective
    assert explicit.effects.observable == inherited.effects.observable
    assert Effect.DOM_MUTATE in explicit.effects.observable


@pytest.mark.parametrize("tag", ["span", "p", "td"])
@pytest.mark.parametrize("editable", ["true", "plaintext-only"])
def test_inherited_content_editing_mutates_document_content(tag, editable):
    cls = classify(ElementSpec(tag=tag, ancestors=[
        ElementSpec(tag="div", attrs={"contenteditable": editable}),
    ]))
    assert {Authority.TYPE, Authority.PASTE} <= cls.authority.inherited
    assert Effect.DOM_MUTATE in cls.effects.observable


def test_inherited_editing_effect_combines_with_handler():
    cls = classify(ElementSpec(tag="span", attrs={"onclick": "respond()"}, ancestors=[
        ElementSpec(tag="div", attrs={"contenteditable": "true"}),
    ]))
    assert cls.effects.observable == {Effect.DOM_MUTATE, Effect.EXECUTE}


@pytest.mark.parametrize("on_self", [False, True])
def test_contenteditable_false_blocks_inherited_mutation(on_self):
    editor = ElementSpec(tag="div", attrs={"contenteditable": "true"})
    disabled = {"contenteditable": "false"}
    cls = classify(ElementSpec(
        tag="span", attrs=disabled if on_self else {},
        ancestors=[editor] if on_self else [ElementSpec(tag="p", attrs=disabled), editor],
    ))
    assert Authority.TYPE not in cls.authority.effective
    assert Effect.DOM_MUTATE not in cls.effects.observable


def test_invalid_contenteditable_value_inherits_mutation():
    cls = classify(ElementSpec(tag="span", attrs={"contenteditable": "inherit"}, ancestors=[
        ElementSpec(tag="div", attrs={"contenteditable": "true"}),
    ]))
    assert Effect.DOM_MUTATE in cls.effects.observable


@pytest.mark.parametrize("tag", ["input", "textarea", "select", "script", "style", "template"])
@pytest.mark.parametrize("on_self", [False, True])
def test_editable_does_not_convert_native_state_or_metadata_to_dom_editing(tag, on_self):
    baseline = classify(ElementSpec(tag=tag))
    cls = classify(ElementSpec(
        tag=tag, attrs={"contenteditable": "true"} if on_self else {},
        ancestors=[] if on_self else [ElementSpec(tag="div", attrs={"contenteditable": "true"})],
    ))
    assert cls.effects.observable == baseline.effects.observable
    assert cls.authority.effective == baseline.authority.effective
    assert Authority.TYPE not in cls.authority.inherited


@pytest.mark.parametrize("attrs", [{}, {"open": ""}])
def test_summary_toggle_mutates_parent_open_attribute(attrs):
    cls = classify(ElementSpec(tag="summary", ancestors=[ElementSpec(tag="details", attrs=attrs)]))
    assert Authority.TOGGLE in cls.authority.effective
    assert Effect.DOM_MUTATE in cls.effects.observable


@pytest.mark.parametrize("ancestors", [
    [], [ElementSpec(tag="div")], [ElementSpec(tag="div"), ElementSpec(tag="details")],
])
def test_summary_without_direct_details_parent_does_not_establish_dom_mutation(ancestors):
    cls = classify(ElementSpec(tag="summary", ancestors=ancestors))
    assert Effect.DOM_MUTATE not in cls.effects.observable
