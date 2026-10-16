"""Build ElementSpec instances from a CDP DOMSnapshot response.

`DOMSnapshot.captureSnapshot` returns a flat representation of every DOM
element across every frame in one shot — far cheaper than per-node DOM
queries.

Two functions:

- `build_specs_from_snapshot(snapshot) -> dict[bni → ElementSpec]`
  Per-element specs fed to the classifier. Each carries lightweight
  ancestor chain for composition rules.

- `build_dom_records(snapshot) -> list[dict]`
  Flat list of DOM elements in DOCUMENT-TREE PRE-ORDER. Each record has
  bni, tag, attrs, depth, parent_bni. Used to build the full DOM-shaped
  representation that gets joined with AX + classification + provenance.

Both walk the same snapshot once.
"""

from typing import Any

from intact.gentree.taxonomy.node_spec import ElementSpec


# Node types from the DOM spec.
NODE_TYPE_ELEMENT = 1
NODE_TYPE_TEXT = 3

# Computed style names we ask CDP to capture. Order matters — layout.styles
# entries are positional against this list.
COMPUTED_STYLE_NAMES = ["display", "visibility", "pointer-events"]


def build_specs_from_snapshot(snapshot: dict) -> dict[int, ElementSpec]:
    """Walk a DOMSnapshot.captureSnapshot result, return bni → ElementSpec.

    Aggregates across all documents (frames). Non-element nodes (text,
    comment, document) are skipped — the classifier only operates on
    element nodes.
    """
    strings: list[str] = snapshot.get("strings", [])

    def s(idx: int) -> str:
        """Resolve a string-table index. -1 (sentinel for missing) → ""."""
        if idx is None or idx < 0 or idx >= len(strings):
            return ""
        return strings[idx]

    out: dict[int, ElementSpec] = {}

    for document in snapshot.get("documents", []):
        nodes = document.get("nodes", {})
        layout = document.get("layout", {})

        parent_index_arr  = nodes.get("parentIndex", [])
        node_type_arr     = nodes.get("nodeType", [])
        node_name_arr     = nodes.get("nodeName", [])
        backend_node_arr  = nodes.get("backendNodeId", [])
        attributes_arr    = nodes.get("attributes", [])
        n = len(node_type_arr)

        # Decode tag + attrs per node up front; we'll reference these when
        # building ancestor chains for each element.
        per_node_tag:   list[str]            = [""] * n
        per_node_attrs: list[dict[str, str]] = [{} for _ in range(n)]
        for i in range(n):
            if node_type_arr[i] != NODE_TYPE_ELEMENT:
                continue
            per_node_tag[i] = s(node_name_arr[i] if i < len(node_name_arr) else -1).lower()
            attr_pairs = attributes_arr[i] if i < len(attributes_arr) else []
            attrs: dict[str, str] = {}
            for j in range(0, len(attr_pairs) - 1, 2):
                k = s(attr_pairs[j])
                v = s(attr_pairs[j + 1])
                if k:
                    attrs[k] = v
            per_node_attrs[i] = attrs

        # Build computed-style lookup: which node-index each layout entry refers to.
        computed_styles_by_node: dict[int, dict[str, str]] = {}
        layout_nodes  = layout.get("nodeIndex", [])
        layout_styles = layout.get("styles", [])
        for k, node_idx in enumerate(layout_nodes):
            if k >= len(layout_styles):
                continue
            style_values = layout_styles[k]
            style_dict: dict[str, str] = {}
            for s_pos, s_val_idx in enumerate(style_values):
                if s_pos >= len(COMPUTED_STYLE_NAMES):
                    break
                style_dict[COMPUTED_STYLE_NAMES[s_pos]] = s(s_val_idx)
            computed_styles_by_node[node_idx] = style_dict

        # Build one ElementSpec per element node.
        for i in range(n):
            if node_type_arr[i] != NODE_TYPE_ELEMENT:
                continue
            bni = backend_node_arr[i] if i < len(backend_node_arr) else None
            if not bni:
                continue

            # Walk parentIndex to assemble the ancestor chain.
            ancestors: list[ElementSpec] = []
            cur = parent_index_arr[i] if i < len(parent_index_arr) else -1
            guard = 0
            while cur != -1 and cur < n and guard < 200:
                if node_type_arr[cur] == NODE_TYPE_ELEMENT:
                    ancestors.append(ElementSpec(
                        tag=per_node_tag[cur],
                        attrs=per_node_attrs[cur],
                        role=per_node_attrs[cur].get("role"),
                        ancestors=[],  # composition reads tag/attrs only — flat is fine
                    ))
                cur = parent_index_arr[cur] if cur < len(parent_index_arr) else -1
                guard += 1

            out[bni] = ElementSpec(
                tag=per_node_tag[i],
                attrs=per_node_attrs[i],
                role=per_node_attrs[i].get("role"),
                ancestors=ancestors,
                computed_style_flags=computed_styles_by_node.get(i, {}),
                runtime_listeners=[],  # not populated in v1 — on*= handlers live in attrs
            )

    return out


