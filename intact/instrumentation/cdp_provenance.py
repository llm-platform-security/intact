"""
intact/instrumentation/cdp_provenance.py — CDP-based DOM provenance tracker

Injects a JS wrapper before page scripts run, then collects who created,
inserted, and modified every DOM element.  Works in any Chromium browser —
no Brave/PageGraph required.

Schema returned by collect():

    {
        "page_origin": "cnn.com",

        "elements": {
            <backendNodeId>: {
                "tag":       str,          # html tag
                "creator":   str,          # "1p:file.js" | "1p:inline" | "3p:domain.com/path#hash"
                                           #   | "unknown" (script-created but unattributable;
                                           #   fail-closed — never silently 1p)
                "via":       str,          # "createElement" | "innerHTML" | "insertAdjacentHTML"
                                           #   | "documentWrite" | "fragment" | "clone" | ...
                "inserter":  str | None,   # who put it in the DOM (None if same as creator)
                "frameId":   str,          # frame the element lives in (records keyed frameId|nid)
                "attr_mods": [             # every setAttribute write, by party
                    {"attr": str, "by": str}  # (deduped by (attr, party))
                ],
                "text_mods": [str],        # parties that wrote text into this element (content taint)
                "listeners": [str],        # scripts that attached event listeners
                "loads":     [str],        # 3p domains this element points to (src/href values)
            }
        },

        # Attribution coverage over script-touched elements:
        # {first_party, third_party, unknown, tracked_total}.
        "coverage": {str: int},

        "scripts": {
            <url>: {
                "cls":       str,          # same format as creator
                "3p_loads":  [str],        # 3p domains this script requested over the network
            }
        },

        "network": [                       # every request that went to a 3p domain
            {"url": str, "domain": str, "initiator_script": str}
        ],
    }

Usage:
    tracker = CDPProvenance("cnn.com")

    # Before navigation:
    cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": tracker.inject_script()})
    tracker.enable_network_tracking(cdp)

    # Navigate + wait...

    # After page settles:
    data = tracker.collect(cdp)
"""

import json
from urllib.parse import urlparse

from intact.etld import etld1

# ---------------------------------------------------------------------------
# Injected JS — runs before any page scripts
# ---------------------------------------------------------------------------

