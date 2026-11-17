"""Classifier core: ElementSpec → ElementClassification.

Two-pass model:
1. `classify_base(spec)` — pick best-matching rule, return the rule's axes.
2. `classify(spec)` — base + composition pass (composition.py applies the
   ancestor / computed-style rules).

Public callers should use `classify()`. `classify_base()` exists for tests
that want to isolate base rules from composition.
"""

from intact.gentree.taxonomy.node_spec import ElementSpec
from intact.gentree.taxonomy.rules import all_rules
from intact.gentree.taxonomy.rules._base import Rule
from intact.gentree.taxonomy.types import (
    AuthoritySet,
    EffectSet,
    ElementClassification,
    Exposure,
)


_RULES_CACHE: list[Rule] | None = None


def _get_rules() -> list[Rule]:
    """Lazily fetch and cache the full rule list.

    Rules are pure data, registration order is stable, so caching is safe
    for the process lifetime. Tests that need a clean slate call
    `_reset_rule_cache()`.
    """
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = all_rules()
    return _RULES_CACHE


def _reset_rule_cache() -> None:
    """For tests only — forces re-aggregation on next classify call."""
    global _RULES_CACHE
    _RULES_CACHE = None


def _resolve(spec: ElementSpec, value):
    """Evaluate a rule axis: it's either a static set or a callable on spec."""
    return value(spec) if callable(value) else value


def classify_base(spec: ElementSpec) -> ElementClassification:
    """Base classification — rule match only, no composition pass."""
    candidates: list[Rule] = []
    for rule in _get_rules():
        try:
            if rule.match(spec):
                candidates.append(rule)
        except Exception:
            # A buggy match lambda must not crash the whole classifier.
            continue

    if not candidates:
        return ElementClassification.empty()

    # Most specific wins; first-registered breaks ties.
    winner = max(candidates, key=lambda r: r.specificity)
    return ElementClassification(
        authority=_resolve(spec, winner.authority),
        effects=_resolve(spec, winner.effects),
        exposure=_resolve(spec, winner.exposure),
        source_rule=winner.name,
    )


def classify(spec: ElementSpec) -> ElementClassification:
    """Full classification: base + composition."""
    base = classify_base(spec)
    try:
        from intact.gentree.taxonomy.composition import apply_composition
        return apply_composition(base, spec)
    except ImportError:
        return base
