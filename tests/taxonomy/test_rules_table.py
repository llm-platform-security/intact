"""Table-driven coverage across all element families.

Each row in `_TABLE` is an `(label, spec, expected)` triple where `expected`
is a dict of asserted subsets:
    "source_rule":          exact string match
    "authority_direct":     subset of cls.authority.direct
    "authority_blocked":    subset of cls.authority.blocked
    "authority_effective":  subset of cls.authority.effective
    "observable_effects":   subset of cls.effects.observable
    "no_observable_effects": effects guaranteed NOT in cls.effects.observable
    "exposure_channels":    subset of cls.exposure.channels
    "exposure_views":       subset of cls.exposure.visible_to
    "not_exposure_views":   set NOT in cls.exposure.visible_to

This file is the most-recent line of defense — it's the published taxonomy
table re-expressed as code. If a rule regresses, the matching row's test
fails with a clear diff.
"""

import pytest

from intact.gentree.taxonomy import (
    AgentView, Authority, Channel, Effect, ElementSpec,
)
from intact.gentree.taxonomy.classifier import classify


_AX_VISIBLE = {AgentView.AX_TREE, AgentView.DOM_TEXT}


# ── Test rows ────────────────────────────────────────────────────────────────

_TABLE: list[tuple[str, ElementSpec, dict]] = [
    # ---- Static / phrasing / sectioning / lists -------------------------------
    ("static:p", ElementSpec(tag="p"), {
        "source_rule": "static:base",
        "exposure_channels": {Channel.BODY_TEXT},
        "exposure_views": _AX_VISIBLE,
    }),
    ("static:h1", ElementSpec(tag="h1"), {
        "source_rule": "static:base",
        "exposure_channels": {Channel.BODY_TEXT},
    }),
    ("static:section", ElementSpec(tag="section"), {
        "source_rule": "static:base",
    }),
    ("static:ul", ElementSpec(tag="ul"), {
        "source_rule": "static:base",
    }),
    ("static:div-onclick", ElementSpec(tag="div", attrs={"onclick": "x()"}), {
        "source_rule": "static:with-event-handler",
        "authority_direct": {Authority.CLICK, Authority.FOCUS},
        "observable_effects": {Effect.EXECUTE},
        "exposure_channels": {Channel.BODY_TEXT, Channel.EVENT_HANDLER_SOURCE},
    }),
    ("static:div-contenteditable", ElementSpec(tag="div", attrs={"contenteditable": "true"}), {
        "source_rule": "static:contenteditable",
        "authority_direct": {Authority.TYPE, Authority.FOCUS, Authority.PASTE},
        "observable_effects": {Effect.DOM_MUTATE},
    }),

    # ---- Anchors --------------------------------------------------------------
    ("anchor:no-href", ElementSpec(tag="a"), {
        "source_rule": "anchor:no-href",
    }),
    ("anchor:href", ElementSpec(tag="a", attrs={"href": "/x"}), {
        "source_rule": "anchor:href",
        "authority_direct": {Authority.CLICK, Authority.FOCUS},
        "observable_effects": {Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
        "exposure_channels": {Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
    }),
    ("anchor:javascript", ElementSpec(tag="a", attrs={"href": "javascript:x()"}), {
        "source_rule": "anchor:javascript-scheme",
        "observable_effects": {Effect.EXECUTE},
    }),
    ("anchor:target-blank", ElementSpec(tag="a", attrs={"href": "/x", "target": "_blank"}), {
        "source_rule": "anchor:target-blank",
        "authority_direct": {Authority.POPUP},
    }),
    ("anchor:download", ElementSpec(tag="a", attrs={"href": "/f.pdf", "download": ""}), {
        "source_rule": "anchor:download",
        "observable_effects": {Effect.SEND_REQUEST},
        "no_observable_effects": {Effect.NAVIGATE_FRAME},
    }),
    ("anchor:mailto", ElementSpec(tag="a", attrs={"href": "mailto:x@y.com"}), {
        "source_rule": "anchor:mailto-tel-sms",
        "observable_effects": {Effect.EXTERNAL_HANDLER},
        "no_observable_effects": {Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
    }),
    ("anchor:area-href", ElementSpec(tag="area", attrs={"href": "/dest"}), {
        "source_rule": "anchor:area-href",
        "authority_direct": {Authority.CLICK},
        "observable_effects": {Effect.NAVIGATE},
        "exposure_channels": {Channel.ALT},
    }),

    # ---- Forms ---------------------------------------------------------------
    ("form:simple", ElementSpec(tag="form", attrs={"action": "/x"}), {
        "source_rule": "form:root",
        "observable_effects": {Effect.SUBMIT, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
    }),
    ("form:checkout", ElementSpec(tag="form", attrs={"action": "/checkout", "method": "post"}), {
        # Same observable effects as any other form — URL pattern is not heuristic-classified.
        "source_rule": "form:root",
        "observable_effects": {Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME},
    }),
    ("input:text", ElementSpec(tag="input", attrs={"type": "text"}), {
        "source_rule": "input:text-family",
        "authority_direct": {Authority.TYPE, Authority.FOCUS},
    }),
    ("input:password", ElementSpec(tag="input", attrs={"type": "password"}), {
        "source_rule": "input:password",
        "authority_direct": {Authority.TYPE, Authority.FOCUS},
    }),
    ("input:hidden", ElementSpec(tag="input", attrs={"type": "hidden"}), {
        "source_rule": "input:hidden",
        "not_exposure_views": {AgentView.AX_TREE},
    }),
    ("input:file", ElementSpec(tag="input", attrs={"type": "file"}), {
        "source_rule": "input:file",
        "authority_direct": {Authority.UPLOAD},
    }),
    ("input:checkbox", ElementSpec(tag="input", attrs={"type": "checkbox"}), {
        "source_rule": "input:checkbox-radio",
        "authority_direct": {Authority.CHANGE_VALUE},
    }),
    ("textarea", ElementSpec(tag="textarea"), {
        "source_rule": "textarea",
        "authority_direct": {Authority.TYPE, Authority.PASTE},
    }),
    ("select", ElementSpec(tag="select"), {
        "source_rule": "select",
        "authority_direct": {Authority.CLICK, Authority.CHANGE_VALUE},
        "observable_effects": {Effect.CHOOSE, Effect.DOM_MUTATE},
    }),
    ("option", ElementSpec(tag="option"), {
        "source_rule": "option",
        "exposure_channels": {Channel.OPTION_TEXT},
    }),
    ("button:standalone", ElementSpec(tag="button"), {
        "source_rule": "button:standalone",
        "authority_direct": {Authority.CLICK},
    }),
    ("button:in-form", ElementSpec(
        tag="button",
        ancestors=[ElementSpec(tag="form", attrs={"action": "/x"})],
    ), {
        "source_rule": "button:in-form",
        "authority_direct": {Authority.CLICK},
        "observable_effects": {Effect.SUBMIT},
    }),
    ("button:reset", ElementSpec(tag="button", attrs={"type": "reset"}), {
        "source_rule": "button:reset",
    }),
    ("label:for", ElementSpec(tag="label", attrs={"for": "email"}), {
        "source_rule": "label:for-reference",
        "authority_direct": {Authority.CLICK},
    }),
    ("fieldset", ElementSpec(tag="fieldset"), {
        "source_rule": "fieldset",
        "exposure_channels": {Channel.ACCESSIBLE_NAME},
    }),

    # ---- Media ---------------------------------------------------------------
    ("media:img", ElementSpec(tag="img", attrs={"src": "/a.jpg", "alt": "x"}), {
        "source_rule": "media:img",
        "authority_direct": {Authority.HOVER},
        "observable_effects": {Effect.FETCH},
        "exposure_channels": {Channel.ALT},
    }),
    ("media:video-controls", ElementSpec(tag="video", attrs={"controls": "", "src": "/v.mp4"}), {
        "source_rule": "media:video-controls",
        "authority_direct": {Authority.CLICK, Authority.FOCUS},
        "observable_effects": {Effect.FETCH},
        "exposure_channels": {Channel.CAPTION_TRACK},
    }),
    ("media:video-no-controls", ElementSpec(tag="video", attrs={"src": "/v.mp4"}), {
        "source_rule": "media:video",
        "observable_effects": {Effect.FETCH},
    }),
    ("media:audio-controls", ElementSpec(tag="audio", attrs={"controls": "", "src": "/a.mp3"}), {
        "source_rule": "media:audio-controls",
        "authority_direct": {Authority.CLICK, Authority.FOCUS},
    }),
    ("media:track", ElementSpec(tag="track", attrs={"src": "/c.vtt"}), {
        "source_rule": "media:track",
        "observable_effects": {Effect.FETCH},
        "exposure_channels": {Channel.CAPTION_TRACK},
    }),
    ("media:canvas", ElementSpec(tag="canvas"), {
        "source_rule": "media:canvas",
        "authority_direct": {Authority.HOVER},
    }),
    ("media:svg", ElementSpec(tag="svg"), {
        "source_rule": "media:svg",
    }),

    # ---- Embedded ------------------------------------------------------------
    ("embedded:iframe", ElementSpec(tag="iframe", attrs={"src": "/page"}), {
        "source_rule": "embedded:iframe",
        "authority_direct": {Authority.FOCUS},
        "observable_effects": {Effect.FETCH, Effect.RENDER_FRAME, Effect.POST_MESSAGE},
    }),
    ("embedded:iframe-srcdoc", ElementSpec(tag="iframe", attrs={"srcdoc": "<p>hi</p>"}), {
        "source_rule": "embedded:iframe",
        "observable_effects": {Effect.RENDER_FRAME, Effect.POST_MESSAGE},
    }),

    # ---- Tables --------------------------------------------------------------
    ("table:base", ElementSpec(tag="table"), {
        "source_rule": "table:base",
    }),
    ("table:td-contenteditable", ElementSpec(
        tag="td", attrs={"contenteditable": "true"},
    ), {
        "source_rule": "table:cell-contenteditable",
        "authority_direct": {Authority.TYPE, Authority.PASTE},
    }),

    # ---- Modal ---------------------------------------------------------------
    ("modal:summary", ElementSpec(tag="summary"), {
        "source_rule": "modal:summary",
        "authority_direct": {Authority.CLICK, Authority.TOGGLE},
    }),
    ("modal:details-closed", ElementSpec(tag="details"), {
        "source_rule": "modal:details",
    }),
    ("modal:details-open", ElementSpec(tag="details", attrs={"open": ""}), {
        "source_rule": "modal:details-open",
    }),
    ("modal:dialog-closed", ElementSpec(tag="dialog"), {
        "source_rule": "modal:dialog",
        "not_exposure_views": {AgentView.AX_TREE},
    }),
    ("modal:dialog-open", ElementSpec(tag="dialog", attrs={"open": ""}), {
        "source_rule": "modal:dialog-open",
    }),

    # ---- Scripting / metadata ------------------------------------------------
    ("scripting:script-external", ElementSpec(tag="script", attrs={"src": "/a.js"}), {
        "source_rule": "scripting:script-external",
        "observable_effects": {Effect.FETCH, Effect.EXECUTE},
        "not_exposure_views": {AgentView.AX_TREE},
    }),
    ("scripting:script-inline", ElementSpec(tag="script"), {
        "source_rule": "scripting:script-inline",
        "observable_effects": {Effect.EXECUTE},
    }),
    ("scripting:style", ElementSpec(tag="style"), {
        "source_rule": "scripting:style",
        "observable_effects": {Effect.APPLY_STYLE},
    }),
    ("scripting:link-stylesheet", ElementSpec(
        tag="link", attrs={"rel": "stylesheet", "href": "/s.css"},
    ), {
        "source_rule": "scripting:link-stylesheet",
        "observable_effects": {Effect.FETCH, Effect.APPLY_STYLE},
    }),
    ("scripting:link-preload", ElementSpec(
        tag="link", attrs={"rel": "preload", "href": "/p.js"},
    ), {
        "source_rule": "scripting:link-preload",
        "observable_effects": {Effect.FETCH},
    }),
    ("scripting:meta-og", ElementSpec(
        tag="meta", attrs={"property": "og:title", "content": "Test"},
    ), {
        "source_rule": "scripting:meta-og",
        "exposure_channels": {Channel.META_OG},
    }),
    ("scripting:meta-refresh", ElementSpec(
        tag="meta", attrs={"http-equiv": "refresh", "content": "5; url=/x"},
    ), {
        "source_rule": "scripting:meta-refresh",
        "observable_effects": {Effect.NAVIGATE_FRAME},
    }),
    ("scripting:title", ElementSpec(tag="title"), {
        "source_rule": "scripting:title",
        "exposure_channels": {Channel.META_OG},
    }),
    ("scripting:noscript", ElementSpec(tag="noscript"), {
        "source_rule": "scripting:noscript",
        "exposure_channels": {Channel.NOSCRIPT},
    }),

    # ---- Custom / web-components --------------------------------------------
    ("custom:custom-element", ElementSpec(tag="my-widget"), {
        "source_rule": "custom:element-unknown",
        "exposure_channels": {Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
    }),
    ("custom:template", ElementSpec(tag="template"), {
        "source_rule": "custom:template",
        "not_exposure_views": {AgentView.AX_TREE, AgentView.DOM_TEXT},
    }),
    ("custom:slot", ElementSpec(tag="slot"), {
        "source_rule": "custom:slot",
    }),
]


# ── Test runner ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "label,spec,expected",
    _TABLE,
    ids=[row[0] for row in _TABLE],
)
def test_table_row(label, spec, expected):
    cls = classify(spec)

    if "source_rule" in expected:
        assert cls.source_rule == expected["source_rule"], \
            f"{label}: source_rule mismatch (got {cls.source_rule!r}, want {expected['source_rule']!r})"

    if "authority_direct" in expected:
        assert expected["authority_direct"].issubset(cls.authority.direct), \
            f"{label}: missing direct authority {expected['authority_direct'] - cls.authority.direct}"

    if "authority_blocked" in expected:
        assert expected["authority_blocked"].issubset(cls.authority.blocked), \
            f"{label}: missing blocked authority {expected['authority_blocked'] - cls.authority.blocked}"

    if "authority_effective" in expected:
        assert expected["authority_effective"].issubset(cls.authority.effective), \
            f"{label}: missing effective authority"

    if "observable_effects" in expected:
        assert expected["observable_effects"].issubset(cls.effects.observable), \
            f"{label}: missing observable effects {expected['observable_effects'] - cls.effects.observable}"

    if "no_observable_effects" in expected:
        bad = expected["no_observable_effects"] & cls.effects.observable
        assert not bad, f"{label}: must NOT have observable effects {bad}"

    if "exposure_channels" in expected:
        assert expected["exposure_channels"].issubset(cls.exposure.channels), \
            f"{label}: missing exposure channels " \
            f"{expected['exposure_channels'] - cls.exposure.channels}"

    if "exposure_views" in expected:
        assert expected["exposure_views"].issubset(cls.exposure.visible_to), \
            f"{label}: missing exposure views " \
            f"{expected['exposure_views'] - cls.exposure.visible_to}"

    if "not_exposure_views" in expected:
        forbidden = expected["not_exposure_views"] & cls.exposure.visible_to
        assert not forbidden, \
            f"{label}: should NOT be visible to {forbidden}, but is"


def test_table_is_nonempty():
    assert len(_TABLE) >= 40, f"Coverage is shrinking: {len(_TABLE)} rows"
