"""Anchor / link elements: <a>, <area>.

The canonical clickable + navigable elements. Attribute-driven variants
significantly change the classification:

- a (no href):          inert, like a span
- a[href=...]:          click + focus + hover; navigate + send-request + navigate-frame
- a[href=javascript:]:  + execute (URL scheme is a code channel)
- a[target=_blank]:     + popup
- a[href][download]:    file download — fires send-request but no navigate-frame
                        (browser does not change page after download)
- a[href=mailto:|tel:|sms:]: out-of-band — hands off to OS app; no in-browser
                        send-request, no navigate-frame
- area[href=...]:       like a[href] but with alt-text exposure

Effects describe potential operations, not guaranteed outcomes of every click.
No URL-pattern heuristics.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _href_scheme(spec: ElementSpec) -> str:
    href = spec.attrs.get("href", "").strip().lower()
    if ":" not in href:
        return ""
    return href.split(":", 1)[0]


def _is_a_without_href(s: ElementSpec) -> bool:
    return s.tag == "a" and "href" not in s.attrs


def _is_a_with_href(s: ElementSpec) -> bool:
    return s.tag == "a" and "href" in s.attrs


def _is_a_javascript(s: ElementSpec) -> bool:
    return s.tag == "a" and _href_scheme(s) == "javascript"


def _is_a_target_blank(s: ElementSpec) -> bool:
    return s.tag == "a" and "href" in s.attrs and s.attrs.get("target") == "_blank"


def _is_a_with_download(s: ElementSpec) -> bool:
    return s.tag == "a" and "href" in s.attrs and "download" in s.attrs


def _is_a_out_of_band(s: ElementSpec) -> bool:
    return s.tag == "a" and _href_scheme(s) in ("mailto", "tel", "sms")


def _is_area_with_href(s: ElementSpec) -> bool:
    return s.tag == "area" and "href" in s.attrs


RULES: list[Rule] = [
    # --- Highest specificity: scheme-specific variants ----------------------

    Rule(
        name="anchor:javascript-scheme",
        match=_is_a_javascript,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.HOVER},
        ),
        effects=EffectSet(observable={Effect.EXECUTE}),
        exposure=Exposure(
            channels={
                Channel.BODY_TEXT,
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
                Channel.EVENT_HANDLER_SOURCE,
            },
            visible_to=_AX,
        ),
        specificity=4,
    ),

    Rule(
        name="anchor:mailto-tel-sms",
        match=_is_a_out_of_band,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.HOVER},
        ),
        # No in-browser network request or navigation, but it is not inert: the
        # OS handler takes over (mail client / dialer / SMS app). For mailto: and
        # sms: the URL can carry data (subject/body), making this an off-browser
        # exfiltration surface, so we mark it EXTERNAL_HANDLER rather than empty.
        effects=EffectSet(observable={Effect.EXTERNAL_HANDLER}),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=4,
    ),

    # --- Attribute upgrades over base a[href] -------------------------------

    Rule(
        name="anchor:download",
        match=_is_a_with_download,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.HOVER},
        ),
        # Fires a network request to fetch the file, but does NOT navigate the
        # frame (browser stays on the current page). That's the observable
        # distinction from anchor:href.
        effects=EffectSet(observable={Effect.SEND_REQUEST}),
        exposure=Exposure(
            channels={
                Channel.BODY_TEXT,
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
            },
            visible_to=_AX,
        ),
        specificity=3,
    ),

    Rule(
        name="anchor:target-blank",
        match=_is_a_target_blank,
        authority=AuthoritySet(
            direct={
                Authority.CLICK, Authority.FOCUS, Authority.HOVER,
                Authority.POPUP,
            },
        ),
        effects=EffectSet(observable={Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}),
        exposure=Exposure(
            channels={
                Channel.BODY_TEXT,
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
            },
            visible_to=_AX,
        ),
        specificity=3,
    ),

    # --- Canonical a[href] --------------------------------------------------

    Rule(
        name="anchor:href",
        match=_is_a_with_href,
        authority=AuthoritySet(
            direct={
                Authority.CLICK, Authority.FOCUS, Authority.HOVER,
            },
        ),
        effects=EffectSet(observable={Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}),
        exposure=Exposure(
            channels={
                Channel.BODY_TEXT,
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
            },
            visible_to=_AX,
        ),
        specificity=2,
    ),

    # --- Inert <a> without href --------------------------------------------

    Rule(
        name="anchor:no-href",
        match=_is_a_without_href,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT},
            visible_to=_AX,
        ),
        specificity=2,
    ),

    # --- <area href=…> -----------------------------------------------------

    Rule(
        name="anchor:area-href",
        match=_is_area_with_href,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS},
        ),
        effects=EffectSet(observable={Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}),
        exposure=Exposure(
            channels={Channel.ALT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),
]
