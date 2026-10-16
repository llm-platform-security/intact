# `intact.gentree`

## The GenTree record

`representation.json` holds `url`, `taxonomy_version`, `captured_at`, `element_count`, `frames`, `uncaptured_frames`, `capture` (the crawler's status for the page; empty for `intact.cli.capture`), and `elements`: a flat list, one document after another, each in document order, with one record per element of every frame. `parent_bni` rebuilds one tree per document, and `frames[].owner_bni` links a site-isolated frame to its `<iframe>`; other frames are not linked to theirs. `serialize.py` documents the schema.

This record comes from the test page in `tests/pages.py`, where a third-party analytics script creates a tracking image in the first-party document:

```json
{
  "bni": 17,
  "tag": "img",
  "attrs": {"data-cdp-pid": "2", "id": "tracker", "src": "https://thirdparty.test/pixel.gif"},
  "depth": 2,
  "parent_bni": 25,
  "doc_index": 0,
  "document": {"url": "https://firstparty.test/", "scope": "1p"},
  "ax": {"in_tree": true, "node_id": "17", "role": "image", "name": "", "description": "",
         "properties": {"url": "https://thirdparty.test/pixel.gif"}, "ignored": false},
  "classification": {
    "source_rule": "media:img",
    "authority": {"direct": ["hover"], "inherited": [], "blocked": [], "effective": ["hover"]},
    "effects": {"observable": ["fetch"]},
    "exposure": {"channels": ["accessible-name", "alt", "title-tooltip"],
                 "visible_to": ["ax-tree", "dom-text"]},
    "composition_notes": []
  },
  "provenance": {
    "tag": "img",
    "creator": "3p:thirdparty.test/analytics.js#6cde8188",
    "via": "createElement",
    "inserter": null,
    "attr_mods": [], "text_mods": [], "listeners": [],
    "loads": ["src→3p:thirdparty.test"],
    "frameId": "9D7A9C7C3A66EE8488E70EE6CBDA53C7"
  },
  "delivery_3p": [{"attr": "src", "host": "thirdparty.test"}]
}
```

| Field | Meaning |
|---|---|
| `bni` | the node's id (CDP `backendNodeId`; namespaced for site-isolated frames) |
| `tag`, `attrs` | tag name and attributes |
| `text` | the element's direct text, i.e., its own text nodes, joined (absent if blank) |
| `depth`, `parent_bni`, `doc_index` | the position in the tree, and the document (frame) the element belongs to |
| `document` | that document's URL, and whether it is first-party (`1p`) or third-party (`3p`) |
| `ax` | role, name, description, and properties, when the element is in the accessibility tree |
| `classification` | the element's capabilities (below) |
| `provenance` | `null` for parser-created elements that no recorded write touched; else `creator`, `via` (the interface), `inserter` (the first script that inserted or moved the element, or an ancestor, with `appendChild`, `insertBefore`, or `replaceChild`; `null` when no insertion was recorded or its label equals the creator's), `attr_mods`, `text_mods`, `listeners`, `loads` (the parties of the absolute third-party URLs that scripts write to `src`, `href`, `action`, or `data` through `setAttribute`/`setAttributeNS` or the wrapped `src` and `href` setters, and of the third-party requests of the script that created the element), `tag`, `frameId`, and `via_inline_id` (only on elements that code with a synthetic source URL, i.e., code passed to `eval` or `Function` or a dynamically inserted inline script, created with `createElement` or `createElementNS`) |
| `delivery_3p` | (optional) the third-party hosts that the element's URL attributes point to |

In the paper's terms, `classification.authority.effective` holds the element's **interactions**, `classification.effects.observable` its **effects**, and `classification.exposure.channels` its **channels**. `authority.direct` comes from the element itself, `inherited` from its ancestors (e.g., an image inside a link), and `blocked` lists what composition removed (e.g., from a disabled button).

## The capability taxonomy

- **10 interactions:** click, type, upload, drag, paste, hover, focus, popup, toggle, change-value.
- **13 effects:** choose, submit, navigate, fetch, send-request, navigate-frame, dom-mutate, storage-write, execute, post-message, apply-style, render-frame, external-handler.
- **12 channels:** body-text, accessible-name, accessible-description, placeholder, option-text, value, alt, title-tooltip, meta-og, noscript-content, caption-track, event-handler-source.
- **76 rules** assign the base labels from an element's tag and attributes (and, for a few, an enclosing form or details element), grouped by family: links, forms, media, embedded content, tables, dialogs (including details and summary), scripting, static content, and custom elements. **14 composition rules** then adjust them for the element's other attributes (e.g., ARIA, `tabindex`, `disabled`), its ancestors, and computed style.
- **Effect categories.** A *local change* (`reversible` in the code) can be reverted: choose, dom-mutate, apply-style, storage-write. An *external effect* (`irreversible`) cannot be recalled: send-request, fetch, external-handler. For an *undetermined* effect, the label alone does not settle its consequences: submit, navigate, execute, post-message, navigate-frame, render-frame.

[`taxonomy/README.md`](taxonomy/README.md) documents the rules.
