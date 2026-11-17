"""Build the unified per-page representation: full DOM tree with AX, classification,
and provenance joined onto every element.

state["elements"] is a list of unified records in DOM-tree pre-order. EVERY
DOM element across every frame appears here — including ones the AX tree
ignores (hidden inputs, <script>, <style>, <meta>, <noscript>, aria-hidden
subtrees). When an element has an AX entry, role/name/properties/ignored
are filled in; otherwise those fields are None or empty and `ax_in_tree`
is False.

`state["dom_records"]` is the input — built by classification_pass from the
DOMSnapshot. Indexing into AX, classification, and provenance is by
backendNodeId.
"""

from typing import Any
from urllib.parse import urlparse

from intact.etld import etld1


# ── Document scope ──────────────────────────────────────────────────────────

def _etld1(url: str) -> str:
    """Registrable-domain extractor. Delegates to the canonical PSL-backed
    extractor (intact/etld.py) so document scope and provenance creator
    classification use the SAME 1p/3p boundary (single source)."""
    return etld1(url or "")


def _scope(doc_url: str, page_etld1: str) -> str:
    """1p if the document's eTLD+1 matches the top frame's, else 3p.
    Empty/about:blank docs collapse to 1p."""
    if not doc_url:
        return "1p"
    return "1p" if _etld1(doc_url) == page_etld1 else "3p"


def _top_etld1(dom_records: list[dict]) -> str:
    """eTLD+1 of the first doc_index=0 record. Used as the 1p reference."""
    for rec in dom_records:
        if rec.get("doc_index", 0) == 0 and rec.get("doc_url"):
            return _etld1(rec["doc_url"])
    return ""


# ── Delivery-host attribution ───────────────────────────────────────────────

# URL-bearing attribute keys we extract host attributions from. Order matters
# only for readability of the resulting list.
_URL_ATTRS = (
    "src", "href", "data", "action", "formaction", "poster", "cite", "srcset",
)


def _hosts_from_url(url: str) -> list[str]:
    """Return the list of hostnames carried by one attribute value. For
    srcset this is multiple URLs separated by commas with optional
    descriptors; for everything else it's one URL.

    Returns hostnames lowercased. Skips non-http(s) schemes (data:, about:,
    javascript:, mailto:, etc.), relative paths, and protocol-relative URLs
    without a host.
    """
    if not url:
        return []
    out: list[str] = []
    # srcset is comma-separated "<url> <descriptor>?"; we want the urls.
    parts = url.split(",") if "," in url else [url]
    for part in parts:
        candidate = part.strip().split()[0] if part.strip() else ""
        if not candidate:
            continue
        # Protocol-relative URL (//host/path) — give it a scheme so urlparse
        # extracts the host.
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        # Skip non-network schemes outright.
        lower = candidate.lower()
        if lower.startswith(("data:", "about:", "javascript:", "mailto:",
                              "tel:", "blob:", "#", "?")):
            continue
        try:
            parsed = urlparse(candidate)
            if not parsed.scheme or parsed.scheme not in ("http", "https"):
                continue
            host = (parsed.hostname or "").lower()
        except ValueError:
            continue  # malformed URL (e.g. bracketed non-IP host): no host
        if host and host not in out:
            out.append(host)
    return out


def _delivery_3p(attrs: dict, page_etld1: str) -> list[dict[str, str]]:
    """For each URL-bearing attribute present on the element, classify its
    target host as 1p or 3p (vs the page eTLD+1) and return the 3p
    entries. Each result is `{"attr": <attr-name>, "host": <hostname>}`.

    Same element can produce multiple entries (e.g., an <img> with both
    `src` and `srcset` pointing at different 3p hosts). Duplicates within
    the same element are de-duplicated.
    """
    if not attrs:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for attr in _URL_ATTRS:
        val = attrs.get(attr)
        if not isinstance(val, str) or not val:
            continue
        for host in _hosts_from_url(val):
            if _etld1("https://" + host) == page_etld1:
                continue
            key = (attr, host)
            if key in seen:
                continue
            seen.add(key)
            out.append({"attr": attr, "host": host})
    return out


# ── AX helpers ──────────────────────────────────────────────────────────────

def _aname(ax_node: dict) -> str:
    name = ax_node.get("name", {})
    v = name.get("value")
    if isinstance(v, dict):
        return v.get("value", "")
    if isinstance(v, str):
        return v
    return ""


def _adescription(ax_node: dict) -> str:
    desc = ax_node.get("description", {})
    v = desc.get("value")
    if isinstance(v, dict):
        return v.get("value", "")
    if isinstance(v, str):
        return v
    return ""