def build_dom_records(snapshot: dict) -> list[dict[str, Any]]:
    """Return every DOM element across every document in DOCUMENT-TREE PRE-ORDER.

    Each record:
        {
            "bni":         backendNodeId (int),
            "tag":         lowercase tag name,
            "attrs":       attribute dict,
            "text":        concatenated nodeValue of DIRECT text-node children,
                           omitted when empty or whitespace-only,
            "depth":       0-based depth within this document (root = 0),
            "parent_bni":  backendNodeId of DOM parent in same doc (or None for roots),
            "doc_index":   which document this element belongs to (0 = top frame),
            "doc_url":     URL of the document that delivered this element
                           (top-frame URL for doc_index=0, iframe URL otherwise),
        }

    Text semantics: `text` is the join of nodeValue from immediate text-node
    children only, NOT recursive textContent. For `<p>Hello <b>world</b>!</p>`
    the `<p>` gets `text="Hello !"` and the `<b>` gets `text="world"` on its
    own record. Inline `<script>` and `<style>` bodies surface the same way.

    Frame documents are visited in the order CDP returned them. Within each
    document, walk is pre-order via parentIndex chains.
    """
    strings: list[str] = snapshot.get("strings", [])

    def s(idx: int) -> str:
        if idx is None or idx < 0 or idx >= len(strings):
            return ""
        return strings[idx]

    out: list[dict[str, Any]] = []

    for doc_index, document in enumerate(snapshot.get("documents", [])):
        doc_url = s(document.get("documentURL", -1))
        nodes = document.get("nodes", {})
        parent_index_arr = nodes.get("parentIndex", [])
        node_type_arr    = nodes.get("nodeType", [])
        node_name_arr    = nodes.get("nodeName", [])
        node_value_arr   = nodes.get("nodeValue", [])
        backend_node_arr = nodes.get("backendNodeId", [])
        attributes_arr   = nodes.get("attributes", [])
        n = len(node_type_arr)

        # Decode tag + attrs per node up front.
        per_node_tag:   list[str] = [""] * n
        per_node_attrs: list[dict[str, str]] = [{} for _ in range(n)]
        per_node_bni:   list[int | None] = [None] * n
        for i in range(n):
            if node_type_arr[i] != NODE_TYPE_ELEMENT:
                continue
            per_node_tag[i] = s(node_name_arr[i] if i < len(node_name_arr) else -1).lower()
            attr_pairs = attributes_arr[i] if i < len(attributes_arr) else []
            attrs: dict[str, str] = {}
            for j in range(0, len(attr_pairs) - 1, 2):
                k = s(attr_pairs[j])
                v = s(attr_pairs[j + 1])
                if k:
                    attrs[k] = v
            per_node_attrs[i] = attrs
            per_node_bni[i] = backend_node_arr[i] if i < len(backend_node_arr) else None

        # Build children lists from parent_index, so we can pre-order walk
        # using the document order of siblings (parent_index doesn't preserve
        # sibling order on its own — we reconstruct by index order, which is
        # the same as document order for DOMSnapshot).
        children: list[list[int]] = [[] for _ in range(n)]
        roots: list[int] = []
        for i in range(n):
            p = parent_index_arr[i] if i < len(parent_index_arr) else -1
            if p == -1 or p >= n:
                roots.append(i)
            else:
                children[p].append(i)

        # Per-element direct-text-children join. Walk each element's children
        # once, picking up only the immediate NODE_TYPE_TEXT entries.
        per_node_text: list[str] = [""] * n
        for i in range(n):
            if node_type_arr[i] != NODE_TYPE_ELEMENT:
                continue
            parts: list[str] = []
            for child_idx in children[i]:
                if (child_idx < n
                        and node_type_arr[child_idx] == NODE_TYPE_TEXT
                        and child_idx < len(node_value_arr)):
                    parts.append(s(node_value_arr[child_idx]))
            per_node_text[i] = "".join(parts)

        # Depth-first preorder walk, skipping non-element nodes but
        # recursing into their children (e.g., a DOCUMENT node has element
        # children).
        depth_of: dict[int, int] = {}

        def walk(node_idx: int, depth: int) -> None:
            is_element = node_type_arr[node_idx] == NODE_TYPE_ELEMENT
            bni = per_node_bni[node_idx]
            if is_element and bni:
                parent_idx = parent_index_arr[node_idx] if node_idx < len(parent_index_arr) else -1
                parent_bni = per_node_bni[parent_idx] if parent_idx != -1 and parent_idx < n else None
                depth_of[node_idx] = depth
                record: dict[str, Any] = {
                    "bni":        bni,
                    "tag":        per_node_tag[node_idx],
                    "attrs":      per_node_attrs[node_idx],
                    "depth":      depth,
                    "parent_bni": parent_bni,
                    "doc_index":  doc_index,
                    "doc_url":    doc_url,
                }
                text = per_node_text[node_idx]
                if text and text.strip():
                    record["text"] = text
                out.append(record)
                child_depth = depth + 1
            else:
                child_depth = depth
            for child_idx in children[node_idx]:
                walk(child_idx, child_depth)

        for root in roots:
            walk(root, 0)

    return out

