"""Enums for the static HTML element taxonomy.

Three independent axes per element:
- Authority: agent-driven operations the element exposes (click, type, ...)
- Effect:    what happens if those operations or browser-driven flows fire
- Channel:   content channels through which an element's content reaches the agent

Plus AgentView: which view of the page the agent uses to perceive content.

Reversibility annotations for every Effect label live in reversibility.py;
they do not add an axis or change label membership.

Adding a new value here must come with a corresponding rule entry in
`rules/<family>.py` and a test row in the parametrized suite.
"""

from enum import Enum


TAXONOMY_VERSION = "interaction-effects-v2"
LEGACY_TAXONOMY_VERSION = "interactions-v1"


class Authority(str, Enum):
    """Operations an LLM agent can be instructed to perform on an element."""
    CLICK         = "click"
    TYPE          = "type"
    UPLOAD        = "upload"             # file picker
    DRAG          = "drag"
    PASTE         = "paste"
    HOVER         = "hover"
    FOCUS         = "focus"
    POPUP         = "popup"              # opens new window/tab
    TOGGLE        = "toggle"             # details/summary, popovers
    CHANGE_VALUE  = "change-value"       # checkboxes, radios, sliders, color picker


class Effect(str, Enum):
    """Potential operations or consequences supported by element semantics.

    These labels do not guarantee that every click or keystroke produces the
    operation. Selecting an option, initiating form submission, and following
    a link are effects of suitable activation; they are distinct from their
    downstream state changes, requests, or frame navigation. Heuristic /
    inferred consequences ("this submit is probably a checkout") are
    intentionally NOT in the taxonomy; they belong in a separate
    consequence-scoring layer that consumes the taxonomy as input.
    """
    CHOOSE          = "choose"               # selecting an option/value, not merely opening a picker
    SUBMIT          = "submit"               # initiating form submission, subject to validation/cancellation
    NAVIGATE        = "navigate"             # following a navigation target, before frame consequences
    FETCH           = "fetch"                # browser-driven resource fetch
    SEND_REQUEST    = "send-request"         # form submit, XHR, fetch from JS
    NAVIGATE_FRAME  = "navigate-frame"       # location change in some frame
    DOM_MUTATE      = "dom-mutate"           # DOM content or represented control-state change
    STORAGE_WRITE   = "storage-write"        # cookies, localStorage / sessionStorage
    EXECUTE         = "execute"              # script run
    POST_MESSAGE    = "post-message"         # cross-frame messaging
    APPLY_STYLE     = "apply-style"          # stylesheet applied
    RENDER_FRAME    = "render-frame"         # iframe / object subtree rendered
    EXTERNAL_HANDLER = "external-handler"    # hands off to an OS app (mailto/tel/sms);
                                             # the URL can carry data (mailto/sms body)


class Channel(str, Enum):
    """Content channels through which an element reaches an agent's perception."""
    BODY_TEXT              = "body-text"
    ACCESSIBLE_NAME        = "accessible-name"          # aria-label, alt, <label for>
    ACCESSIBLE_DESCRIPTION = "accessible-description"   # aria-describedby
    PLACEHOLDER            = "placeholder"
    OPTION_TEXT            = "option-text"
    VALUE                  = "value"
    ALT                    = "alt"
    TITLE_TOOLTIP          = "title-tooltip"
    META_OG                = "meta-og"
    NOSCRIPT               = "noscript-content"
    CAPTION_TRACK          = "caption-track"            # VTT
    EVENT_HANDLER_SOURCE   = "event-handler-source"     # on*= attribute body


class AgentView(str, Enum):
    """Which view of the page an agent uses to perceive content.

    These are the two real perception substrates an agent can consume:
    - AX_TREE: Chrome's accessibility tree (what screen-reader-style agents see)
    - DOM_TEXT: raw HTML scrape (what curl/playwright-query agents see)

    A "hybrid" consumer that uses both views derives the union at the call
    site: `elem.exposure.visible_to & {AgentView.AX_TREE, AgentView.DOM_TEXT}`.
    No separate HYBRID enum value — that was redundant (union of the other two)
    and would have hidden the AX-only vs DOM-only distinction we explicitly
    want to preserve (e.g., <input type=hidden> rides on submit but isn't
    in the AX tree; <noscript> and <meta og:*> are DOM-scrape-only).

    Screenshot/OCR views are intentionally out of scope.
    """
    AX_TREE  = "ax-tree"
    DOM_TEXT = "dom-text"
