"""Lightweight node representation fed to the classifier.

Decoupled from any specific DOM library (Playwright handle, lxml element,
CDP node-description dict). Adapters from each are one-pass walks that build
ElementSpec instances.

This indirection lets the classifier be tested without a browser — tests
build ElementSpec literals directly.
"""

from dataclasses import dataclass, field


@dataclass
class ElementSpec:
    """A node's static + observable runtime state, as classifier input.

    Fields:
        tag:
            Lowercase tag name (e.g. "a", "input", "iframe").
        attrs:
            Attribute name → value, both strings. Empty-string value means the
            attribute is present without a value (e.g., `disabled`, `inert`).
        role:
            Explicit ARIA role attribute value if set, else None.
            Composition uses this to remap expected authority for role-overridden
            elements (e.g., `<div role="button">`).
        ancestors:
            Parent chain, immediate parent FIRST and root LAST. The classifier
            consults this for composition (wrapping <a>, ancestor sandbox iframe,
            inherited contenteditable, etc.).
        computed_style_flags:
            Subset of computed style values the classifier consults:
              "display", "visibility", "pointer-events", "inert", "content-visibility"
            Empty if no browser is available; classifier handles missing keys.
        runtime_listeners:
            Event types with registered listeners ("click", "input", ...).
            Best-effort; absent if no instrumentation. on*= attribute handlers
            live in `attrs`, not here.
    """
    tag:                   str
    attrs:                 dict[str, str]       = field(default_factory=dict)
    role:                  str | None           = None
    ancestors:             list["ElementSpec"]  = field(default_factory=list)
    computed_style_flags:  dict[str, str]       = field(default_factory=dict)
    runtime_listeners:     list[str]            = field(default_factory=list)
