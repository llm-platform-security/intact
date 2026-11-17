"""Rule data class — the declarative entry for the classifier.

Each `rules/<family>.py` exports a list `RULES: list[Rule]`. The classifier
collects all rules from every family, filters by `match()`, and picks the
highest-`specificity` candidate. Ties broken by registration order
(earlier rule wins).

The three axis fields can be either:
- A pre-built `AuthoritySet` / `EffectSet` / `Exposure` (most rules), OR
- A `Callable[[ElementSpec], <set>]` that derives the axis from the spec
  at classification time. This lets form / input-submit rules vary their
  inferred effects based on action/method.
"""

from dataclasses import dataclass
from typing import Callable, Union

from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.types import AuthoritySet, EffectSet, Exposure


AuthorityFn = Union[AuthoritySet, Callable[[ElementSpec], AuthoritySet]]
EffectFn    = Union[EffectSet,    Callable[[ElementSpec], EffectSet]]
ExposureFn  = Union[Exposure,     Callable[[ElementSpec], Exposure]]


@dataclass(frozen=True)
class Rule:
    """A single classification rule.

    Specificity convention:
        tag-only match:             1
        tag + 1 attr predicate:     2
        tag + 2 attr predicates:    3
        tag + scheme-specific URL:  4
    The classifier picks max-specificity; ties broken by registration order.
    """
    name:        str
    match:       Callable[[ElementSpec], bool]
    authority:   AuthorityFn
    effects:     EffectFn
    exposure:    ExposureFn
    specificity: int = 1

    def __hash__(self) -> int:
        return hash(self.name)
