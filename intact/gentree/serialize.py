"""JSON serialization for the unified per-page representation.

Turns `state["elements"]` (a list of mixed Python dicts + ElementClassification
objects) into a fully JSON-friendly structure with stable enum-name strings.

Schema (one entry per DOM element, document-tree pre-order):

    {
        "bni":         int,
        "tag":         str,
        "attrs":       {str: str},
        "text":        str,           # OPTIONAL — present when the element has
                                       # non-whitespace direct text-node children.
                                       # Direct text only: <p>Hi <b>x</b>!</p>
                                       # gives the <p> text "Hi !" and the <b>
                                       # text "x" on its own record. Captures
                                       # inline <script>/<style> bodies too.
        "depth":       int,
        "parent_bni":  int | null,
        "doc_index":   int,
        "document":    {"url": str, "scope": "1p" | "3p"},
        "ax": {
            "in_tree":    bool,
            "node_id":    str | null,
            "role":       str | null,
            "name":       str | null,
            "description": str | null,
            "properties": {str: any} | null,
            "ignored":    bool | null
        },
        "classification": {
            "source_rule": str,
            "authority":   {"direct": [str], "inherited": [str], "blocked": [str], "effective": [str]},
            "effects":     {"observable": [str]},
            "exposure":    {"channels": [str], "visible_to": [str]},
            "composition_notes": [str]
        } | null,
        "provenance": {"creator": str, "via": str | null, "loads": [str], "listeners": [str], ...} | null,
                        # creator ∈ {"1p:...", "3p:...", "unknown"}; "unknown" = script-created
                        # but unattributable (fail-closed, never silently 1p). null = parser-created.
        "delivery_3p": [                # OPTIONAL — only when non-empty.
            {"attr": str, "host": str}   # 3p hosts the element's URL-bearing
        ],                               # attrs point at (src/href/data/
                                         # action/formaction/poster/cite/
                                         # srcset). Independent of who
                                         # CREATED the element — captures
                                         # parser-static pixel trackers,
                                         # declined-iframe shells, and
                                         # initial <script src=3p> that
                                         # would otherwise be invisible
                                         # to provenance.creator grouping.
    }

Top-level wrapper:

    {
        "url":         str,
        "taxonomy_version": str,       # version of the classification axes
        "captured_at": ISO-8601 str,
        "element_count": int,
        "frames":      [               # site-isolated (out-of-process) iframes
            {"segment": int,           #   their element bnis are
             "url": str,               #   segment * 1e9 + local id
             "owner_bni": int | None,  # the <iframe> element embedding it
             "doc_index": int}         # first doc_index of its documents
        ],
        "uncaptured_frames": [         # isolated frames the capture could not
            {"target_id": str, "url": str}   # reach (should be empty)
        ],
        "capture":     {               # crawl status ({} when not recorded)
            "status": "ok" | "error" | "blocked",
            "requested_url": str, "final_url": str, "title": str,
            "cross_site_redirect": bool,   # provenance labeled vs final site
            "attempts": int
        },
        "elements":    [ ... ]
    }
"""

from datetime import datetime, timezone
from typing import Any

from intact.gentree.taxonomy import ElementClassification
from intact.gentree.taxonomy.enums import TAXONOMY_VERSION


def _sorted_values(values) -> list[str]:
    """Convert a set of str-enum members to a sorted list of their string values."""
    if not values:
        return []
    return sorted(v.value for v in values)


def _serialize_classification(cls: ElementClassification | None) -> dict | None:
    if cls is None:
        return None
    return {
        "source_rule": cls.source_rule,
        "authority": {
            "direct":    _sorted_values(cls.authority.direct),
            "inherited": _sorted_values(cls.authority.inherited),
            "blocked":   _sorted_values(cls.authority.blocked),
            "effective": _sorted_values(cls.authority.effective),
        },
        "effects": {
            "observable": _sorted_values(cls.effects.observable),
        },
        "exposure": {
            "channels":   _sorted_values(cls.exposure.channels),
            "visible_to": _sorted_values(cls.exposure.visible_to),
        },
        "composition_notes": list(cls.composition_notes),
    }


def _serialize_ax(entry: dict) -> dict:
    in_tree = bool(entry.get("ax_in_tree", False))
    if not in_tree:
        return {
            "in_tree":     False,
            "node_id":     None,
            "role":        None,
            "name":        None,
            "description": None,
            "properties":  None,
            "ignored":     None,
        }
    return {
        "in_tree":     True,
        "node_id":     entry.get("ax_node_id"),
        "role":        entry.get("role", ""),
        "name":        entry.get("name", ""),
        "description": entry.get("description", ""),
        "properties":  dict(entry.get("properties", {})),
        "ignored":     bool(entry.get("ignored", False)),
    }


def _serialize_document(entry: dict) -> dict:
    """The document field tells the consumer which HTTP response delivered
    these bytes — kept structured rather than packed into the creator string."""
    doc = entry.get("document") or {}
    return {
        "url":   doc.get("url", "") or "",
        "scope": doc.get("scope", "1p"),
    }


def serialize_element(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert one unified element record into a JSON-friendly dict."""
    out: dict[str, Any] = {
        "bni":            entry["bni"],
        "tag":            entry.get("tag", ""),
        "attrs":          dict(entry.get("attrs", {})),
        "depth":          int(entry.get("depth", 0)),
        "parent_bni":     entry.get("parent_bni"),
        "doc_index":      int(entry.get("doc_index", 0)),
        "document":       _serialize_document(entry),
        "ax":             _serialize_ax(entry),
        "classification": _serialize_classification(entry.get("classification")),
        "provenance":     entry.get("provenance"),
    }
    if "text" in entry and entry["text"]:
        out["text"] = entry["text"]
    if entry.get("delivery_3p"):
        out["delivery_3p"] = entry["delivery_3p"]
    return out


def serialize_representation(state: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Build a JSON snapshot with versioned classification axes."""
    elements = state.get("elements", [])
    return {
        "url":           url,
        "taxonomy_version": TAXONOMY_VERSION,
        "captured_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "element_count": len(elements),
        "frames":        list(state.get("frames") or []),
        "uncaptured_frames": list(state.get("uncaptured_frames") or []),
        "capture":       dict(state.get("capture") or {}),
        "elements":      [serialize_element(e) for e in elements],
    }
