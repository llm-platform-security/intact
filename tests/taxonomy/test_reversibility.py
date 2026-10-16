"""Coverage checks for taxonomy-owned reversibility metadata."""

import pytest

from intact.gentree.taxonomy import (
    Effect, EFFECT_REVERSIBILITY,
    classify_effects,
)


def test_every_effect_label_has_a_class_and_reason():
    assert set(EFFECT_REVERSIBILITY) == {label.value for label in Effect}
    for rule in EFFECT_REVERSIBILITY.values():
        assert rule["class"] in {"reversible", "irreversible", "undetermined"}
        assert rule["reason"]


@pytest.mark.parametrize("effects, expected", [
    ([], "undetermined"),
    (["dom-mutate"], "reversible"),
    (["dom-mutate", "send-request"], "irreversible"),
    (["post-message"], "undetermined"),
    (["dom-mutate", "post-message"], "undetermined"),
    (["navigate"], "undetermined"),
    (["navigate-frame"], "undetermined"),
    (["navigate", "navigate-frame"], "undetermined"),
    (["navigate", "navigate-frame", "send-request"], "irreversible"),
    (["post-message", "send-request"], "irreversible"),
])
def test_step_classification_uses_supported_effects(effects, expected):
    assert classify_effects(effects)["class"] == expected


def test_execute_exception_does_not_relabel_execution_itself():
    assert EFFECT_REVERSIBILITY["execute"]["class"] == "undetermined"
    assert classify_effects(["execute"])["class"] == "undetermined"
    assert classify_effects(["execute", "choose"])["class"] == "reversible"
    assert classify_effects(["execute", "choose", "submit"])["class"] == "undetermined"


@pytest.mark.parametrize("effects, expected", [
    (("choose", "dom-mutate", "apply-style", "storage-write"), "reversible"),
    (("send-request", "fetch", "external-handler"), "irreversible"),
    (("submit", "navigate", "execute", "post-message", "navigate-frame", "render-frame"), "undetermined"),
])
def test_original_effect_categories(effects, expected):
    for effect in effects:
        assert EFFECT_REVERSIBILITY[effect]["class"] == expected
        assert classify_effects([effect])["class"] == expected


@pytest.mark.parametrize("labels", [["not-an-effect"], ["click"], [None], [["dom-mutate"]], "dom-mutate"])
def test_taxonomy_composition_rejects_unknown_or_malformed_labels(labels):
    with pytest.raises(ValueError):
        classify_effects(labels)
