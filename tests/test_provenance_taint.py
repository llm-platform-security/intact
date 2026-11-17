"""Tests that the taint DECISION (not just the _classify label) fails closed.

These pin the soundness invariant at the layer that actually makes the trust
decision: `unknown` creators and 3p `text_mods`/`attr_mods` must be treated as
tainted, otherwise the fail-closed labeling buys nothing downstream.
"""

import pytest

from intact.gentree.provenance_taint import (
    chain_3p_hosts, has_unknown_party, is_provenance_tainted,
)


# ── shared extractor ─────────────────────────────────────────────────────────

def test_unknown_creator_is_tainted():
    prov = {"creator": "unknown"}
    assert has_unknown_party(prov)
    assert is_provenance_tainted(prov, "1p")


def test_3p_text_mod_on_1p_element_is_tainted():
    # Text laundering: element made by 1p, but a 3p script wrote text into it.
    prov = {"creator": "1p:inline", "text_mods": ["3p:thirdparty.test"]}
    assert chain_3p_hosts(prov) == {"thirdparty.test"}
    assert is_provenance_tainted(prov, "1p")


def test_3p_attr_mod_is_tainted():
    prov = {"creator": "1p:inline", "attr_mods": [{"attr": "href", "by": "3p:evil.test"}]}
    assert chain_3p_hosts(prov) == {"evil.test"}
    assert is_provenance_tainted(prov, "1p")


def test_clean_1p_element_is_not_tainted():
    prov = {"creator": "1p:app.js", "text_mods": ["1p:app.js"]}
    assert not chain_3p_hosts(prov)
    assert not has_unknown_party(prov)
    assert not is_provenance_tainted(prov, "1p")


def test_listeners_and_loads_count():
    assert chain_3p_hosts({"listeners": ["3p:a.test"], "loads": ["src→3p:b.test"]}) \
        == {"a.test", "b.test"}
