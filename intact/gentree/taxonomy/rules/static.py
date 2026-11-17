"""Static text / phrasing / sectioning / list elements.

Authority:
- Base: none (text containers don't expose operations).
- With on*= handler: gains {click, focus} + execute effect.
- With contenteditable: gains {type, focus, paste} + dom-mutate effect.
- With tabindex>=0: gains {focus}.

Exposure: body-text always; event-handler-source when on*= present;
value when contenteditable.

Most ARIA role overrides (role="button" on a static element) are handled in
composition.py, not here — that file is the single place role-remapping lives.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_STATIC_TAGS = frozenset({
    "p", "span", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "em", "strong", "b", "i", "u", "s", "mark", "small",
    "blockquote", "cite", "q", "abbr", "code", "kbd", "samp", "var",
    "pre", "time", "br", "hr", "sub", "sup", "ins", "del",
    "address", "figure", "figcaption", "ruby", "rt", "rp",
})

_SECTIONING_TAGS = frozenset({
    "header", "footer", "main", "section", "article", "nav", "aside",
})

_LIST_TAGS = frozenset({"ul", "ol", "li", "dl", "dt", "dd", "menu"})

_ALL_TEXT_TAGS = _STATIC_TAGS | _SECTIONING_TAGS | _LIST_TAGS

_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_text_container(spec: ElementSpec) -> bool:
    return spec.tag in _ALL_TEXT_TAGS


def _has_on_handler(spec: ElementSpec) -> bool:
    return any(k.startswith("on") and len(k) > 2 for k in spec.attrs)


def _has_contenteditable(spec: ElementSpec) -> bool:
    if "contenteditable" not in spec.attrs:
        return False
    v = spec.attrs["contenteditable"].lower()
    # Empty value, "true", or "plaintext-only" all enable editing.
    # "false" or "inherit" do not (inherit is handled in composition).
    return v in ("", "true", "plaintext-only")


def _has_positive_tabindex(spec: ElementSpec) -> bool:
    raw = spec.attrs.get("tabindex")
    if raw is None:
        return False
    try:
        return int(raw) >= 0
    except ValueError:
        return False


def _handler_authority(spec: ElementSpec) -> AuthoritySet:
    direct = {Authority.CLICK, Authority.FOCUS}
    if _has_contenteditable(spec):
        direct |= {Authority.TYPE, Authority.PASTE}
    return AuthoritySet(direct=direct)


def _handler_effects(spec: ElementSpec) -> EffectSet:
    observable = {Effect.EXECUTE}
    if _has_contenteditable(spec):
        observable.add(Effect.DOM_MUTATE)
    return EffectSet(observable=observable)


RULES: list[Rule] = [
    # --- Specific variants first (higher specificity) -----------------------

    Rule(
        name="static:with-event-handler",
        match=lambda s: _is_text_container(s) and _has_on_handler(s),
        authority=_handler_authority,
        effects=_handler_effects,
        exposure=lambda s: Exposure(
            channels={Channel.BODY_TEXT, Channel.EVENT_HANDLER_SOURCE}
            | ({Channel.VALUE} if _has_contenteditable(s) else set()),
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="static:contenteditable",
        match=lambda s: _is_text_container(s) and _has_contenteditable(s),
        authority=AuthoritySet(
            direct={Authority.TYPE, Authority.FOCUS, Authority.PASTE},
        ),
        effects=EffectSet(observable={Effect.DOM_MUTATE}),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.VALUE},
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="static:tabindex-focusable",
        match=lambda s: _is_text_container(s) and _has_positive_tabindex(s),
        authority=AuthoritySet(direct={Authority.FOCUS}),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT},
            visible_to=_AX,
        ),
        specificity=2,
    ),

    # --- Base text container (catch-all for known static tags) --------------

    Rule(
        name="static:base",
        match=_is_text_container,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT},
            visible_to=_AX,
        ),
        specificity=1,
    ),
]
