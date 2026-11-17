"""Table elements: structural read-only.

Tables become "grid" in ARIA but the elements themselves are not interactive
unless contenteditable (handled by composition.py's inherited-contenteditable rule
on the parent's static base classification — but td/th aren't in the static
tag set, so we cover them here).
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


_TABLE_TAGS = frozenset({
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "caption", "col", "colgroup",
})

_AX = {AgentView.AX_TREE, AgentView.DOM_TEXT}


def _is_table_cell_with_contenteditable(s: ElementSpec) -> bool:
    if s.tag not in ("td", "th"):
        return False
    if "contenteditable" not in s.attrs:
        return False
    return s.attrs["contenteditable"].lower() in ("", "true", "plaintext-only")


def _is_table(s: ElementSpec) -> bool:
    return s.tag in _TABLE_TAGS


RULES: list[Rule] = [
    Rule(
        name="table:cell-contenteditable",
        match=_is_table_cell_with_contenteditable,
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
        name="table:base",
        match=_is_table,
        authority=AuthoritySet(),
        effects=EffectSet(),
        exposure=Exposure(channels={Channel.BODY_TEXT}, visible_to=_AX),
        specificity=1,
    ),
]
