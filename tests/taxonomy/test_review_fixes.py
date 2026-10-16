"""Regression tests for corrections to the authority and effect labels. Each
test pins a specific over/under-claim fix so it can't silently regress. Uses
full `classify` (base + composition).
"""

from intact.gentree.taxonomy import Authority, Effect, ElementSpec
from intact.gentree.taxonomy.classifier import classify


def _auth(spec):
    return set(classify(spec).authority.effective)


def _eff(spec):
    return set(classify(spec).effects.observable)


_FORM = ElementSpec(tag="form", attrs={"action": "/s"})
_A = ElementSpec(tag="a", attrs={"href": "/x"})


# ── bare buttons don't EXECUTE without a handler ─────────────────────────────
def test_bare_button_has_no_execute():
    assert Effect.EXECUTE not in _eff(ElementSpec(tag="button"))
    assert Effect.EXECUTE not in _eff(ElementSpec(tag="button", attrs={"type": "button"}))
    assert Effect.EXECUTE not in _eff(ElementSpec(tag="input", attrs={"type": "button"}))


def test_button_with_handler_executes():
    assert Effect.EXECUTE in _eff(ElementSpec(tag="button", attrs={"onclick": "x()"}))
    assert Effect.EXECUTE in _eff(
        ElementSpec(tag="input", attrs={"type": "button", "onclick": "x()"}))


# ── textarea never submits; text inputs submit only in a form ────────────────
def test_textarea_no_submit():
    assert Effect.SUBMIT not in _eff(ElementSpec(tag="textarea"))


def test_text_input_submit_is_form_conditional():
    assert Effect.SUBMIT not in _eff(ElementSpec(tag="input", attrs={"type": "text"}))
    assert Effect.SUBMIT in _eff(
        ElementSpec(tag="input", attrs={"type": "text"}, ancestors=[_FORM]))
    # password too
    assert Effect.SUBMIT not in _eff(ElementSpec(tag="input", attrs={"type": "password"}))
    assert Effect.SUBMIT in _eff(
        ElementSpec(tag="input", attrs={"type": "password"}, ancestors=[_FORM]))


# ── input[type=image] fetch is src-gated ─────────────────────────────────────
def test_input_image_fetch_requires_src():
    assert Effect.FETCH not in _eff(ElementSpec(tag="input", attrs={"type": "image"}))
    assert Effect.FETCH in _eff(
        ElementSpec(tag="input", attrs={"type": "image", "src": "//x"}))


# ── ARIA role remap preserves action/navigation effects ─────────────────────
def test_role_remap_adds_effects():
    assert _eff(ElementSpec(tag="div", attrs={"role": "checkbox"})) == {Effect.DOM_MUTATE}
    assert _eff(ElementSpec(tag="div", attrs={"role": "switch"})) == {Effect.DOM_MUTATE}
    assert _eff(ElementSpec(tag="div", attrs={"role": "link"})) == {
        Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}
    assert _eff(ElementSpec(tag="div", attrs={"role": "button"})) == {Effect.EXECUTE}
    assert _eff(ElementSpec(tag="div", attrs={"role": "menuitem"})) == {Effect.EXECUTE}


# ── wrapping anchor inherits the anchor's effects, scheme-aware ───────────────
def test_wrapping_anchor_inherits_effects():
    span_in_a = ElementSpec(tag="span", ancestors=[_A])
    assert Authority.CLICK in _auth(span_in_a)
    assert _eff(span_in_a) == {Effect.NAVIGATE, Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME}
    # scheme-specific
    mailto = ElementSpec(tag="span",
                         ancestors=[ElementSpec(tag="a", attrs={"href": "mailto:x@y.z"})])
    assert _eff(mailto) == {Effect.EXTERNAL_HANDLER}
    assert Effect.NAVIGATE not in _eff(mailto)
    js = ElementSpec(tag="span",
                     ancestors=[ElementSpec(tag="a", attrs={"href": "javascript:x()"})])
    assert _eff(js) == {Effect.EXECUTE}
    dl = ElementSpec(tag="span",
                     ancestors=[ElementSpec(tag="a", attrs={"href": "/f", "download": ""})])
    assert _eff(dl) == {Effect.SEND_REQUEST}


# ── wrapping anchor does not make non-rendered descendants clickable ─────────
def test_wrapping_anchor_skips_non_rendered_descendants():
    # metadata/scripting content generates no box and can't receive a click, so
    # a wrapping <a href> must not grant it click authority or the
    # anchor's navigation effects (that was a spurious over-claim).
    for tag in ("script", "style", "template", "meta", "link", "title", "noscript"):
        spec = ElementSpec(tag=tag, ancestors=[_A])
        auth = _auth(spec)
        assert Effect.NAVIGATE not in _eff(spec), tag
        assert Authority.CLICK not in auth, tag
        assert Effect.NAVIGATE_FRAME not in _eff(spec), tag
    # control: a rendered descendant still inherits from the same anchor
    assert Effect.NAVIGATE in _eff(ElementSpec(tag="span", ancestors=[_A]))
    # the element keeps its OWN base effects (a script still fetches/executes)
    assert Effect.FETCH in _eff(ElementSpec(tag="script", attrs={"src": "//x"}, ancestors=[_A]))


# ── link rels and meta refresh ───────────────────────────────────────────────
def test_link_icon_fetches():
    assert _eff(ElementSpec(tag="link", attrs={"rel": "icon", "href": "//x"})) == {Effect.FETCH}


def test_connection_hint_links_do_not_fetch():
    for rel in ("dns-prefetch", "preconnect"):
        assert _eff(ElementSpec(tag="link", attrs={"rel": rel, "href": "//x"})) == set()
    for rel in ("preload", "prefetch", "modulepreload"):
        assert Effect.FETCH in _eff(ElementSpec(tag="link", attrs={"rel": rel, "href": "//x"}))


def test_meta_refresh_sends_request():
    eff = _eff(ElementSpec(tag="meta",
                           attrs={"http-equiv": "refresh", "content": "0;url=/x"}))
    assert eff == {Effect.NAVIGATE_FRAME, Effect.SEND_REQUEST}


# ── sandboxed iframe drops post-message unless allow-scripts ──────────────────
def test_sandbox_iframe_blocks_post_message():
    blocked = _eff(ElementSpec(tag="iframe", attrs={"src": "//x", "sandbox": ""}))
    assert Effect.POST_MESSAGE not in blocked
    assert Effect.RENDER_FRAME in blocked and Effect.FETCH in blocked
    allowed = _eff(ElementSpec(tag="iframe",
                               attrs={"src": "//x", "sandbox": "allow-scripts"}))
    assert Effect.POST_MESSAGE in allowed
    # an unsandboxed iframe keeps the channel
    assert Effect.POST_MESSAGE in _eff(ElementSpec(tag="iframe", attrs={"src": "//x"}))
