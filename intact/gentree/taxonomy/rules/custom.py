"""Web components / shadow DOM / template / slot.

Custom elements (any tag with a hyphen, e.g. <my-widget>) cannot be classified
statically — their capability is defined by their JS class. We return an
"unknown:custom-element" classification that consumers can refine via
runtime observation (event listeners, fired requests) or a component manifest.

<template> content is inert until cloned. <slot> is shadow-DOM routing glue
and has no behavior of its own.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_custom_element(s: ElementSpec) -> bool:
    """Custom elements have a hyphen in the tag name (HTML spec rule)."""
    return "-" in s.tag and s.tag not in ("annotation-xml",)  # one MathML exception


def _is_template(s): return s.tag == "template"
def _is_slot(s):     return s.tag == "slot"


RULES: list[Rule] = [
    Rule(
        name="custom:element-unknown",
        match=_is_custom_element,
        # Optimistic baseline — gives static-text exposure so the agent can
        # still read body text, but no authority claims. Runtime observation
        # (listener detection, request correlation) can upgrade this later.
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=1,
    ),
    Rule(
        name="custom:template",
        match=_is_template,
        # Template contents are inert in the live tree.
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=1,
    ),
    Rule(
        name="custom:slot",
        match=_is_slot,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Slot is structural; meaningful content is in distributed children.
        exposure=Exposure(channels=set(), visible_to=_AX),
        specificity=1,
    ),
]
