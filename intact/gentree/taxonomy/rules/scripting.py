"""Scripting & metadata elements: <script>, <noscript>, <style>, <link>,
<meta>, <title>, <base>.

These rarely have agent affordances. Their classification captures the
browser-driven Effects (fetch, execute, apply-style) and Exposure channels
(meta-og for title/meta, event-handler-source for inline scripts).
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_script(s):            return s.tag == "script"
def _is_script_external(s):   return s.tag == "script" and "src" in s.attrs
def _is_noscript(s):          return s.tag == "noscript"
def _is_style(s):              return s.tag == "style"
def _is_title(s):              return s.tag == "title"
def _is_base(s):               return s.tag == "base"


def _is_link_stylesheet(s):
    return s.tag == "link" and s.attrs.get("rel", "").lower() == "stylesheet"


def _is_link_preload(s):
    # Rels that actually fetch a subresource. dns-prefetch/preconnect are
    # connection hints (DNS/socket setup), NOT subresource fetches, so they are
    # deliberately excluded and fall through to scripting:link-other (inert).
    return s.tag == "link" and s.attrs.get("rel", "").lower() in (
        "preload", "prefetch", "modulepreload",
    )


def _is_link_icon(s):
    # Favicons / touch icons fetch an image subresource.
    return s.tag == "link" and "icon" in s.attrs.get("rel", "").lower()


def _is_link_other(s):
    return s.tag == "link"


def _is_meta_refresh(s):
    return s.tag == "meta" and s.attrs.get("http-equiv", "").lower() == "refresh"


def _is_meta_og_or_desc(s):
    if s.tag != "meta":
        return False
    name = s.attrs.get("name", "").lower()
    prop = s.attrs.get("property", "").lower()
    if name in ("description", "keywords", "author"):
        return True
    if prop.startswith("og:") or prop.startswith("twitter:"):
        return True
    return False


def _is_meta(s):
    return s.tag == "meta"


RULES: list[Rule] = [
    # External script — fetches + executes.
    Rule(
        name="scripting:script-external",
        match=_is_script_external,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.FETCH, Effect.EXECUTE}),
        exposure=Exposure(channels=set(), visible_to={AgentView.DOM_TEXT}),
        specificity=2,
    ),
    # Inline script — just executes.
    Rule(
        name="scripting:script-inline",
        match=_is_script,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.EXECUTE}),
        # Inline body is visible to DOM-text scrape but not in AX.
        exposure=Exposure(
            channels={Channel.EVENT_HANDLER_SOURCE},
            visible_to={AgentView.DOM_TEXT},
        ),
        specificity=1,
    ),
    Rule(
        name="scripting:noscript",
        match=_is_noscript,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Rendered only when JS disabled; visible to scrapers.
        exposure=Exposure(
            channels={Channel.NOSCRIPT},
            visible_to={AgentView.DOM_TEXT},
        ),
        specificity=1,
    ),
    Rule(
        name="scripting:style",
        match=_is_style,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.APPLY_STYLE}),
        exposure=Exposure(channels=set(), visible_to={AgentView.DOM_TEXT}),
        specificity=1,
    ),
    Rule(
        name="scripting:link-stylesheet",
        match=_is_link_stylesheet,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.FETCH, Effect.APPLY_STYLE}),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=3,
    ),
    Rule(
        name="scripting:link-preload",
        match=_is_link_preload,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=3,
    ),
    Rule(
        name="scripting:link-icon",
        match=_is_link_icon,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=3,
    ),
    Rule(
        name="scripting:link-other",
        match=_is_link_other,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=1,
    ),
    # meta http-equiv=refresh navigates the frame AND fetches the target URL.
    Rule(
        name="scripting:meta-refresh",
        match=_is_meta_refresh,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.NAVIGATE_FRAME, Effect.SEND_REQUEST}),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=3,
    ),
    # og:* / description / keywords / twitter:* — Exposure.META_OG.
    Rule(
        name="scripting:meta-og",
        match=_is_meta_og_or_desc,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # AX tree typically doesn't surface meta, but raw-HTML scrapers do.
        exposure=Exposure(
            channels={Channel.META_OG},
            visible_to={AgentView.DOM_TEXT},
        ),
        specificity=2,
    ),
    Rule(
        name="scripting:meta",
        match=_is_meta,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=1,
    ),
    Rule(
        name="scripting:title",
        match=_is_title,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Title is in AX as the document title (and visible in tab UI).
        exposure=Exposure(channels={Channel.META_OG}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="scripting:base",
        match=_is_base,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # <base href> changes URL resolution for the document — a navigate-y side effect.
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=1,
    ),
]
