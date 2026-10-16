"""Reversibility metadata for taxonomy Effects and predicted Effect sets.

This is label metadata, not a new per-element axis or a runtime guarantee.
A planned step is classified from its supported Effects. Interaction labels
do not receive reversibility annotations.

The paper's appendix gives the rationale for each Effect's category.

The paper uses Local change, External effect, and Undetermined for the
respective class keys reversible, irreversible, and undetermined. The keys
remain stable for compatibility; the category names express qualitative
assessments, not runtime guarantees.
"""

from intact.gentree.taxonomy.enums import Effect


EFFECT_REVERSIBILITY = {
    "choose": {"class": "reversible", "reason": "Restore the previous local option selection under the stated local-state assumptions."},
    "submit": {"class": "undetermined", "reason": "Submission alone does not establish transmission or other downstream consequences."},
    "navigate": {"class": "undetermined", "reason": "Navigation alone does not establish external communication or whether the prior state can be restored."},
    "send-request": {"class": "irreversible", "reason": "An external request cannot be recalled after it is sent."},
    "fetch": {"class": "irreversible", "reason": "Resource retrieval may communicate externally; an external request cannot be recalled."},
    "external-handler": {"class": "irreversible", "reason": "The action hands off outside the controlled browser context."},
    "dom-mutate": {"class": "reversible", "reason": "Restore the previous DOM content or covered control state under the stated local-state assumptions."},
    "apply-style": {"class": "reversible", "reason": "Restore the previous local style state under the stated local-state assumptions."},
    "storage-write": {"class": "reversible", "reason": "Restore previous stored values, or remove newly created entries, under the stated local-state assumptions."},
    "execute": {"class": "undetermined", "reason": "Script execution alone does not identify its consequences.",
                "with_only_concrete_local_effects": "reversible"},
    "post-message": {"class": "undetermined", "reason": "Messaging without a resolved recipient boundary does not establish whether its consequences are within recoverable local state."},
    "navigate-frame": {"class": "undetermined", "reason": "A frame location or document change alone does not establish external communication or whether the prior state can be restored."},
    "render-frame": {"class": "undetermined", "reason": "Frame rendering alone does not establish its external consequences."},
}

REVERSIBILITY_SCOPE = (
    "Classification covers model-predicted effects only. Reversible means the covered local state can be restored, "
    "assuming prior local state is recoverable and no unlisted external consequences occur. "
    "Undetermined means the label lacks enough information to decide; its consequences may be reversible or irreversible. "
    "Irreversible means a predicted Effect entails communication or handoff outside recoverable local state under this analysis, possibly conditionally; "
    "no class establishes observed execution or a runtime guarantee."
)


def classify_effects(labels):
    """Combine supported Effect labels under the taxonomy's reversibility policy.

    Irreversible Effects take precedence over unresolved Effects, then local
    Effects. Execution with only concrete local Effects uses the explicit
    metadata exception; execution alone and an empty set remain undetermined.
    Do not pass every potential Effect on an element as if each were triggered
    by a particular Interaction.
    """
    if isinstance(labels, (str, bytes)):
        raise ValueError("Effect labels must be an iterable of canonical labels.")
    values = list(labels)
    vocabulary = {item.value for item in Effect}
    if any(not isinstance(label, str) or label not in vocabulary for label in values):
        raise ValueError("Effect labels must contain only canonical labels.")
    effects = set(values)
    irreversible = sorted(label for label in effects if EFFECT_REVERSIBILITY[label]["class"] == "irreversible")
    local = sorted(label for label in effects if EFFECT_REVERSIBILITY[label]["class"] == "reversible")
    qualified = {
        label for label in effects
        if EFFECT_REVERSIBILITY[label].get("with_only_concrete_local_effects") == "reversible"
    }
    unresolved = sorted(effects - set(irreversible) - set(local) - qualified)
    if irreversible:
        classification = "irreversible"
        reasons = [EFFECT_REVERSIBILITY[label]["reason"] for label in irreversible]
    elif unresolved:
        classification = "undetermined"
        reasons = [EFFECT_REVERSIBILITY[label]["reason"] for label in unresolved]
    elif local:
        classification = "reversible"
        reasons = ["Only concrete local changes are predicted; prior state must be recoverable."]
        if "execute" in effects:
            reasons.append("Execution is classified through the listed local consequences; unlisted script effects are not ruled out.")
    else:
        classification = "undetermined"
        reasons = [EFFECT_REVERSIBILITY[label]["reason"] for label in sorted(qualified)] or [
            "No effects were identified; this does not establish that the interaction is reversible."
        ]
    return {"class": classification, "reasons": reasons, "labels": sorted(effects), "scope": REVERSIBILITY_SCOPE}
