"""Provenance-chain taint: is an element's content possibly third-party?

Centralizes which provenance fields contribute taint, so that every consumer
reads the whole chain: the creator and inserter, the parties of the third-party
URLs that scripts write to the element (``src``, ``href``, ``action``,
``data``) or that its creating script requested (``loads``), the scripts that
attached listeners (``listeners``), and the parties that modified its text
(``text_mods``) or attributes (``attr_mods``). ``unknown`` (a script-created
element we could not attribute) is never treated as clean: "we don't know who
made it" reads as *possibly untrusted* — fail closed.

Taint of an element's provenance = ANY of:
  - a ``3p:<host>`` party anywhere in the chain, or
  - an ``unknown`` party anywhere in the chain (unattributable, fail-closed), or
  - a third-party document scope.
"""

import re

# A party token looks like "3p:<host>/<path>#<hash>"; pull the host out.
_3P_RE = re.compile(r"3p:([a-zA-Z0-9.\-]+)")

# Provenance fields whose party tokens can introduce taint. `attr_mods` is a
# list of {attr, by} dicts and is handled separately.
_CHAIN_FIELDS = ("creator", "inserter", "loads", "listeners", "text_mods")


def _strings(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [x for x in items if isinstance(x, str)]


def chain_parties(prov: dict) -> list[str]:
    """Every party token across the whole provenance chain, including the
    content/attribute modifiers (``text_mods`` and ``attr_mods[*].by``)."""
    if not isinstance(prov, dict):
        return []
    out: list[str] = []
    for fld in _CHAIN_FIELDS:
        out.extend(_strings(prov.get(fld)))
    for am in prov.get("attr_mods") or []:
        if isinstance(am, dict):
            out.extend(_strings(am.get("by")))
    return out


def chain_3p_hosts(prov: dict) -> set[str]:
    """Distinct third-party eTLD+1 hosts named anywhere in the chain."""
    out: set[str] = set()
    for party in chain_parties(prov):
        out.update(_3P_RE.findall(party))
    return out


def has_unknown_party(prov: dict) -> bool:
    """True if any chain party is ``unknown`` (unattributable script content)."""
    return any(p == "unknown" for p in chain_parties(prov))


def is_provenance_tainted(prov: dict, doc_scope: "str | None" = None) -> bool:
    """Conservative taint predicate: a 3p host, an ``unknown`` party, or a 3p
    document scope all taint the element."""
    return bool(chain_3p_hosts(prov)) or has_unknown_party(prov) or doc_scope == "3p"