_INJECT_JS = r"""
(function () {
  if (window.__cdpProv) return;

  // Every setAttribute write is recorded in attrMods (deduped downstream by
  // (attr, party)), so a 3p mutating class/style/data-* on first-party content
  // is captured, not just AX-relevant attributes. LOAD_ATTRS additionally yields
  // a `loads` entry when the value is a URL.
  var LOAD_ATTRS = {'src':1,'href':1,'action':1,'data':1};
  var MARKER  = 'data-cdp-pid';
  var tracking = true;

  var prov = window.__cdpProv = { nextId: 1, nodes: {}, inlineScripts: {} };

  // Capture native references before wrapping
  var _createElement      = Document.prototype.createElement;
  var _createElementNS    = Document.prototype.createElementNS;
  var _setAttribute       = Element.prototype.setAttribute;
  var _setAttributeNS     = Element.prototype.setAttributeNS;
  var _removeAttribute    = Element.prototype.removeAttribute;
  var _appendChild        = Node.prototype.appendChild;
  var _insertBefore       = Node.prototype.insertBefore;
  var _replaceChild       = Node.prototype.replaceChild;
  var _cloneNode          = Node.prototype.cloneNode;
  var _addEventListener   = EventTarget.prototype.addEventListener;
  var _insertAdjacentHTML = Element.prototype.insertAdjacentHTML;
  var _domParserParse     = window.DOMParser && DOMParser.prototype.parseFromString;
  var _rangeCreateFragment = window.Range && Range.prototype.createContextualFragment;
  var _importNode         = Document.prototype.importNode;
  var _adoptNode          = Document.prototype.adoptNode;
  var _docWrite           = Document.prototype.write;
  var _docWriteln         = Document.prototype.writeln;
  var _eval               = window.eval;
  var _Function           = window.Function;
  var _inHTMLDesc      = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  var _innerTextDesc   = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'innerText');
  var _textContentDesc = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent');
  var _nodeValueDesc   = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeValue');
  var _charDataDesc    = Object.getOwnPropertyDescriptor(CharacterData.prototype, 'data');
  var _appendData      = CharacterData.prototype.appendData;
  var _insertData      = CharacterData.prototype.insertData;
  var _scriptTextDesc  = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'text');
  // Some Chromium versions expose an own textContent accessor on HTMLScriptElement
  // that shadows Node.prototype.textContent — must be wrapped separately.
  var _scriptTCDesc    = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'textContent');
  var _qsa = Element.prototype.querySelectorAll;
  var _dqsa = Document.prototype.querySelectorAll;

  // Maps a <script> element to the {creator, text} captured when its body was set,
  // so we can register provenance + rewrite the body with a synthetic sourceURL
  // at insertion time (inline scripts execute synchronously during insert).
  var _pendingScriptText = new WeakMap();
  // Side-channel set by callerUrl() when the matched stack frame was a synthetic
  // dynamic-inline source. Read by callers that want to record viaInlineId.
  var _lastInlineId = null;

  // ── helpers ──────────────────────────────────────────────────────────────

  function ensureNode(el) {
    if (!el || el.nodeType !== 1 || !tracking) return null;
    try {
      var existing = el.getAttribute(MARKER);
      if (existing) return prov.nodes[+existing];
      var nid = prov.nextId++;
      tracking = false;
      _setAttribute.call(el, MARKER, nid);
      tracking = true;
      var rec = {
        creator: null, via: null, inserter: null,
        attrMods: [], text_mods: [], listeners: [], loads: []
      };
      prov.nodes[nid] = rec;
      return rec;
    } catch(e) { tracking = true; return null; }
  }

  function callerUrl() {
    _lastInlineId = null;
    try {
      var lines = (new Error().stack || '').split('\n');
      for (var i = 2; i < lines.length; i++) {
        // A frame running from an opaque blob: or data: URL has no party of its
        // own, even when the URL embeds an https origin: the call is unattributed.
        if (/(?:^|[\s(])(?:blob|data):/.test(lines[i])) return 'inline';
        var m = lines[i].match(/((?:https?|cdpprov):\/\/[^\s)]+)/);
        if (m) {
          var url = m[1].replace(/:\d+:\d+$/, '');
          // Synthetic dynamic-inline URLs: resolve to the originating script.
          // This is what catches async callbacks defined inside dynamically
          // injected inline scripts (e.g. setTimeout body) — V8 reports the
          // sourceURL we set via "//# sourceURL=" rather than chain_b.js.
          if ((url.indexOf('cdpprov://dynamic-inline/') === 0 ||
               url.indexOf('cdpprov://dynamic-eval/') === 0) &&
              prov.inlineScripts[url]) {
            _lastInlineId = url;
            return prov.inlineScripts[url].creator || 'inline';
          }
          return url;
        }
      }
    } catch(e) {}
    return 'inline';
  }

  // djb2-ish hash → 8 hex chars. Identifier-only, not security-relevant.
  function _quickHash(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h) ^ s.charCodeAt(i);
    return ('00000000' + (h >>> 0).toString(16)).slice(-8);
  }

  // Called from textContent/text setters: stash {creator, text} on the script
  // element so trackInsert can rewrite + register at insertion time.
  function _captureScriptText(scriptEl, val) {
    if (!tracking) return;
    if (!(scriptEl instanceof HTMLScriptElement)) return;
    var creator = callerUrl();
    _pendingScriptText.set(scriptEl, { creator: creator, text: String(val == null ? '' : val) });
  }

  function forEachElement(root, includeRoot, fn) {
    if (!root) return 0;
    var count = 0;
    try {
      if (includeRoot && root.nodeType === 1) {
        fn(root);
        count++;
      }
      var kids = [];
      var wasTracking = tracking;
      try {
        tracking = false;
        if (root.nodeType === 1) kids = _qsa.call(root, '*');
        else if (root.nodeType === 9) kids = _dqsa.call(root, '*');
        else if (root.querySelectorAll) kids = root.querySelectorAll('*');
      } finally {
        tracking = wasTracking;
      }
      for (var i = 0; i < kids.length; i++) {
        fn(kids[i]);
        count++;
      }
    } catch(e) {}
    return count;
  }

  function stripMarkerTree(root) {
    forEachElement(root, true, function(el) {
      try {
        if (!el.hasAttribute || !el.hasAttribute(MARKER)) return;
        var wasTracking = tracking;
        try {
          tracking = false;
          _removeAttribute.call(el, MARKER);
        } finally {
          tracking = wasTracking;
        }
      } catch(e) {}
    });
  }

  function markChildren(container, by, via) {
    var count = 0;
    try {
      count = forEachElement(container, false, function(el) {
        var rec = ensureNode(el);
        if (rec && !rec.creator) { rec.creator = by; rec.via = via; }
      });
    } catch(e) {}
    return count;
  }

  function markElementTree(root, by, via, force) {
    if (!root) return 0;
    var count = 0;
    try {
      count = forEachElement(root, true, function(el) {
        var rec = ensureNode(el);
        if (rec && (force || !rec.creator)) { rec.creator = by; rec.via = via; }
      });
    } catch(e) {}
    return count;
  }

  function recordTextMod(target) {
    if (!tracking || !target) return;
    var el = null;
    if (target.nodeType === 1) {
      if (target instanceof HTMLScriptElement) return;
      el = target;
    } else if (target.nodeType === 3 || target instanceof CharacterData) {
      el = target.parentElement || (target.parentNode && target.parentNode.nodeType === 1 ? target.parentNode : null);
      if (el instanceof HTMLScriptElement) return;
    }
    if (!el) return;
    var rec = ensureNode(el);
    if (rec) rec.text_mods.push({ by: callerUrl() });
  }

  function _registerDynamicEvalSource(src, creator) {
    var text = String(src == null ? '' : src);
    // A page-supplied sourceURL is only a debug/id hint; do not let it become
    // the party-bearing script URL seen in stack traces.
    var evalText = text
      .replace(/^\s*\/\/[#@]\s*sourceURL=.*$/mg, '')
      .replace(/^\s*\/\*[#@]\s*sourceURL=.*?\*\/\s*$/mg, '');
    var hash = _quickHash(text);
    var sid  = 'cdpprov://dynamic-eval/' + hash;
    prov.inlineScripts[sid] = {
      creator: creator,
      hash:    hash,
      preview: text.slice(0, 80),
      kind:    'eval',
    };
    return evalText + '\n//# sourceURL=' + sid + '\n';
  }

  // ── wrappers ─────────────────────────────────────────────────────────────

  Document.prototype.createElement = function(tag, opts) {
    var el = _createElement.call(this, tag, opts);
    var rec = ensureNode(el);
    if (rec) {
      rec.creator = callerUrl();
      rec.via = 'createElement';
      if (_lastInlineId) rec.viaInlineId = _lastInlineId;
    }
    return el;
  };

  Document.prototype.createElementNS = function(ns, tag, opts) {
    var el = _createElementNS.call(this, ns, tag, opts);
    var rec = ensureNode(el);
    if (rec) {
      rec.creator = callerUrl();
      rec.via = 'createElement';
      if (_lastInlineId) rec.viaInlineId = _lastInlineId;
    }
    return el;
  };

  if (_domParserParse) {
    DOMParser.prototype.parseFromString = function(str, type) {
      var by = tracking ? callerUrl() : null;
      var doc = _domParserParse.call(this, str, type);
      if (by) markElementTree(doc, by, 'domparser');
      return doc;
    };
  }

  Node.prototype.cloneNode = function(deep) {
    var by = tracking ? callerUrl() : null;
    var clone = _cloneNode.call(this, deep);
    if (by) {
      stripMarkerTree(clone);
      markElementTree(clone, by, 'clone');
    }
    return clone;
  };

  if (_rangeCreateFragment) {
    Range.prototype.createContextualFragment = function(html) {
      var by = tracking ? callerUrl() : null;
      var frag = _rangeCreateFragment.call(this, html);
      if (by) markElementTree(frag, by, 'fragment');
      return frag;
    };
  }

  if (_importNode) {
    Document.prototype.importNode = function(node, deep) {
      var by = tracking ? callerUrl() : null;
      var imported = _importNode.call(this, node, deep);
      if (by) {
        stripMarkerTree(imported);
        markElementTree(imported, by, 'importNode');
      }
      return imported;
    };
  }

  if (_adoptNode) {
    Document.prototype.adoptNode = function(node) {
      var by = tracking ? callerUrl() : null;
      var adopted = _adoptNode.call(this, node);
      if (by) {
        stripMarkerTree(adopted);
        markElementTree(adopted, by, 'adoptNode');
      }
      return adopted;
    };
  }

  Element.prototype.setAttribute = function(name, val) {
    if (tracking && name !== MARKER) {
      var rec = ensureNode(this);
      if (rec) {
        rec.attrMods.push({ attr: name, by: callerUrl() });
        if (LOAD_ATTRS[name]) {
          var v = String(val || '');
          if (v.indexOf('http') === 0) rec.loads.push({ attr: name, url: v });
        }
      }
    }
    return _setAttribute.call(this, name, val);
  };

  Element.prototype.setAttributeNS = function(ns, name, val) {
    if (tracking && name !== MARKER) {
      var rec = ensureNode(this);
      if (rec) {
        var localName = name.split(':').pop();
        rec.attrMods.push({ attr: localName, by: callerUrl() });
        if (LOAD_ATTRS[localName]) {
          var v = String(val || '');
          if (v.indexOf('http') === 0) rec.loads.push({ attr: localName, url: v });
        }
      }
    }
    return _setAttributeNS.call(this, ns, name, val);
  };

  // Register a dynamically-injected inline script BEFORE it executes.
  // We rewrite the script body to append `//# sourceURL=cdpprov://...` so V8
  // attributes any function defined inside (including async callbacks) to that
  // synthetic URL. callerUrl() then resolves it back to the originating script.
  function _registerInlineScriptIfPending(child) {
    if (!(child instanceof HTMLScriptElement)) return;
    if (!_pendingScriptText.has(child)) return;
    // Skip script elements that have an external src — the textContent is ignored
    // by the browser in that case, so no inline execution will happen.
    if (child.src) { _pendingScriptText.delete(child); return; }
    var info = _pendingScriptText.get(child);
    _pendingScriptText.delete(child);
    var hash = _quickHash(info.text);
    var sid  = 'cdpprov://dynamic-inline/' + hash;
    prov.inlineScripts[sid] = {
      creator: info.creator,
      hash:    hash,
      preview: info.text.slice(0, 80),
    };
    tracking = false;
    try {
      _textContentDesc.set.call(child, info.text + '\n//# sourceURL=' + sid + '\n');
    } catch(e) {}
    tracking = true;
  }

  function trackInsert(child) {
    if (!tracking || !child) return;
    var by = callerUrl();
    forEachElement(child, true, function(el) {
      _registerInlineScriptIfPending(el);
      var rec = ensureNode(el);
      if (rec && !rec.inserter) rec.inserter = by;
    });
  }

  Node.prototype.appendChild  = function(c)    { trackInsert(c); return _appendChild.call(this, c); };
  Node.prototype.insertBefore = function(c, r) { trackInsert(c); return _insertBefore.call(this, c, r); };
  Node.prototype.replaceChild = function(n, o) { trackInsert(n); return _replaceChild.call(this, n, o); };

  function wrapDocumentWrite(nativeFn) {
    return function() {
      var by = tracking ? callerUrl() : null;
      var observer = null;
      if (by && window.MutationObserver) {
        try {
          observer = new MutationObserver(function(){});
          observer.observe(this, { childList: true, subtree: true });
        } catch(e) {
          try {
            if (this.documentElement) observer.observe(this.documentElement, { childList: true, subtree: true });
          } catch(e2) { observer = null; }
        }
      }
      try {
        return nativeFn.apply(this, arguments);
      } finally {
        if (observer) {
          try {
            var records = observer.takeRecords();
            observer.disconnect();
            for (var i = 0; i < records.length; i++) {
              var added = records[i].addedNodes || [];
              for (var j = 0; j < added.length; j++) {
                markElementTree(added[j], by, 'documentWrite', true);
              }
            }
          } catch(e3) {
            try { observer.disconnect(); } catch(e4) {}
          }
        }
      }
    };
  }
  Document.prototype.write = wrapDocumentWrite(_docWrite);
  Document.prototype.writeln = wrapDocumentWrite(_docWriteln);

  function _constructFunction(args) {
    var bindArgs = [null];
    for (var i = 0; i < args.length; i++) bindArgs.push(args[i]);
    return new (_Function.bind.apply(_Function, bindArgs))();
  }

  window.eval = function(src) {
    if (tracking && typeof src === 'string') {
      return _eval.call(this, _registerDynamicEvalSource(src, callerUrl()));
    }
    return _eval.call(this, src);
  };

  function FunctionWrapper() {
    var args = Array.prototype.slice.call(arguments);
    if (tracking && args.length) {
      args[args.length - 1] = _registerDynamicEvalSource(args[args.length - 1], callerUrl());
    }
    return _constructFunction(args);
  }
  FunctionWrapper.prototype = _Function.prototype;
  window.Function = FunctionWrapper;
  try {
    Object.defineProperty(Function.prototype, 'constructor', {
      value: FunctionWrapper,
      writable: true,
      configurable: true,
    });
  } catch(e) {}

  // Wrap textContent setter on Node.prototype: catches the common case for non-script
  // nodes. (For <script> elements, see HTMLScriptElement.prototype.textContent below —
  // Chromium puts an own accessor there that shadows Node.prototype.textContent.)
  if (_textContentDesc && _textContentDesc.set) {
    Object.defineProperty(Node.prototype, 'textContent', {
      get: _textContentDesc.get,
      set: function(val) {
        if (tracking && this instanceof HTMLScriptElement) _captureScriptText(this, val);
        else if (tracking) recordTextMod(this);
        _textContentDesc.set.call(this, val);
      },
      configurable: true,
    });
  }
  if (_innerTextDesc && _innerTextDesc.set) {
    Object.defineProperty(HTMLElement.prototype, 'innerText', {
      get: _innerTextDesc.get,
      set: function(val) {
        if (tracking) recordTextMod(this);
        _innerTextDesc.set.call(this, val);
      },
      configurable: true,
    });
  }
  if (_charDataDesc && _charDataDesc.set) {
    Object.defineProperty(CharacterData.prototype, 'data', {
      get: _charDataDesc.get,
      set: function(val) {
        if (tracking) recordTextMod(this);
        _charDataDesc.set.call(this, val);
      },
      configurable: true,
    });
  }
  if (_nodeValueDesc && _nodeValueDesc.set) {
    Object.defineProperty(Node.prototype, 'nodeValue', {
      get: _nodeValueDesc.get,
      set: function(val) {
        if (tracking && this instanceof CharacterData) recordTextMod(this);
        _nodeValueDesc.set.call(this, val);
      },
      configurable: true,
    });
  }
  CharacterData.prototype.appendData = function(data) {
    if (tracking) recordTextMod(this);
    return _appendData.call(this, data);
  };
  CharacterData.prototype.insertData = function(offset, data) {
    if (tracking) recordTextMod(this);
    return _insertData.call(this, offset, data);
  };
  // HTMLScriptElement.prototype.textContent shadows Node.prototype.textContent in
  // Chromium, so we MUST wrap this one to catch `scriptEl.textContent = "..."`.
  if (_scriptTCDesc && _scriptTCDesc.set) {
    Object.defineProperty(HTMLScriptElement.prototype, 'textContent', {
      get: _scriptTCDesc.get,
      set: function(val) {
        if (tracking) _captureScriptText(this, val);
        _scriptTCDesc.set.call(this, val);
      },
      configurable: true,
    });
  }
  // Alternate body-set API: HTMLScriptElement.prototype.text.
  if (_scriptTextDesc && _scriptTextDesc.set) {
    Object.defineProperty(HTMLScriptElement.prototype, 'text', {
      get: _scriptTextDesc.get,
      set: function(val) {
        if (tracking) _captureScriptText(this, val);
        _scriptTextDesc.set.call(this, val);
      },
      configurable: true,
    });
  }

  Object.defineProperty(Element.prototype, 'innerHTML', {
    get: _inHTMLDesc.get,
    set: function(html) {
      var by = tracking ? callerUrl() : null;
      _inHTMLDesc.set.call(this, html);
      if (by) {
        var marked = markChildren(this, by, 'innerHTML');
        if (!marked && this.textContent) recordTextMod(this);
      }
    },
    configurable: true,
  });

  Element.prototype.insertAdjacentHTML = function(pos, html) {
    var by = tracking ? callerUrl() : null;
    var observer = null;
    var observeTarget = null;
    if (by && window.MutationObserver) {
      try {
        var p = String(pos || '').toLowerCase();
        observeTarget = (p === 'beforebegin' || p === 'afterend') ? this.parentNode : this;
        if (observeTarget) {
          observer = new MutationObserver(function(){});
          observer.observe(observeTarget, { childList: true });
        }
      } catch(e) { observer = null; }
    }
    try {
      return _insertAdjacentHTML.call(this, pos, html);
    } finally {
      if (observer) {
        try {
          var records = observer.takeRecords();
          observer.disconnect();
          for (var i = 0; i < records.length; i++) {
            var added = records[i].addedNodes || [];
            for (var j = 0; j < added.length; j++) {
              markElementTree(added[j], by, 'insertAdjacentHTML');
            }
          }
        } catch(e2) {
          try { observer.disconnect(); } catch(e3) {}
        }
      }
    }
  };

  // ── load-attribute property setters (img.src, script.src, etc.) ─────────
  // These bypass setAttribute, so we wrap them separately.
  function wrapLoadProp(proto, attr) {
    var desc = Object.getOwnPropertyDescriptor(proto, attr);
    if (!desc || !desc.set) return;
    Object.defineProperty(proto, attr, {
      get: desc.get,
      set: function(val) {
        if (tracking) {
          var rec = ensureNode(this);
          if (rec) {
            var v = String(val || '');
            if (v.indexOf('http') === 0) rec.loads.push({ attr: attr, url: v });
          }
        }
        desc.set.call(this, val);
      },
      configurable: true,
    });
  }
  wrapLoadProp(HTMLImageElement.prototype,  'src');
  wrapLoadProp(HTMLScriptElement.prototype, 'src');
  wrapLoadProp(HTMLIFrameElement.prototype, 'src');
  wrapLoadProp(HTMLLinkElement.prototype,   'href');

  EventTarget.prototype.addEventListener = function(type, fn, opts) {
    if (tracking && this && this.nodeType === 1) {
      var rec = ensureNode(this);
      if (rec) {
        var u = callerUrl();
        if (rec.listeners.indexOf(u) < 0) rec.listeners.push(u);
      }
    }
    return _addEventListener.call(this, type, fn, opts);
  };

})();
"""

