"""Static HTML element taxonomy for agentic-browsing PI defense work.

Three independent per-element axes:
- Authority: operations the agent can be told to perform on an element
- Effect:    what happens (observable or inferred) if those fire
- Channel:   content channels through which the element reaches the agent

Plus AgentView (perception model) and the ElementSpec input shape.

Provenance integration, coupling relations, and the defense predicates that
join across elements are intentionally out of scope here — they consume the
classification result but are built in separate modules.
"""

from intact.gentree.taxonomy.enums import AgentView, Authority, Channel, Effect
from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.reversibility import (
    EFFECT_REVERSIBILITY,
    classify_effects,
)
from intact.gentree.taxonomy.types import (
    AuthoritySet,
    EffectSet,
    ElementClassification,
    Exposure,
)

__all__ = [
    "AgentView",
    "Authority",
    "AuthoritySet",
    "Channel",
    "Effect",
    "EffectSet",
    "EFFECT_REVERSIBILITY",
    "classify_effects",
    "ElementClassification",
    "ElementSpec",
    "Exposure",
]
