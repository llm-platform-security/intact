"""Orchestrate the per-element classification pass.

Called from BrowserSession.capture(). Issues one CDP DOMSnapshot call,
turns its flat node list into ElementSpec instances via spec_builder,
runs the classifier on each, and attaches the result to the state dict
under `state["classification"]`.

Failures degrade gracefully: a snapshot error leaves an empty
classification map but doesn't raise. The existing capture pipeline
(provenance + AX tree) keeps working regardless.
"""

from typing import Any

from intact.gentree.spec_builder import (
    COMPUTED_STYLE_NAMES, build_dom_records, build_specs_from_snapshot,
)
from intact.gentree.taxonomy.classifier import classify
from intact.gentree.taxonomy.types import ElementClassification


def attach_classifications(state: dict[str, Any], cdp: Any) -> dict[str, Any]:
    """Populate state["classification"] and state["dom_records"].

    - state["classification"]: {bni → ElementClassification} — full DOM-wide.
    - state["dom_records"]: list of dicts in DOM-tree pre-order, each
      {bni, tag, attrs, depth, parent_bni, doc_index}. The DOM-shaped
      backbone that `unified_view.build_unified_elements` walks.

    One DOMSnapshot call feeds both. Per-element classify() failures are
    caught so one bad element doesn't strand the rest.
    """
    classifications: dict[int, ElementClassification] = {}
    dom_records: list[dict[str, Any]] = []

    try:
        snapshot = cdp.send(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles":                COMPUTED_STYLE_NAMES,
                "includePaintOrder":             False,
                "includeDOMRects":               False,
                "includeBlendedBackgroundColors": False,
                "includeTextColorOpacities":     False,
            },
        )
        specs = build_specs_from_snapshot(snapshot)
        for bni, spec in specs.items():
            try:
                classifications[bni] = classify(spec)
            except Exception:
                continue
        dom_records = build_dom_records(snapshot)
    except Exception as e:
        print(f"  classification pass failed: {e}")

    state["classification"] = classifications
    state["dom_records"]    = dom_records
    return state
