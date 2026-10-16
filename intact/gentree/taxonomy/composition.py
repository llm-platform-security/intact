"""Composition pass — applies after base classification.

Each composition rule is a function `(classification, spec) -> None` that
mutates the (deep-copied) classification in place and, if it fires, appends
a string to `classification.composition_notes`.

The orchestrator (`apply_composition`) deep-copies the base classification
once, then runs each rule in order. Composition rules don't compete on
specificity — they all fire if their predicate holds.

Rules in this module (order matters where ordering changes semantics):
1. wrapping_anchor    — <a href> ancestor extends click+focus+hover and navigation effects
2. inherited_contenteditable — explicit/ancestor contenteditable enables editing
3. tabindex_focus      — tabindex>=0 on self adds focus to direct
4. role_remap          — `role="button"` etc. remaps expected affordances
5. aria_expanded_disclosure — activatable aria-expanded controls have a state effect
6. aria_pressed_toggle — activatable aria-pressed buttons have a state effect
7. event_handler_execute — inline on*= handlers add the execute effect
8. tabindex_minus_one  — tabindex=-1 on self removes focus from effective authority
9. sandbox_block       — iframe-sandboxed descendants lose caps minus allow-*
10. pointer_events_none — computed style blocks click/hover
11. display_visibility — display:none / visibility:hidden drops from AX_TREE
12. aria_hidden        — aria-hidden=true drops from AX_TREE
13. disabled           — disabled / aria-disabled=true blocks all caps
14. inert              — inert on self or ancestor blocks all caps + drops AX
"""

from copy import deepcopy

from intact.gentree.taxonomy.enums import AgentView, Authority, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.types import ElementClassification


# HTML metadata content + inert containers: these generate no rendered box and
# cannot be a pointer-interaction target, so a wrapping <a href> does not make
# them clickable/navigable — propagating the anchor's authority/effects to them
# is a spurious over-claim. Their own base rule still applies (a <script> keeps
# its execute/fetch effects).
_NON_RENDERED_TAGS = frozenset({
    "script", "style", "template", "meta", "link", "title", "base", "head",
    "noscript",
})


# ── Helpers ─────────────────────────────────────────────────────────────────

def _any_ancestor(spec: ElementSpec, pred) -> ElementSpec | None:
    for a in spec.ancestors:
        if pred(a):
            return a
    return None


def _all_caps(cls: ElementClassification) -> set[Authority]:
    return set(cls.authority.direct) | set(cls.authority.inherited)


# ── Composition rules ───────────────────────────────────────────────────────

def _wrapping_anchor(cls: ElementClassification, spec: ElementSpec) -> None:
    """Wrapped by <a href>: a click on a descendant activates the ancestor anchor,
    so the descendant inherits both the anchor's authority AND its effects, scheme
    by scheme."""
    if spec.tag in ("a", "area") or spec.tag in _NON_RENDERED_TAGS:
        return
    a_anc = _any_ancestor(spec, lambda a: a.tag == "a" and "href" in a.attrs)
    if a_anc is None:
        return
    href = a_anc.attrs.get("href", "")
    auth = {Authority.CLICK, Authority.FOCUS, Authority.HOVER}
    if "download" in a_anc.attrs:
        eff = {Effect.SEND_REQUEST}
    elif href.lower().startswith("javascript:"):
        eff = {Effect.EXECUTE}
    elif href.lower().startswith(("mailto:", "tel:", "sms:")):
        eff = {Effect.EXTERNAL_HANDLER}
    else:
        if a_anc.attrs.get("target", "").lower() == "_blank":
            auth.add(Authority.POPUP)
        eff = {Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}
    cls.authority.inherited |= auth
    cls.effects.observable |= eff
    cls.composition_notes.append(f"wrapping-anchor:href={href!r}")


def _inherited_contenteditable(cls: ElementClassification, spec: ElementSpec) -> None:
    """Explicit or inherited `contenteditable` enables editing of DOM content.
    Native input controls retain their own value-editing semantics. A closer
    explicit false value blocks inheritance.
    """
    if spec.tag in ("input", "textarea", "select") or spec.tag in _NON_RENDERED_TAGS:
        return
    own_value = spec.attrs.get("contenteditable", "inherit").lower()
    if own_value in ("", "true", "plaintext-only"):
        # Contenteditable is global: non-static tags such as a/label/output
        # may have a base rule that does not already include editing.
        cls.authority.direct |= {Authority.TYPE, Authority.FOCUS, Authority.PASTE}
        cls.effects.observable.add(Effect.DOM_MUTATE)
        cls.composition_notes.append("contenteditable")
        return
    if own_value == "false":
        return
    for a in spec.ancestors:
        if "contenteditable" not in a.attrs:
            continue
        v = a.attrs["contenteditable"].lower()
        if v in ("false",):
            return  # disabled at this ancestor; closer "true"s would have hit first
        if v in ("", "true", "plaintext-only"):
            cls.authority.inherited |= {Authority.TYPE, Authority.FOCUS, Authority.PASTE}
            cls.effects.observable.add(Effect.DOM_MUTATE)
            cls.composition_notes.append("inherited-contenteditable")
            return


