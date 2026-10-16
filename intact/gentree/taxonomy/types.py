"""Per-element classification result types."""

from dataclasses import dataclass, field

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect


@dataclass
class AuthoritySet:
    """Operations on an element, partitioned by source.

    - direct:    the element's own affordances (from its tag + attrs).
    - inherited: added by wrappers (e.g. <a> wrapping <img> extends click/focus).
    - blocked:   removed by ancestor flags / computed style (disabled, inert,
                 sandbox, pointer-events: none).
    """
    direct:    set[Authority] = field(default_factory=set)
    inherited: set[Authority] = field(default_factory=set)
    blocked:   set[Authority] = field(default_factory=set)

    @property
    def effective(self) -> set[Authority]:
        """Authorities actually exercisable: (direct ∪ inherited) − blocked."""
        return (self.direct | self.inherited) - self.blocked


@dataclass
class EffectSet:
    """Effects of exercising authority or of the browser parsing the element.

    Classifies browser operations and covered control-state changes supported
    by element semantics, including structured disclosure declarations. Static
    labels describe potential effects, not verified execution or effects of
    every available interaction. For example, clicking a select may only open
    its picker; choosing a value requires actually selecting an option. A form
    input's submit effect requires implicit submission (such as Enter), not
    ordinary typing. The field name
    ``observable`` is retained for compatibility; business-consequence inference
    lives in a separate downstream module that consumes this taxonomy as input.
    """
    observable: set[Effect] = field(default_factory=set)


@dataclass
class Exposure:
    """Content channels exposed and which agent views can see them."""
    channels:   set[Channel]   = field(default_factory=set)
    visible_to: set[AgentView] = field(default_factory=set)


@dataclass
class ElementClassification:
    """The full per-element classification result.

    `source_rule` identifies which Rule produced the base classification (for
    debugging). `composition_notes` records each composition rule that fired
    during the second pass, in order.
    """
    authority:         AuthoritySet
    effects:           EffectSet
    exposure:          Exposure
    source_rule:       str       = ""
    composition_notes: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "ElementClassification":
        """Default for elements that match no rule (unknown / catch-all)."""
        return cls(
            authority=AuthoritySet(),
            effects=EffectSet(),
            exposure=Exposure(
                channels={Channel.BODY_TEXT},
                visible_to={AgentView.AX_TREE, AgentView.DOM_TEXT},
            ),
            source_rule="fallback:unknown",
        )
