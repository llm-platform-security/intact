"""Form root, controls, buttons, labels.

Effects are observable-only. We do NOT inspect the form's action URL for
"/checkout" / "/login" / "/delete" patterns — that was URL-pattern heuristic
that belongs in a separate consequence-scoring module, not the structural
taxonomy.

Buttons inside vs outside a form differ — that distinction lives here,
not in composition, because it's a base affordance choice rather than an
inherited/blocked cap.

DOM_MUTATE includes represented control-state changes as well as DOM node,
text, and attribute changes. Its meaning is broader than MutationObserver
records: input/textarea values, checkedness, selectedness, reset state, and label
activation have this effect even without a corresponding attribute mutation.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}

# Potential form operation and downstream consequences of successful submission.
_SUBMIT_EFFECTS = EffectSet(observable={Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME})


def _ancestor_form(spec: ElementSpec) -> ElementSpec | None:
    for a in spec.ancestors:
        if a.tag == "form":
            return a
    return None


# ── Tag/type predicates ─────────────────────────────────────────────────────

def _is_form(s):     return s.tag == "form"
def _is_textarea(s): return s.tag == "textarea"
def _is_select(s):   return s.tag == "select"
def _is_option(s):   return s.tag == "option"
def _is_optgroup(s): return s.tag == "optgroup"
def _is_datalist(s): return s.tag == "datalist"
def _is_output(s):   return s.tag == "output"
def _is_progress(s): return s.tag == "progress"
def _is_meter(s):    return s.tag == "meter"
def _is_fieldset(s): return s.tag == "fieldset"
def _is_legend(s):   return s.tag == "legend"


def _input_type(s: ElementSpec) -> str:
    return s.attrs.get("type", "text").lower()


_TEXT_INPUT_TYPES = frozenset({
    "text", "email", "search", "tel", "url", "password",
    "number", "date", "datetime-local", "month", "week", "time",
})


def _is_text_input(s):       return s.tag == "input" and _input_type(s) in _TEXT_INPUT_TYPES
def _is_password_input(s):   return s.tag == "input" and _input_type(s) == "password"
def _is_check_radio_input(s): return s.tag == "input" and _input_type(s) in ("checkbox", "radio")
def _is_button_input(s):     return s.tag == "input" and _input_type(s) == "button"
def _is_submit_input(s):     return s.tag == "input" and _input_type(s) == "submit"
def _is_image_input(s):      return s.tag == "input" and _input_type(s) == "image"
def _is_reset_input(s):      return s.tag == "input" and _input_type(s) == "reset"
def _is_file_input(s):       return s.tag == "input" and _input_type(s) == "file"
def _is_hidden_input(s):     return s.tag == "input" and _input_type(s) == "hidden"
def _is_range_color_input(s): return s.tag == "input" and _input_type(s) in ("range", "color")


def _is_button(s):                       return s.tag == "button"
def _is_button_type_button(s):           return s.tag == "button" and s.attrs.get("type", "submit").lower() == "button"
def _is_button_type_reset(s):            return s.tag == "button" and s.attrs.get("type", "submit").lower() == "reset"
def _is_button_in_form(s):               return _is_button(s) and _ancestor_form(s) is not None
def _is_button_type_button_in_form(s):   return _is_button_type_button(s) and _ancestor_form(s) is not None


def _is_label_for(s):
    return s.tag == "label" and "for" in s.attrs


# ── Context-conditional authority / effects ──────────────────────────────────

def _text_input_effects(s: ElementSpec) -> EffectSet:
    """Typing changes the value. Form-associated inputs may also initiate
    implicit submission (such as Enter), conditional on the form and browser.
    Ordinary typing alone does not imply SUBMIT or its downstream effects.
    """
    observable = {Effect.DOM_MUTATE}
    if _ancestor_form(s) is not None:
        observable.add(Effect.SUBMIT)
    return EffectSet(observable=observable)


def _image_input_effects(s: ElementSpec) -> EffectSet:
    """Graphical submit control: submits the form; fetches the image only when a
    non-empty src is present."""
    obs = {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}
    if s.attrs.get("src", "").strip():
        obs.add(Effect.FETCH)
    return EffectSet(observable=obs)


RULES: list[Rule] = [
    # ── Form root ──────────────────────────────────────────────────────────

    Rule(
        name="form:root",
        match=_is_form,
        # A form supports submission but is not itself an activation control.
        authority=AuthoritySet(),
        effects=_SUBMIT_EFFECTS,
        exposure=Exposure(channels=set(), visible_to=_AX),
        specificity=1,
    ),

    # ── input variants — most specific first ──────────────────────────────

    Rule(
        name="input:hidden",
        match=_is_hidden_input,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Hidden input value isn't in AX, but DOM_TEXT scrapers do see it.
        exposure=Exposure(channels={Channel.VALUE}, visible_to={AgentView.DOM_TEXT}),
        specificity=3,
    ),

    Rule(
        name="input:password",
        match=_is_password_input,
        authority=AuthoritySet(direct={Authority.TYPE, Authority.FOCUS}),
        effects=_text_input_effects,
        # AX-visible to label its presence, but value should be considered sensitive.
        exposure=Exposure(
            channels={Channel.PLACEHOLDER, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:submit",
        match=_is_submit_input,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS},
        ),
        effects=_SUBMIT_EFFECTS,
        exposure=Exposure(
            channels={Channel.VALUE, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:image",
        match=_is_image_input,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS},
        ),
        effects=_image_input_effects,  # FETCH only when src present
        exposure=Exposure(
            channels={Channel.ALT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:reset",
        match=_is_reset_input,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # restores control state
        exposure=Exposure(
            channels={Channel.VALUE, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:file",
        match=_is_file_input,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.UPLOAD},
        ),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=3,
    ),

    Rule(
        name="input:button",
        match=_is_button_input,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        # No intrinsic effect: a button does nothing without a handler. EXECUTE is
        # added by composition when an on*= handler is present.
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.VALUE, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:checkbox-radio",
        match=_is_check_radio_input,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE},
        ),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # current checkedness
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:range-color",
        match=_is_range_color_input,
        authority=AuthoritySet(
            direct={Authority.FOCUS, Authority.CHANGE_VALUE},
        ),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # current value
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="input:text-family",
        match=_is_text_input,
        authority=AuthoritySet(direct={Authority.TYPE, Authority.FOCUS}),
        effects=_text_input_effects,
        exposure=Exposure(
            channels={Channel.PLACEHOLDER, Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=2,
    ),

    # ── textarea / select / option / etc. ─────────────────────────────────

    Rule(
        name="textarea",
        match=_is_textarea,
        # Enter in a <textarea> inserts a newline, it does not imply SUBMIT.
        authority=AuthoritySet(
            direct={Authority.TYPE, Authority.FOCUS, Authority.PASTE},
        ),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # typing/pasting changes value
        exposure=Exposure(
            channels={Channel.PLACEHOLDER, Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="select",
        match=_is_select,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE},
        ),
        # Choosing an option can change selectedness; opening the picker alone
        # does not guarantee either effect.
        effects=EffectSet(observable={Effect.CHOOSE, Effect.DOM_MUTATE}),
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.OPTION_TEXT},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="option",
        match=_is_option,
        authority=AuthoritySet(),  # not directly actionable; selected via parent select
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.OPTION_TEXT, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="optgroup",
        match=_is_optgroup,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),

    Rule(
        name="datalist",
        match=_is_datalist,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Provides options to inputs — option-text is the readable surface.
        exposure=Exposure(channels={Channel.OPTION_TEXT}, visible_to=_AX),
        specificity=1,
    ),

    Rule(
        name="output",
        match=_is_output,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="progress",
        match=_is_progress,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="meter",
        match=_is_meter,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    # ── button variants ────────────────────────────────────────────────────
    #
    # Order:
    #   1. button[type=reset] (any context)        — restores form defaults
    #   2. button[type=button] inside form         — explicit override, no submit
    #   3. button[type=button] outside form        — generic click
    #   4. button inside form (default submit)     — triggers submit
    #   5. button outside form (default submit)    — generic click, fallback
    #
    # Higher-specificity rules earlier in the list to ensure they win on tie.

    Rule(
        name="button:reset",
        match=_is_button_type_reset,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # restores control state
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=4,
    ),

    Rule(
        name="button:type-button-in-form",
        match=_is_button_type_button_in_form,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        # No intrinsic effect without a handler; EXECUTE added by composition on on*=.
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=4,
    ),

    Rule(
        name="button:type-button",
        match=_is_button_type_button,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        # No intrinsic effect without a handler; EXECUTE added by composition on on*=.
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="button:in-form",
        match=_is_button_in_form,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS},
        ),
        effects=_SUBMIT_EFFECTS,
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),

    Rule(
        name="button:standalone",
        match=_is_button,
        authority=AuthoritySet(direct={Authority.CLICK, Authority.FOCUS}),
        # No intrinsic effect without a handler; EXECUTE added by composition on on*=.
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    # ── label / fieldset / legend ──────────────────────────────────────────

    Rule(
        name="label:for-reference",
        match=_is_label_for,
        # Clicking the label propagates to the for-referenced control.
        # The control receives the click; label itself is read+focusable-via-click.
        authority=AuthoritySet(direct={Authority.CLICK}),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),  # focuses/activates control
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),

    Rule(
        name="label:plain",
        match=lambda s: s.tag == "label",
        authority=AuthoritySet(direct={Authority.CLICK}),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=1,
    ),

    Rule(
        name="fieldset",
        match=_is_fieldset,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),

    Rule(
        name="legend",
        match=_is_legend,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Legend becomes the fieldset's accessible name.
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=1,
    ),
]