def _role(ax_node: dict) -> str:
    role = ax_node.get("role", {})
    v = role.get("value")
    if isinstance(v, dict):
        return v.get("value", "")
    if isinstance(v, str):
        return v
    return ""


def _properties(ax_node: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prop in ax_node.get("properties", []):
        name = prop.get("name")
        val = prop.get("value", {}).get("value")
        if name:
            out[name] = val
    return out


def _index_ax_by_bni(ax_nodes: list[dict]) -> dict[int, dict]:
    """Index AX nodes by backendDOMNodeId. AX-virtual nodes (StaticText,
    generic without a backing DOM element) have no bni and are skipped."""
    out: dict[int, dict] = {}
    for node in ax_nodes:
        bni = node.get("backendDOMNodeId")
        if bni:
            out[bni] = node
    return out


# ── Public ──────────────────────────────────────────────────────────────────

def build_unified_elements(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk the DOM in pre-order, joining AX + classification + provenance per element.

    Each record:
        {
            "bni":           backendNodeId,
            "tag":           lowercase tag name (always present),
            "attrs":         attribute dict (always present),
            "depth":         DOM-tree depth (root = 0),
            "parent_bni":    DOM parent's bni (None for roots),
            "doc_index":     frame index (0 = top frame),

            # AX side — populated when this element has an AX entry, else
            # role="" name="" properties={} ax_in_tree=False ignored=False.
            "ax_node_id":    str | None,
            "role":          str,
            "name":          str,
            "description":   str,
            "properties":    dict[str, Any],
            "ignored":       bool,
            "ax_in_tree":    bool,

            # Classification (always present for every DOM element).
            "classification": ElementClassification | None,

            # Document that delivered this element's bytes — always present.
            # url is the document URL (top frame, or iframe URL for nested
            # documents). scope is "1p" if its eTLD+1 matches the top frame's,
            # else "3p". For parser-created elements this IS the HTTP response
            # that carried the bytes; for JS-created elements it's the document
            # the JS injected into (and provenance.creator names the script).
            "document":       {"url": str, "scope": "1p" | "3p"},

            # Provenance — present when JS-tracked, else None. Parser-static
            # elements have no entry here; consumers should treat absence
            # as creator='parser'.
            "provenance":     dict | None,

            # 3p delivery hosts — derived from URL-bearing attrs
            # (src/href/data/action/formaction/poster/cite/srcset). Each
            # entry is {"attr": <name>, "host": <hostname>}. Lists 3p
            # hosts the element's bytes load from, independent of who
            # created the element in the DOM. Omitted entirely (key
            # absent) when the element has no 3p URL-bearing attrs —
            # most elements are in this state. Covers the parser-static
            # case where `provenance` is None but the element still
            # points at a 3p host (pixel trackers, declined ad iframes,
            # initial <script src=3p>).
            "delivery_3p":    list[dict] | absent,
        }
    """
    dom_records    = state.get("dom_records", [])
    classification = state.get("classification", {})
    prov_elements  = state.get("provenance", {}).get("elements", {})
    ax_by_bni      = _index_ax_by_bni(state.get("ax_nodes", []))
    page_etld1     = _top_etld1(dom_records)

    out: list[dict[str, Any]] = []
    for rec in dom_records:
        bni = rec.get("bni")
        ax_node = ax_by_bni.get(bni)

        if ax_node is not None:
            role        = _role(ax_node)
            name        = _aname(ax_node)
            description = _adescription(ax_node)
            properties  = _properties(ax_node)
            ignored     = bool(ax_node.get("ignored", False))
            ax_in_tree  = True
            ax_node_id  = ax_node.get("nodeId")
        else:
            role, name, description = "", "", ""
            properties = {}
            ignored = False
            ax_in_tree = False
            ax_node_id = None

        doc_url = rec.get("doc_url", "")

        record: dict[str, Any] = {
            "bni":            bni,
            "tag":            rec.get("tag", ""),
            "attrs":          rec.get("attrs", {}),
            "depth":          rec.get("depth", 0),
            "parent_bni":     rec.get("parent_bni"),
            "doc_index":      rec.get("doc_index", 0),

            "ax_node_id":     ax_node_id,
            "role":           role,
            "name":           name,
            "description":    description,
            "properties":     properties,
            "ignored":        ignored,
            "ax_in_tree":     ax_in_tree,

            "document":       {"url": doc_url, "scope": _scope(doc_url, page_etld1)},

            "classification": classification.get(bni),
            "provenance":     prov_elements.get(bni),
        }
        if "text" in rec:
            record["text"] = rec["text"]
        deliveries = _delivery_3p(rec.get("attrs", {}), page_etld1)
        if deliveries:
            record["delivery_3p"] = deliveries
        out.append(record)

    return out
