# `intact.gentree.taxonomy`

The taxonomy labels each element with the capabilities that [`../README.md`](../README.md#the-capability-taxonomy) lists. It reads only the element's tag, attributes, ancestors, and computed style. An element's effects are the effects that its semantics allow; an action on the element may produce only some of them.

## Base rules

76 rules assign an element's base labels. The most specific rule that matches the element applies.

| Family | Elements |
|---|---|
| Links | `<a>` and `<area>`, by `href` scheme, `download`, and `target="_blank"` |
| Forms | `<form>`, every `<input>` type, `<button>`, `<select>`, `<textarea>`, `<label>`, and the other form elements |
| Media | `<img>`, `<picture>`, `<video>`, `<audio>`, `<svg>`, `<canvas>`, and their parts |
| Embedded content | `<iframe>`, `<embed>`, `<object>` |
| Scripting and metadata | `<script>`, `<noscript>`, `<style>`, `<link>`, `<meta>`, `<title>`, `<base>` |
| Dialogs | `<dialog>`, `<details>`, `<summary>` |
| Tables | table elements |
| Static content | text, sectioning, and list elements, and any element that no other rule matches |
| Custom elements | tags with a hyphen, `<template>`, `<slot>` |

## Composition rules

14 rules then adjust the base labels, in this order:

| # | Condition | Change |
|---|---|---|
| 1 | an ancestor `<a href>` | inherits the link's interactions and effects |
| 2 | `contenteditable` on the element or an ancestor | adds type, focus, paste, and dom-mutate |
| 3 | `tabindex` ≥ 0 | adds focus |
| 4 | an ARIA role such as `button`, `checkbox`, or `tab` | adds the role's interactions and effects |
| 5 | `aria-expanded` on a clickable control | adds dom-mutate |
| 6 | `aria-pressed` on a button | adds dom-mutate |
| 7 | an inline `on*` handler | adds execute |
| 8 | `tabindex="-1"` | blocks focus |
| 9 | a sandboxed `<iframe>` ancestor | blocks popup and removes submit and navigate, unless the matching `allow-*` token permits them |
| 10 | `pointer-events: none` | blocks click and hover |
| 11 | `display: none` or `visibility: hidden` | removes `ax-tree` from `exposure.visible_to` |
| 12 | `aria-hidden="true"` | removes `ax-tree` from `exposure.visible_to` |
| 13 | `disabled` or `aria-disabled="true"` | blocks every interaction |
| 14 | `inert` on the element or an ancestor | blocks every interaction and removes `ax-tree` from `exposure.visible_to` |

Labels pass only from ancestors to descendants.

## Adding a base rule

1. Add a `Rule` to the `RULES` list in the family's file under `rules/`. For a new family, create a file and add its `RULES` to `all_rules()` in `rules/__init__.py`.
2. Name the rule `family:variant` (e.g., `anchor:download`), and give it `match`, `authority`, `effects`, and `exposure`. A label set can be a function of the element when it depends on the element's attributes.
3. Set `specificity`: 1 for a tag alone, 2 for a tag and one attribute condition, 3 for a tag and two attribute conditions, and 4 for a tag and a URL scheme. Ties go to the rule registered first.
4. Add a row to `tests/taxonomy/test_rules_table.py` with the labels that you expect. The keys `no_observable_effects` and `not_exposure_views` check labels that the rule must not assign.
5. If the rule interacts with a composition rule, add a test to `tests/taxonomy/test_composition.py`.
6. Run `pytest tests/taxonomy -q`.

## Adding a composition rule

1. Add a function `_my_rule(cls, spec)` to `composition.py`. It changes the classification `cls` in place and appends a note to `cls.composition_notes` when it applies.
2. Add the function to `_COMPOSITION_RULES` at its place in the order. `_disabled` and `_inert` run last, so that they override the earlier rules.
3. Add tests to `tests/taxonomy/test_composition.py`, and run `pytest tests/taxonomy -q`.