def _tabindex_focus(cls: ElementClassification, spec: ElementSpec) -> None:
    """tabindex>=0 makes any element focusable."""
    raw = spec.attrs.get("tabindex")
    if raw is None:
        return
    try:
        idx = int(raw)
    except ValueError:
        return
    if idx >= 0:
        cls.authority.direct.add(Authority.FOCUS)
        cls.composition_notes.append(f"tabindex={idx}")


def _tabindex_minus_one(cls: ElementClassification, spec: ElementSpec) -> None:
    """tabindex=-1 explicitly removes focusability via tab navigation."""
    raw = spec.attrs.get("tabindex")
    if raw is None:
        return
    try:
        idx = int(raw)
    except ValueError:
        return
    if idx == -1:
        cls.authority.blocked.add(Authority.FOCUS)
        cls.composition_notes.append("tabindex=-1")


_ROLE_REMAP = {
    "button":   {Authority.CLICK, Authority.FOCUS},
    "link":     {Authority.CLICK, Authority.FOCUS},
    "checkbox": {Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE},
    "radio":    {Authority.CLICK, Authority.FOCUS, Authority.CHANGE_VALUE},
    "switch":   {Authority.CLICK, Authority.FOCUS, Authority.TOGGLE},
    "tab":      {Authority.CLICK, Authority.FOCUS, Authority.TOGGLE},
    "menuitem": {Authority.CLICK, Authority.FOCUS},
}

