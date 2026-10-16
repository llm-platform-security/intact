"""Standard HTML, SVG, and MathML tag names, for the operation log of Intact's planner."""

# Standard web-platform element names (lowercased): HTML (current + legacy/
# deprecated), SVG, and MathML. A custom element is identified by EXCLUSION —
# any tag not in this set is treated as custom (web component or otherwise
# non-standard) — rather than by the HTML-spec "must contain a hyphen" pattern,
# which misses non-hyphenated non-standard tags.
_STANDARD_HTML = {
    "a", "abbr", "address", "area", "article", "aside", "audio", "b", "base",
    "bdi", "bdo", "blockquote", "body", "br", "button", "canvas", "caption",
    "cite", "code", "col", "colgroup", "data", "datalist", "dd", "del",
    "details", "dfn", "dialog", "div", "dl", "dt", "em", "embed", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "head", "header", "hgroup", "hr", "html", "i", "iframe", "img",
    "input", "ins", "kbd", "label", "legend", "li", "link", "main", "map",
    "mark", "menu", "meta", "meter", "nav", "noscript", "object", "ol",
    "optgroup", "option", "output", "p", "param", "picture", "pre", "progress",
    "q", "rp", "rt", "ruby", "s", "samp", "script", "search", "section",
    "select", "slot", "small", "source", "span", "strong", "style", "sub",
    "summary", "sup", "table", "tbody", "td", "template", "textarea", "tfoot",
    "th", "thead", "time", "title", "tr", "track", "u", "ul", "var", "video",
    "wbr",
    # legacy / deprecated but still standard-defined
    "acronym", "applet", "basefont", "bgsound", "big", "blink", "center",
    "dir", "font", "frame", "frameset", "image", "isindex", "keygen",
    "marquee", "menuitem", "nobr", "noembed", "noframes", "plaintext", "rb",
    "rtc", "spacer", "strike", "tt", "xmp",
}
_STANDARD_SVG = {
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
    "polygon", "text", "tspan", "textpath", "defs", "clippath",
    "lineargradient", "radialgradient", "stop", "use", "symbol", "mask",
    "pattern", "foreignobject", "marker", "filter", "fegaussianblur",
    "feoffset", "feblend", "fecolormatrix", "fecomposite", "femerge",
    "femergenode", "feflood", "feimage", "femorphology", "fespecularlighting",
    "fediffuselighting", "feturbulence", "fedisplacementmap", "fetile",
    "fecomponenttransfer", "fefuncr", "fefuncg", "fefuncb", "fefunca",
    "desc", "metadata", "switch", "animate", "animatetransform",
    "animatemotion", "mpath", "set", "view",
}
_STANDARD_MATHML = {
    "math", "mrow", "mi", "mn", "mo", "ms", "mtext", "mspace", "mfrac",
    "msqrt", "mroot", "mstyle", "merror", "mpadded", "mphantom", "mfenced",
    "menclose", "msub", "msup", "msubsup", "munder", "mover", "munderover",
    "mmultiscripts", "mtable", "mtr", "mtd", "mlabeledtr", "maction",
    "annotation", "annotation-xml", "semantics",
}
_STANDARD_TAGS = _STANDARD_HTML | _STANDARD_SVG | _STANDARD_MATHML
