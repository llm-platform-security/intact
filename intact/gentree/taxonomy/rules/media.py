"""Media elements: <img>, <picture>, <source>, <video>, <audio>, <track>,
<canvas>, <svg>.

Most media is read-only with a browser-driven fetch on parse. Variants with
controls (video, audio) gain {click, focus}; img with on*= handler gains
execute via the handler.

SVG can host its own <script> and <a xlink:href> — we classify the outer
<svg> as static media; inner SVG elements would need svg-specific rules
later if needed.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_img(s):              return s.tag == "img"
def _is_picture(s):          return s.tag == "picture"
def _is_source(s):           return s.tag == "source"
def _is_track(s):            return s.tag == "track"
def _is_video(s):            return s.tag == "video"
def _is_audio(s):            return s.tag == "audio"
def _is_map(s):              return s.tag == "map"
def _is_canvas(s):           return s.tag == "canvas"
def _is_svg(s):              return s.tag == "svg"
def _is_video_with_controls(s): return s.tag == "video" and "controls" in s.attrs
def _is_audio_with_controls(s): return s.tag == "audio" and "controls" in s.attrs


RULES: list[Rule] = [
    # video with controls (specific over plain video)
    Rule(
        name="media:video-controls",
        match=_is_video_with_controls,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.HOVER},
        ),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(
            channels={
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
                Channel.CAPTION_TRACK,
            },
            visible_to=_AX,
        ),
        specificity=3,
    ),
    Rule(
        name="media:audio-controls",
        match=_is_audio_with_controls,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS},
        ),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.CAPTION_TRACK},
            visible_to=_AX,
        ),
        specificity=3,
    ),
    Rule(
        name="media:img",
        match=_is_img,
        authority=AuthoritySet(direct={Authority.HOVER}),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(
            channels={
                Channel.ALT,
                Channel.ACCESSIBLE_NAME,
                Channel.TITLE_TOOLTIP,
            },
            visible_to=_AX,
        ),
        specificity=1,
    ),
    Rule(
        name="media:picture",
        match=_is_picture,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Picture wraps source/img selection; meaningful content is in <img>.
        exposure=Exposure(channels=set(), visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:source",
        match=_is_source,
        authority=AuthoritySet(),
        # Source itself doesn't fetch — the parent (<picture> / <video> / <audio>) does.
        effects=EffectSet(),
        exposure=Exposure(channels=set(), visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:track",
        match=_is_track,
        authority=AuthoritySet(),
        # VTT fetched on demand by the parent <video>/<audio>; classifier
        # records fetch capability so defenses know the channel exists.
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(channels={Channel.CAPTION_TRACK}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:video",
        match=_is_video,
        authority=AuthoritySet(),
        # No controls → no agent-driven affordance; just the parser-driven fetch.
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME, Channel.CAPTION_TRACK},
            visible_to=_AX,
        ),
        specificity=1,
    ),
    Rule(
        name="media:audio",
        match=_is_audio,
        authority=AuthoritySet(),
        effects=EffectSet(observable={Effect.FETCH}),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:map",
        match=_is_map,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:canvas",
        match=_is_canvas,
        # Canvas drawn pixels aren't accessible-text by default. Hover is the
        # cheapest agent affordance. Real interactivity needs JS + tabindex.
        authority=AuthoritySet(direct={Authority.HOVER}),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
    Rule(
        name="media:svg",
        match=_is_svg,
        authority=AuthoritySet(direct={Authority.HOVER}),
        effects=EffectSet(),
        # SVG accessible-name comes from <title> child or aria-label.
        exposure=Exposure(channels={Channel.ACCESSIBLE_NAME}, visible_to=_AX),
        specificity=1,
    ),
]