# Role-based effects include expected widget-state transitions. DOM_MUTATE is
# broader than tree/attribute mutation and includes represented control state.
_ROLE_EFFECTS = {
    "button":   {Effect.EXECUTE},
    "menuitem": {Effect.EXECUTE},
    "link":     {Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
    "checkbox": {Effect.DOM_MUTATE},
    "radio":    {Effect.DOM_MUTATE},
    "switch":   {Effect.DOM_MUTATE},
    "tab":      {Effect.DOM_MUTATE},
}


def _role_remap(cls: ElementClassification, spec: ElementSpec) -> None:
    """ARIA role attribute remaps expected affordance.

    `<div role="button">` should classify as a button-like clickable. We don't
    overwrite the base rule's caps — we add the role's expected authority and
    any separately listed role effect. Authority need not imply an Effect.
    """
    role = spec.attrs.get("role")
    if not role:
        return
    role = role.lower()
    if role in _ROLE_REMAP:
        cls.authority.direct |= _ROLE_REMAP[role]
        cls.effects.observable |= _ROLE_EFFECTS.get(role, set())
        cls.composition_notes.append(f"role={role}")


def _event_handler_execute(cls: ElementClassification, spec: ElementSpec) -> None:
    """Any element with an inline on*= handler can run script on activation, so it
    gains the EXECUTE effect. This is the handler evidence that justifies EXECUTE
    on buttons/inputs (whose base rules do not claim it unconditionally)."""
    if any(k.startswith("on") and len(k) > 2 for k in spec.attrs):
        cls.effects.observable.add(Effect.EXECUTE)
        cls.composition_notes.append("on-handler:execute")


def _aria_expanded_disclosure(cls: ElementClassification, spec: ElementSpec) -> None:
    """An activatable control's aria-expanded declares disclosure state.

    Under the broad DOM/control-state taxonomy, activating that disclosure
    has an expected DOM_MUTATE effect. This does not establish a callback or
    observed execution. aria-controls can identify the controlled region, but
    is optional; accessible names or control relationships alone do not imply
    a state change. Inherited anchor activation does not turn a descendant's
    own aria-expanded attribute into a disclosure control.
    """
    expanded = spec.attrs.get("aria-expanded", "").strip().lower()
    if expanded not in ("true", "false"):
        return
    if not cls.authority.direct & {Authority.CLICK, Authority.TOGGLE}:
        return
    cls.effects.observable.add(Effect.DOM_MUTATE)
    cls.composition_notes.append(f"aria-expanded={expanded}:disclosure-state")


def _aria_pressed_toggle(cls: ElementClassification, spec: ElementSpec) -> None:
    """A button's valid aria-pressed declares expected toggle-state changes.

    aria-pressed applies to button semantics, not every clickable element.
    Accept native buttons (including button/submit/reset/image inputs) without
    an explicit role override, or the explicit button role. Other roles and
    role-token lists are not interpreted here. Existing direct activation must
    already be available; the state declaration adds only DOM_MUTATE, not a
    new Interaction or evidence of a callback or observed execution.
    """
    pressed = spec.attrs.get("aria-pressed", "").strip().lower()
    if pressed not in ("true", "false", "mixed"):
        return
    role = spec.attrs.get("role", "").strip().lower()
    native_button = spec.tag == "button" or (
        spec.tag == "input"
        and spec.attrs.get("type", "text").lower() in {"button", "submit", "reset", "image"}
    )
    if role != "button" and (role or not native_button):
        return
    if not cls.authority.direct & {Authority.CLICK, Authority.TOGGLE}:
        return
    cls.effects.observable.add(Effect.DOM_MUTATE)
    cls.composition_notes.append(f"aria-pressed={pressed}:toggle-state")


# Sandbox tokens that re-enable specific interactions or operation effects.
_SANDBOX_ALLOW = {
    "allow-forms":           {Effect.SUBMIT},
    "allow-popups":          {Authority.POPUP},
    "allow-top-navigation":  {Effect.NAVIGATE},
    "allow-same-origin":     set(),
}


def _sandbox_block(cls: ElementClassification, spec: ElementSpec) -> None:
    """Preserve the classifier's sandbox restrictions after moving operations
    to Effects. Blocking submission/navigation does not make a control
    unclickable. Downstream Effects retain their existing conditional semantics.
    """
    iframe = _any_ancestor(spec, lambda a: a.tag == "iframe" and "sandbox" in a.attrs)
    if iframe is None:
        return
    raw = iframe.attrs.get("sandbox", "") or ""
    allow_tokens = {t.strip().lower() for t in raw.split() if t.strip()}

    re_enabled: set[Authority | Effect] = set()
    for tok in allow_tokens:
        re_enabled |= _SANDBOX_ALLOW.get(tok, set())

    # Default-blocked-by-sandbox caps:
    default_blocked = {Effect.SUBMIT, Authority.POPUP, Effect.NAVIGATE}
    to_block = default_blocked - re_enabled
    cls.authority.blocked |= {x for x in to_block if isinstance(x, Authority)}
    cls.effects.observable -= {x for x in to_block if isinstance(x, Effect)}
    cls.composition_notes.append(
        f"iframe-sandbox:tokens={sorted(allow_tokens)} blocked={sorted(a.value for a in to_block)}"
    )


def _pointer_events_none(cls: ElementClassification, spec: ElementSpec) -> None:
    """Computed `pointer-events: none` blocks click/hover."""
    if spec.computed_style_flags.get("pointer-events", "auto") == "none":
        cls.authority.blocked |= {Authority.CLICK, Authority.HOVER}
        cls.composition_notes.append("pointer-events:none")


def _display_visibility(cls: ElementClassification, spec: ElementSpec) -> None:
    """display:none or visibility:hidden drops the element from AX_TREE view."""
    display = spec.computed_style_flags.get("display", "")
    vis = spec.computed_style_flags.get("visibility", "")
    if display == "none" or vis == "hidden":
        cls.exposure.visible_to.discard(AgentView.AX_TREE)
        cls.composition_notes.append(f"hidden:display={display!r} visibility={vis!r}")


def _aria_hidden(cls: ElementClassification, spec: ElementSpec) -> None:
    """aria-hidden=true drops from AX_TREE view."""
    if spec.attrs.get("aria-hidden", "").lower() == "true":
        cls.exposure.visible_to.discard(AgentView.AX_TREE)
        cls.composition_notes.append("aria-hidden")


def _disabled(cls: ElementClassification, spec: ElementSpec) -> None:
    """`disabled` attribute (or aria-disabled='true') blocks all authority."""
    is_disabled = (
        "disabled" in spec.attrs
        or spec.attrs.get("aria-disabled", "").lower() == "true"
    )
    if not is_disabled:
        return
    cls.authority.blocked |= _all_caps(cls)
    cls.composition_notes.append("disabled")


def _inert(cls: ElementClassification, spec: ElementSpec) -> None:
    """`inert` on self or any ancestor blocks all authority + drops from AX_TREE."""
    self_inert = "inert" in spec.attrs
    anc_inert = _any_ancestor(spec, lambda a: "inert" in a.attrs)
    if not (self_inert or anc_inert):
        return
    cls.authority.blocked |= _all_caps(cls)
    cls.exposure.visible_to.discard(AgentView.AX_TREE)
    cls.composition_notes.append("inert" + ("" if self_inert else ":ancestor"))


# ── Orchestrator ────────────────────────────────────────────────────────────

# Order matters where rules interact. tabindex_minus_one runs AFTER role_remap
# so a `<div role="button" tabindex="-1">` ends up button-like but not focusable.
# disabled / inert run last so they block any caps added by earlier composition.
_COMPOSITION_RULES = (
    _wrapping_anchor,
    _inherited_contenteditable,
    _tabindex_focus,
    _role_remap,
    _aria_expanded_disclosure,
    _aria_pressed_toggle,
    _event_handler_execute,
    _tabindex_minus_one,
    _sandbox_block,
    _pointer_events_none,
    _display_visibility,
    _aria_hidden,
    _disabled,
    _inert,
)


def apply_composition(
    base: ElementClassification, spec: ElementSpec
) -> ElementClassification:
    """Run every composition rule in order, returning a new classification."""
    cls = deepcopy(base)
    for rule in _COMPOSITION_RULES:
        try:
            rule(cls, spec)
        except Exception as e:
            cls.composition_notes.append(f"error:{rule.__name__}:{e!r}")
    return cls
