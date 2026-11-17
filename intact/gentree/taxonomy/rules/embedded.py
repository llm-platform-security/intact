"""Embedded / cross-origin elements: <iframe>, <embed>, <object>.

The frame element itself has minimal direct affordances — the content inside
the frame is a separate document with its own classifications. The frame's
own classification captures: render-frame, fetch, post-message Effects;
focus Authority; title attribute as accessible-name.

Sandbox flag handling for descendants is done in composition.py.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_iframe(s):     return s.tag == "iframe"
def _is_embed(s):      return s.tag == "embed"
def _is_object_tag(s): return s.tag == "object"


def _iframe_effects(s: ElementSpec) -> EffectSet:
    observable = {Effect.FETCH, Effect.RENDER_FRAME, Effect.POST_MESSAGE}
    # srcdoc inline HTML doesn't fetch; it renders inline.
    if "srcdoc" in s.attrs and "src" not in s.attrs:
        observable.discard(Effect.FETCH)
    # A sandboxed iframe without allow-scripts cannot run JS in the framed
    # document, so the framed content cannot drive window.postMessage. Empty
    # sandbox ("") blocks scripts; allow-scripts re-enables the channel.
    if "sandbox" in s.attrs:
        tokens = {t.strip().lower() for t in (s.attrs.get("sandbox") or "").split()}
        if "allow-scripts" not in tokens:
            observable.discard(Effect.POST_MESSAGE)
    return EffectSet(observable=observable)


RULES: list[Rule] = [
    Rule(
        name="embedded:iframe",
        match=_is_iframe,
        authority=AuthoritySet(direct={Authority.FOCUS}),
        effects=_iframe_effects,
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.TITLE_TOOLTIP},
            visible_to=_AX,
        ),
        specificity=1,
    ),
    Rule(
        name="embedded:embed",
        match=_is_embed,
        authority=AuthoritySet(direct={Authority.FOCUS}),
        effects=EffectSet(observable={Effect.FETCH, Effect.RENDER_FRAME}),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="embedded:object",
        match=_is_object_tag,
        authority=AuthoritySet(direct={Authority.FOCUS}),
        effects=EffectSet(observable={Effect.FETCH, Effect.RENDER_FRAME}),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
]
