"""The markup view: what the model sees of each element.

_render_element renders an element as its id ([bni=N]), its tag, the
attributes in VISIBLE_ATTRS, and its direct text, with the text and each
attribute value cut to a fixed length. The bodies of scripts, styles,
templates, and noscript elements are dropped. The view carries no
provenance, capability labels, or document scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Attributes a browsing agent can actually perceive (visible text, accessible
# name/description, link/media targets, form semantics). Deliberately excludes
# data-* and other cloaked channels.
VISIBLE_ATTRS: tuple[str, ...] = (
    "href", "src", "alt", "aria-label", "aria-description", "aria-describedby",
    "title", "role", "placeholder", "value", "type", "name", "content", "label",
)

# Tags whose bodies are never useful to the agent and dominate size.
_DROP_BODY_TAGS = {"script", "style", "template", "noscript"}

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")
# attrs whose value is itself a navigable/loadable target token
_TARGET_ATTRS = ("href", "src")


def _strip_url(u: str) -> str:
    return u.rstrip(".,;:!?)]}\"'")


@dataclass
class RenderedElement:
    """Exactly what was rendered into the view for one bni (post-truncation —
    i.e. the bytes the LLM actually saw), plus the target tokens extracted from
    it. Built at input time; the LLM never influences it."""

    bni: int
    tag: str
    text: str
    attrs: dict[str, str] = field(default_factory=dict)
    urls: list[str] = field(default_factory=list)


# ── rendering ────────────────────────────────────────────────────────────────


def _render_element(e: dict, max_text: int = 400, max_attr: int = 300):
    """Return (line, RenderedElement) or (None, None) if nothing visible."""
    tag = e.get("tag", "")
    text = (e.get("text") or "").strip()
    attrs = e.get("attrs") or {}

    if tag in _DROP_BODY_TAGS:
        text = ""

    rendered_attrs: dict[str, str] = {}
    attr_bits = []
    for k in VISIBLE_ATTRS:
        v = attrs.get(k)
        if not v:
            continue
        v = str(v)
        if len(v) > max_attr:
            v = v[:max_attr] + "…"
        rendered_attrs[k] = v
        attr_bits.append(f'{k}="{v}"')

    if not attr_bits and not text:
        return None, None

    if text and len(text) > max_text:
        text = text[:max_text] + "…"

    # Extract target tokens from exactly what we render (text + visible attrs).
    urls: list[str] = [_strip_url(u) for u in _URL_RE.findall(text)]
    for k in _TARGET_ATTRS:
        v = rendered_attrs.get(k)
        if v:
            urls.extend(_strip_url(u) for u in _URL_RE.findall(v))
            # a bare href/src value is itself a target token even if relative
            if not v.lower().startswith(("javascript:", "data:")):
                urls.append(_strip_url(v.strip()))
    urls = [u for u in dict.fromkeys(urls) if u]

    bni = e.get("bni")
    attr_str = (" " + " ".join(attr_bits)) if attr_bits else ""
    line = f'[bni={bni}] <{tag}{attr_str}>'
    if text:
        line += f' "{text}"'
    rec = RenderedElement(bni=bni, tag=tag, text=text, attrs=rendered_attrs, urls=urls)
    return line, rec
