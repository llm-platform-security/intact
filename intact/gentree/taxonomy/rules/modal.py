"""Modal / disclosure elements: <details>, <summary>, <dialog>.

<details> body is hidden until [open]. <summary> is the toggle handle.
<dialog> uses showModal() / show() (JS-driven) — we classify based on
the [open] attribute presence at parse time.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_summary(s): return s.tag == "summary"
def _is_details(s): return s.tag == "details"
def _is_details_open(s): return s.tag == "details" and "open" in s.attrs
def _is_dialog(s): return s.tag == "dialog"
def _is_dialog_open(s): return s.tag == "dialog" and "open" in s.attrs


def _summary_effects(s: ElementSpec) -> EffectSet:
    # Native summary activation toggles its parent details' open attribute.
    # Ancestors are nearest first. Sibling order is unavailable in ElementSpec,
    # so this assumes a summary under details is its operative summary child.
    if s.ancestors and s.ancestors[0].tag == "details":
        return EffectSet(observable={Effect.DOM_MUTATE})
    return EffectSet()


RULES: list[Rule] = [
    Rule(
        name="modal:summary",
        match=_is_summary,
        authority=AuthoritySet(
            direct={Authority.CLICK, Authority.FOCUS, Authority.TOGGLE},
        ),
        effects=_summary_effects,
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),
    Rule(
        name="modal:details-open",
        match=_is_details_open,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # When open, content is in AX.
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),
    Rule(
        name="modal:details",
        match=_is_details,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Closed details — only the <summary> is visible.
        exposure=Exposure(
            channels={Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=1,
    ),
    Rule(
        name="modal:dialog-open",
        match=_is_dialog_open,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(
            channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
            visible_to=_AX,
        ),
        specificity=2,
    ),
    Rule(
        name="modal:dialog",
        match=_is_dialog,
        authority=AuthoritySet(),
        effects=EffectSet(),
        # Closed dialog: not in AX until showModal().
        exposure=Exposure(channels=set(), visible_to=set()),
        specificity=1,
    ),
]