# Collect all provenance records from this frame; Python keys them by frameId|nid.
# DOM resolution happens separately in each frame's main-world context.
_COLLECT_JS = r"""
(function (frameId) {
  var p = window.__cdpProv;
  if (!p) return '{"frameId":' + JSON.stringify(frameId) + ',"nodes":{},"inlineScripts":{}}';
  var nodes = {};
  for (var nid in p.nodes) {
    if (!Object.prototype.hasOwnProperty.call(p.nodes, nid)) continue;
    var rec = p.nodes[nid] || {};
    rec.frameId = frameId;
    if (!rec.text_mods) rec.text_mods = [];
    nodes[nid] = rec;
  }
  return JSON.stringify({
    frameId:       frameId,
    nodes:         nodes,
    inlineScripts: p.inlineScripts || {},
  });
})(__CDP_FRAME_ID__)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _etld1(url: str) -> str:
    """eTLD+1 (registrable domain) of a URL/host.

    Delegates to the canonical PSL-backed extractor (intact/etld.py). Kept as a
    public name because intact.browser.session and the tests import
    ``_etld1`` directly.
    """
    return etld1(url)


def _classify(script_url: str, page_origin: str,
              url_hashes: "dict[str, list[str]] | None" = None) -> str:
    """Return a provenance label for a script creator token.

    Labels: ``1p:<file.js>`` / ``1p:inline`` (positively first-party),
    ``3p:<domain>[/path][#hash]`` (third-party), or ``unknown``.

    **Fails closed (taint invariant).** The creator token distinguishes three
    cases:
      - **empty/None** → the node was never created by a script wrapper
        (``createElement`` et al. always record at least ``"inline"``); it is
        parser content that a mutation wrapper merely touched. Parser content is
        first-party (relative to the top frame) → ``1p:inline``.
      - **literal ``"inline"``** → a script created/modified it but
        ``callerUrl`` found no script URL in the stack (e.g. eval with no
        sourceURL, anonymous async), or the first located frame runs from a
        ``blob:`` or ``data:`` URL. Unattributable → ``unknown``, never 1p.
      - **opaque ``blob:``/``data:``** with no host → ``unknown``.
    Genuine first-party inline scripts in the top document execute with the
    document URL as their script URL, so they classify as ``1p`` through the
    same-origin URL path below.

    3p labels include the full URL path + query to distinguish scripts at
    different paths on the same domain (cdn.com/a/lib.js vs cdn.com/b/lib.js,
    or ?v=1 vs ?v=2).

    url_hashes maps each URL to the list of content hashes (from
    Runtime.scriptParsed) seen for that URL across the page lifetime:
      - One unique hash  → append #<hash8> so the exact content is identified.
      - Multiple hashes  → append #<hash8> of each; callers see the ambiguity.
      - No hash data     → label is path-only (still better than domain-only).
    """
    # No creator token: parser content touched by a mutation wrapper. Parser
    # content is first-party relative to the top frame.
    if not script_url:
        return "1p:inline"
    # A script created/modified the node but we could not identify which script.
    # Fail closed — do NOT assume first-party (that would undercount taint).
    if script_url == "inline":
        return "unknown"
    parsed = urlparse(script_url)
    domain = _etld1(script_url)
    if not domain:
        # Opaque creator (blob:/data:/about:) with no resolvable party.
        return "unknown"
    if domain != page_origin:
        path     = parsed.path.lstrip("/")
        resource = f"{path}?{parsed.query}" if parsed.query else path
        base     = f"3p:{domain}/{resource}" if resource else f"3p:{domain}"
        if url_hashes:
            hashes = list(dict.fromkeys(h for h in url_hashes.get(script_url, []) if h))
            if len(hashes) == 1:
                base = f"{base}#{hashes[0]}"
            elif len(hashes) > 1:
                # Same URL served with different content — include all hashes
                base = f"{base}#({'|'.join(hashes)})"
        return base
    fname = parsed.path.rstrip("/").split("/")[-1].split("?")[0]
    return f"1p:{fname}" if fname else "1p:inline"


def _collect_frame_ids(frame_tree: dict) -> list:
    ids = []
    frame = frame_tree.get("frame", {})
    if fid := frame.get("id"):
        ids.append(fid)
    for child in frame_tree.get("childFrames", []):
        ids.extend(_collect_frame_ids(child))
    return ids


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CDPProvenance:

    def __init__(self, page_origin: str):
        self.page_origin = page_origin
        self._network: list[dict]           = []   # all 3p requests
        self._script_3p: dict[str, list]    = {}   # script_url -> [3p domains]
        self._frame_contexts: dict[str, int] = {}  # frameId -> executionContextId (default world)
        # scriptId → {url, hash, executionContextId} from Runtime.scriptParsed
        self._script_registry: dict[str, dict] = {}
        # url → [content_hash, ...] — one entry per execution of that URL
        self._url_hashes: dict[str, list[str]] = {}
        # synthetic inline-script ID (cdpprov://dynamic-inline/<hash>) → {creator, hash, preview}
        self._inline_scripts: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Setup (call before navigation)
    # ------------------------------------------------------------------

    def inject_script(self) -> str:
        return _INJECT_JS

    def rebase(self, page_origin: str) -> None:
        """Label against ``page_origin`` from now on, e.g. after a cross-site
        redirect moved the page to a different registrable domain. Requests
        already logged to the new first party leave the third-party log."""
        if not page_origin or page_origin == self.page_origin:
            return
        self.page_origin = page_origin
        self._network = [r for r in self._network if r.get("domain") != page_origin]
        drop = f"→3p:{page_origin}"
        for url, bucket in self._script_3p.items():
            self._script_3p[url] = [e for e in bucket if e != drop]

    def enable_network_tracking(self, cdp) -> None:
        cdp.send("Network.enable", {})
        cdp.on("Network.requestWillBeSent", self._on_request)
        cdp.send("Runtime.enable", {})
        cdp.on("Runtime.executionContextCreated", self._on_context_created)
        # Debugger.scriptParsed fires for every script V8 compiles and reliably
        # includes the content hash and scriptId needed for execution-level identity.
        cdp.send("Debugger.enable", {})
        cdp.on("Debugger.scriptParsed", self._on_script_parsed)

    def _on_script_parsed(self, event: dict) -> None:
        script_id = event.get("scriptId")
        if not script_id:
            return
        url  = event.get("url", "")
        h    = event.get("hash", "")        # SHA256 of source bytes; may be ""
        rec  = {
            "url":       url,
            "hash":      h,
            "contextId": event.get("executionContextId"),
            "stack":     event.get("stackTrace"),
        }
        self._script_registry[script_id] = rec
        if url:
            self._url_hashes.setdefault(url, []).append(h[:8] if h else "")

    def _on_context_created(self, event: dict) -> None:
        ctx = event.get("context", {})
        aux = ctx.get("auxData", {})
        # Only track default (main world) contexts, not isolated worlds
        if aux.get("isDefault") and aux.get("frameId"):
            self._frame_contexts[aux["frameId"]] = ctx["id"]

    def _on_request(self, event: dict) -> None:
        url    = (event.get("request") or {}).get("url", "")
        domain = _etld1(url)
        if not domain or domain == self.page_origin:
            return

        initiator      = event.get("initiator") or {}
        stack          = initiator.get("stack") or {}
        frames         = stack.get("callFrames") or []
        initiator_url  = ""

        if frames:
            # Skip frames with no URL (e.g. our injected wrapper frames) and take
            # the first real caller URL.
            for frame in frames:
                if frame.get("url"):
                    initiator_url = frame["url"]
                    break
        elif initiator.get("type") == "script":
            initiator_url = initiator.get("url", "")

        self._network.append({"url": url, "domain": domain, "initiator_script": initiator_url})

        if initiator_url:
            bucket = self._script_3p.setdefault(initiator_url, [])
            entry  = f"→3p:{domain}"
            if entry not in bucket:
                bucket.append(entry)

    # ------------------------------------------------------------------
    # Collection (call after page settles)
    # ------------------------------------------------------------------

    def collect(self, cdp) -> dict:
        """
        Returns the full provenance schema documented at the top of this file.
        Elements not in the returned dict were created by the HTML parser.

        Strategy:
          1. Run _COLLECT_JS per frame to gather provenance dicts (keyed by frameId|nid).
          2. Use per-frame querySelectorAll in the main world, then
             DOM.describeNode for backendNodeId + nid.
        """
        # ── Step 1: gather provenance records from every frame ────────────────
        nid_to_prov: dict[str, dict] = {}

        try:
            frame_tree = cdp.send("Page.getFrameTree", {})
            frame_ids  = _collect_frame_ids(frame_tree.get("frameTree", {}))
        except Exception as e:
            print(f"  CDPProvenance: getFrameTree failed: {e}")
            frame_ids = []

        if not frame_ids:
            frame_ids = [None]

        # The frame tree is root-first, so frame_ids[0] is the top/main frame.
        top_fid = frame_ids[0] if frame_ids else None

        for fid in frame_ids:
            ctx_id = self._frame_contexts.get(fid) if fid else None
            self._collect_frame_prov(cdp, fid, ctx_id, nid_to_prov,
                                     is_top=(fid == top_fid))

        if not nid_to_prov:
            print(f"  CDPProvenance: inject script returned no records "
                  f"(0 elements, {len(self._network)} 3p requests)")
            return self._build_result({})

        # ── Step 2: resolve [data-cdp-pid] elements via Runtime.evaluate ────
        # DOM.performSearch cannot find attributes set via JavaScript; use
        # querySelectorAll evaluated in the page's main world instead, then
        # resolve each element to a backendNodeId via DOM.describeNode(objectId).
        elements: dict[int, dict] = {}
        try:
            cdp.send("DOM.enable", {})

            for fid in frame_ids:
                ctx_id = self._frame_contexts.get(fid) if fid else None
                # Never skip the top frame on a missing context — fall through to
                # a contextId-less evaluate (default main world). Only child
                # frames with no recorded context are skipped.
                if fid and ctx_id is None and fid != top_fid:
                    continue

                eval_params = {
                    "expression":   "Array.from(document.querySelectorAll('[data-cdp-pid]'))",
                    "returnByValue": False,
                }
                if ctx_id is not None:
                    eval_params["contextId"] = ctx_id

                eval_res = cdp.send("Runtime.evaluate", eval_params)
                array_obj_id = (eval_res.get("result") or {}).get("objectId")

                if array_obj_id:
                    props = cdp.send("Runtime.getProperties", {
                        "objectId":      array_obj_id,
                        "ownProperties": True,
                    }).get("result", [])

                    for prop in props:
                        if not prop.get("name", "").isdigit():
                            continue
                        val = prop.get("value") or {}
                        if val.get("type") != "object":
                            continue
                        elem_obj_id = val.get("objectId")
                        if not elem_obj_id:
                            continue

                        try:
                            desc       = cdp.send("DOM.describeNode", {"objectId": elem_obj_id})["node"]
                            backend_id = desc["backendNodeId"]
                            tag        = desc["nodeName"].lower()
                            attrs      = desc.get("attributes", [])   # [name, val, name, val …]
                            nid_str    = None
                            for i in range(0, len(attrs) - 1, 2):
                                if attrs[i] == "data-cdp-pid":
                                    nid_str = attrs[i + 1]
                                    break

                            frame_key = str(fid or "")
                            prov_key  = f"{frame_key}|{nid_str}" if nid_str is not None else None
                            if prov_key is None or prov_key not in nid_to_prov:
                                continue

                            data         = nid_to_prov[prov_key]
                            creator_url  = data.get("creator") or ""
                            inserter_url = data.get("inserter") or ""
                            uh = self._url_hashes
                            creator  = _classify(creator_url,  self.page_origin, uh)
                            inserter = _classify(inserter_url, self.page_origin, uh) if inserter_url else None

                            attr_mods = []
                            seen_mods: set = set()
                            for mod in (data.get("attrMods") or []):
                                party = _classify(mod.get("by", ""), self.page_origin, uh)
                                key   = (mod["attr"], party)
                                if key not in seen_mods:
                                    attr_mods.append({"attr": mod["attr"], "by": party})
                                    seen_mods.add(key)

                            # Text/content provenance: a script writing text
                            # into an element does not change the element's
                            # creator, but it taints the content. Classify each
                            # modifier to a party (fail-closed via _classify).
                            text_mods = []
                            for mod in (data.get("text_mods") or []):
                                party = _classify(mod.get("by", ""), self.page_origin, uh)
                                if party not in text_mods:
                                    text_mods.append(party)

                            listeners = []
                            for lurl in (data.get("listeners") or []):
                                party = _classify(lurl, self.page_origin, uh)
                                if party not in listeners:
                                    listeners.append(party)

                            loads = []
                            for load in (data.get("loads") or []):
                                domain = _etld1(load.get("url", ""))
                                if domain and domain != self.page_origin:
                                    entry = f"{load['attr']}→3p:{domain}"
                                    if entry not in loads:
                                        loads.append(entry)
                            for entry in self._script_3p.get(creator_url, []):
                                if entry not in loads:
                                    loads.append(entry)

                            rec_out = {
                                "tag":       tag,
                                "creator":   creator,
                                "via":       data.get("via") or "createElement",
                                "inserter":  inserter if inserter != creator else None,
                                "attr_mods": attr_mods,
                                "text_mods": text_mods,
                                "listeners": listeners,
                                "loads":     loads,
                                "frameId":   data.get("frameId") or fid,
                            }
                            if data.get("viaInlineId"):
                                rec_out["via_inline_id"] = data["viaInlineId"]
                            elements[backend_id] = rec_out
                        except Exception:
                            continue

        except Exception as e:
            print(f"  CDPProvenance: element collection failed: {e}")

        print(f"  CDPProvenance: {len(elements)} elements tracked, {len(self._network)} 3p requests")
        return self._build_result(elements)

    def _collect_frame_prov(self, cdp, frame_id, ctx_id, nid_to_prov: dict,
                            is_top: bool = False) -> None:
        fid_label = frame_id[:8] if frame_id else "main"
        try:
            if frame_id and ctx_id is None and not is_top:
                # A child frame whose main-world context we never observed. We
                # cannot reach it without a contextId; skip rather than evaluate
                # in the wrong (top) world. (Soundness note: such frames are
                # under-collected, not mis-collected.)
                print(f"  CDPProvenance: frame {fid_label}: no main-world context")
                return
            # The TOP frame must never be skipped: if its context wasn't recorded
            # (a race), fall back to a contextId-less evaluate, which resolves to
            # the default main world. Dropping the top frame would silently lose
            # all main-document provenance and read as parser/first-party.
            params = {
                "expression":    _COLLECT_JS.replace("__CDP_FRAME_ID__", json.dumps(frame_id)),
                "returnByValue": True,
            }
            if ctx_id is not None:
                params["contextId"] = ctx_id
            raw  = cdp.send("Runtime.evaluate", params)
            data = json.loads(raw["result"]["value"])
            nodes          = data.get("nodes", {})
            inline_scripts = data.get("inlineScripts", {})
            record_frame_id = data.get("frameId") or frame_id or ""
            for nid, rec in nodes.items():
                rec["frameId"] = record_frame_id
                nid_to_prov[f"{record_frame_id}|{nid}"] = rec
            self._inline_scripts.update(inline_scripts)
            print(f"  CDPProvenance: frame {fid_label}: {len(nodes)} prov records, "
                  f"{len(inline_scripts)} dynamic inline scripts")
        except Exception as e:
            print(f"  CDPProvenance: frame {fid_label} collect failed: {e}")

    def _build_result(self, elements: dict) -> dict:
        uh = self._url_hashes

        # Resolve synthetic dynamic-inline URLs back to the original creator.
        # _on_request stores Chrome's reported initiator URL raw; when a request
        # fires from inside a dynamically-injected inline script, V8 reports the
        # cdpprov://dynamic-inline/<hash> sourceURL we appended at insert time.
        # Resolve here so downstream consumers see the real culprit.
        def _resolve_synthetic(url: str) -> str:
            if url and url.startswith("cdpprov://dynamic-inline/"):
                info = self._inline_scripts.get(url)
                if info and info.get("creator"):
                    return info["creator"]
            return url

        for r in self._network:
            r["initiator_script"] = _resolve_synthetic(r.get("initiator_script", ""))

        # Re-key _script_3p so resolved URLs merge into the correct buckets.
        merged_3p: dict[str, list] = {}
        for url, loads in self._script_3p.items():
            real_url = _resolve_synthetic(url)
            bucket   = merged_3p.setdefault(real_url, [])
            for entry in loads:
                if entry not in bucket:
                    bucket.append(entry)

        scripts = {
            url: {"cls": _classify(url, self.page_origin, uh), "3p_loads": loads}
            for url, loads in merged_3p.items()
        }
        inline_scripts = {
            sid: {
                "creator":     _classify(info.get("creator", ""), self.page_origin, uh),
                "creator_url": info.get("creator", ""),
                "hash":        info.get("hash", ""),
                "preview":     info.get("preview", ""),
            }
            for sid, info in self._inline_scripts.items()
        }
        return {
            "page_origin":      self.page_origin,
            "elements":         elements,
            "scripts":          scripts,
            "network":          self._network,
            "script_instances": self._script_registry,
            "inline_scripts":   inline_scripts,
            "coverage":         _attribution_coverage(elements),
        }


def _attribution_coverage(elements: dict) -> dict:
    """Attribution coverage over script-touched elements. Buckets each tracked
    element by its creator class:

      - ``first_party``  — positively attributed to the first party
      - ``third_party``  — attributed to a third party
      - ``unknown``      — a script created it but we could not attribute it;
                           treated as conservatively tainted, NEVER as 1p

    Parser-created elements are not in ``elements`` (provenance is null), so this
    is coverage of the *script-created* surface, not the whole DOM. A non-trivial
    ``unknown`` fraction is the honest "limitation" signal for measurement.
    """
    buckets = {"first_party": 0, "third_party": 0, "unknown": 0}
    for rec in elements.values():
        creator = rec.get("creator") or ""
        if creator == "unknown":
            buckets["unknown"] += 1
        elif creator.startswith("3p:"):
            buckets["third_party"] += 1
        elif creator.startswith("1p:"):
            buckets["first_party"] += 1
        else:
            buckets["unknown"] += 1  # anything unrecognized fails closed
    buckets["tracked_total"] = sum(
        buckets[k] for k in ("first_party", "third_party", "unknown"))
    return buckets
