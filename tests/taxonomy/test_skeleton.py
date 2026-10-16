"""Skeleton sanity tests — exercises the shape of enums/types/spec only.

No rule content or classifier logic tested here — those live in
test_classifier.py and the other taxonomy tests.
"""

from intact.gentree.taxonomy import (
    AgentView,
    Authority,
    AuthoritySet,
    Channel,
    Effect,
    EffectSet,
    ElementClassification,
    ElementSpec,
    Exposure,
)


def test_enum_values_are_kebab_case_strings():
    """The string values are what serialize cleanly to JSON / appear in test logs."""
    assert Authority.CLICK.value == "click"
    assert Authority.CHANGE_VALUE.value == "change-value"
    assert Effect.SEND_REQUEST.value == "send-request"
    assert Effect.NAVIGATE_FRAME.value == "navigate-frame"
    assert Channel.BODY_TEXT.value == "body-text"
    assert Channel.ACCESSIBLE_NAME.value == "accessible-name"
    assert AgentView.AX_TREE.value == "ax-tree"


def test_authority_set_effective_subtracts_blocked():
    aset = AuthoritySet(
        direct={Authority.CLICK, Authority.FOCUS},
        inherited={Authority.POPUP},
        blocked={Authority.FOCUS},
    )
    assert aset.effective == {Authority.CLICK, Authority.POPUP}


def test_authority_set_effective_combines_direct_and_inherited():
    aset = AuthoritySet(
        direct={Authority.CLICK},
        inherited={Authority.POPUP, Authority.HOVER},
    )
    assert aset.effective == {Authority.CLICK, Authority.POPUP, Authority.HOVER}


def test_authority_set_default_is_empty():
    aset = AuthoritySet()
    assert aset.direct == set()
    assert aset.effective == set()


def test_effect_set_holds_observable_effects():
    es = EffectSet(observable={Effect.SEND_REQUEST, Effect.NAVIGATE_FRAME})
    assert Effect.SEND_REQUEST in es.observable
    assert Effect.NAVIGATE_FRAME in es.observable
    assert Effect.EXECUTE not in es.observable


def test_exposure_channels_and_views():
    exp = Exposure(
        channels={Channel.BODY_TEXT, Channel.ACCESSIBLE_NAME},
        visible_to={AgentView.AX_TREE},
    )
    assert Channel.BODY_TEXT in exp.channels
    assert AgentView.AX_TREE in exp.visible_to
    assert AgentView.DOM_TEXT not in exp.visible_to


def test_element_classification_empty_fallback():
    e = ElementClassification.empty()
    assert e.authority.effective == set()
    assert e.effects.observable == set()
    # Fallback still exposes body-text — text content reaches the agent.
    assert Channel.BODY_TEXT in e.exposure.channels
    assert AgentView.AX_TREE in e.exposure.visible_to
    assert e.source_rule == "fallback:unknown"
    assert e.composition_notes == []


def test_element_spec_default_collections():
    spec = ElementSpec(tag="p")
    assert spec.tag == "p"
    assert spec.attrs == {}
    assert spec.role is None
    assert spec.ancestors == []
    assert spec.computed_style_flags == {}
    assert spec.runtime_listeners == []


def test_element_spec_with_ancestors():
    parent = ElementSpec(tag="form", attrs={"action": "/submit"})
    spec = ElementSpec(
        tag="button",
        attrs={"type": "submit"},
        ancestors=[parent],
    )
    assert spec.ancestors[0].tag == "form"
    assert spec.ancestors[0].attrs["action"] == "/submit"
