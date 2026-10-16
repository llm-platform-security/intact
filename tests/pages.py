"""Pages that the browser tests load, served by Playwright request routing.

No test opens a local port: Playwright fulfills every request in-process
(`route.fulfill`). The first party is firstparty.test; third parties are
thirdparty.test and other .test hosts.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
FP = "https://firstparty.test/"
TP = "https://thirdparty.test/"
TP_DOMAIN = "thirdparty.test"
TP_LOAD = f"3p:{TP_DOMAIN}"          # `loads` entries name the destination's party


def tp(filename: str) -> str:
    """Creator-label prefix of a script at thirdparty.test/<filename>."""
    return f"3p:{TP_DOMAIN}/{filename}"


# 1x1 transparent GIF, served for every *.gif request.
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f9040100000000"
    "2c00000000010001000002024401003b")


@dataclass(frozen=True)
class Page:
    name: str
    url: str                        # entry URL
    resources: dict                 # URL -> body
    browser_args: tuple = ()
    ready: str | None = None        # JS predicate to wait for, else network idle
    settle: float = 0.4             # seconds to wait after that


def _content_type(url: str) -> str:
    return "application/javascript" if url.endswith(".js") else "text/html"


def route_handler(resources: dict):
    """Fulfill a request from `resources`; *.gif gets a 1x1 image and any
    other URL an empty 200 response."""
    def handler(route):
        url = route.request.url
        if url in resources:
            route.fulfill(status=200, content_type=_content_type(url),
                          body=resources[url])
        elif url.split("?")[0].endswith(".gif"):
            route.fulfill(status=200, content_type="image/gif", body=GIF)
        else:
            route.fulfill(status=200, content_type="text/plain", body="")
    return handler


@contextmanager
def open_page(session_cls, page: Page):
    """Load `page` in a fresh headless `session_cls` and yield the session."""
    session = session_cls(headless=True, browser_args=list(page.browser_args))
    try:
        session._context.route("**/*", route_handler(page.resources))
        session.navigate(page.url, wait=0.2)
        if page.ready:
            session.page.wait_for_function(page.ready, timeout=15_000)
        else:
            try:
                session.page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
        time.sleep(page.settle)
        yield session
    finally:
        session.close()


def backend_node_id(session, selector: str) -> int | None:
    """backendNodeId of the first main-document element matching `selector`."""
    cdp = session.cdp
    cdp.send("DOM.enable", {})
    doc = cdp.send("DOM.getDocument", {"depth": -1})
    node = cdp.send("DOM.querySelector",
                    {"nodeId": doc["root"]["nodeId"], "selector": selector})
    nid = node.get("nodeId", 0)
    if not nid:
        return None
    return cdp.send("DOM.describeNode", {"nodeId": nid})["node"]["backendNodeId"]


def capture(session_cls, page: Page, selectors=()) -> dict:
    """Capture `page` and resolve `selectors` to backendNodeIds before the
    browser closes. Playwright's sync API allows only one running sync
    Playwright instance per thread, so tests never keep one open across
    tests."""
    with open_page(session_cls, page) as session:
        state = session.capture()
        bni = {sel: backend_node_id(session, sel) for sel in selectors}
    return {"state": state, "provenance": state["provenance"],
            "ax_nodes": state["ax_nodes"], "bni": bni}


def element_by_id(state: dict, doc_url: str, el_id: str) -> dict | None:
    """The unified element record with id `el_id` in the document at `doc_url`."""
    for e in state["elements"]:
        if (e.get("document") or {}).get("url") == doc_url \
                and (e.get("attrs") or {}).get("id") == el_id:
            return e
    return None


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def _simple(name: str, html: str, scripts: dict | None = None) -> Page:
    return Page(name=name, url=FP, resources={FP: html, **(scripts or {})})


# The main page: tests/fixtures/index.html and the scripts it loads, including
# a chain inline -> chain_a.js -> chain_b.js; chain_b.js sets __testComplete
# once its timer callback has run.
MAIN = Page(
    name="main",
    url=FP,
    resources={
        FP: _fixture("index.html"),
        FP + "first_party.js": _fixture("first_party.js"),
        TP + "third_party.js": _fixture("third_party.js"),
        TP + "chain_a.js": _fixture("chain_a.js"),
        TP + "chain_b.js": _fixture("chain_b.js"),
    },
    ready="() => window.__testComplete === true",
)

INLINE_CREATE = _simple("inline-create", """<!doctype html><html><body>
      <script>
        var d = document.createElement('div');
        d.id = 'made-by-1p';
        document.body.appendChild(d);
      </script>
    </body></html>""")

TP_CREATE = _simple("3p-create", f"""<!doctype html><html><body>
      <div id="host"></div>
      <script src="{TP}maker.js"></script>
    </body></html>""", {
    TP + "maker.js": "var d=document.createElement('div'); d.id='made-by-3p';"
                     "document.getElementById('host').appendChild(d);"})

DOC_WRITE = _simple("document-write", f"""<!doctype html><html><body>
      <script src="{TP}writer.js"></script>
    </body></html>""", {
    TP + "writer.js": "document.write('<div id=\\'dw\\'>ad</div>');"})

EVAL = _simple("eval", f"""<!doctype html><html><body>
      <script src="{TP}evaler.js"></script>
    </body></html>""", {
    TP + "evaler.js": "eval(\"var s=document.createElement('span'); s.id='via-eval';"
                      "document.body.appendChild(s);\");"})

TEXT_REWRITE = _simple("text-rewrite", f"""<!doctype html><html><body>
      <div id="target">original</div>
      <script src="{TP}launder.js"></script>
    </body></html>""", {
    TP + "launder.js": "document.getElementById('target').textContent = 'injected by 3p';"})

IFRAME_3P = _simple("3p-iframe", f"""<!doctype html><html><body>
      <iframe src="{TP}frame.html"></iframe>
    </body></html>""", {
    TP + "frame.html": """<!doctype html><html><body><script>
      var d = document.createElement('div'); d.id = 'in-frame';
      document.body.appendChild(d);
    </script></body></html>"""})

DOMPARSER = _simple("domparser", f"""<!doctype html><html><body>
      <script src="{TP}dp.js"></script>
    </body></html>""", {
    TP + "dp.js": "var d=new DOMParser().parseFromString("
                  "'<div id=\\'dp-root\\'><a id=\\'dp-child\\' href=\\'//evil.test\\'>x</a></div>',"
                  "'text/html').body.firstChild;"
                  "document.body.appendChild(d);"})

CLONE = _simple("clone", f"""<!doctype html><html><body>
      <template id="tpl"><a id="orig" href="//evil.test">x</a></template>
      <script src="{TP}clone.js"></script>
    </body></html>""", {
    TP + "clone.js": "var src=document.getElementById('tpl').content.firstElementChild;"
                     "var c=src.cloneNode(true); c.id='cloned';"
                     "document.body.appendChild(c);"})

PLAIN_TEXT_INNERHTML = _simple("plain-text-innerhtml", f"""<!doctype html><html><body>
      <div id="t">orig</div>
      <script src="{TP}ih.js"></script>
    </body></html>""", {
    TP + "ih.js": "document.getElementById('t').innerHTML = 'injected 3p text';"})

ADJACENT_SIBLING = _simple("adjacent-sibling", f"""<!doctype html><html><body>
      <div id="anchor"></div>
      <script src="{TP}iah.js"></script>
    </body></html>""", {
    TP + "iah.js": "document.getElementById('anchor').insertAdjacentHTML("
                   "'beforebegin', '<span id=\\'sib\\'>x</span>');"})

ATTRIBUTE_WRITES = _simple("attribute-writes", f"""<!doctype html><html><body>
      <div id="target">original</div>
      <script src="{TP}attr.js"></script>
    </body></html>""", {
    TP + "attr.js": "var t=document.getElementById('target');"
                    "t.setAttribute('class','promo');"
                    "t.setAttribute('data-tracking','xyz');"})

SHADOW_ROOT = _simple("shadow-root", """<!doctype html><html><body>
      <div id="host"></div>
      <script>
        var sr = document.getElementById('host').attachShadow({mode:'open'});
        var d = document.createElement('div'); d.id = 'in-shadow';
        sr.appendChild(d);
      </script>
    </body></html>""")

# A cross-site iframe that --site-per-process isolates into its own renderer,
# and a same-site iframe that stays in the page's process.
FRAME_URL = TP + "frame.html"
SAME_SITE_URL = "https://sub.firstparty.test/frame.html"
ISOLATED_FRAMES = Page(
    name="isolated-frames",
    url=FP,
    resources={
        FP: (f'<html><body><p>top</p><iframe id="ad" src="{FRAME_URL}"></iframe>'
             f'<iframe id="same" src="{SAME_SITE_URL}"></iframe></body></html>'),
        FRAME_URL: ('<html><body><a id="in3p" href="https://evil.test/">3p link</a>'
                    '<button id="btn" onclick="document.body.dataset.clicked=\'1\'">go</button>'
                    '<script>var d=document.createElement("div");d.id="made-in-frame";'
                    'document.body.appendChild(d);</script></body></html>'),
        SAME_SITE_URL: '<html><body><a id="insame" href="/x">same-site link</a></body></html>',
    },
    browser_args=("--site-per-process",),
    settle=0.5,
)

# The site a redirect lands on (routing cannot mock a followed redirect).
NEW_SITE = "https://newsite.test/"
REDIRECT_LANDING = Page(
    name="redirect-landing",
    url=NEW_SITE,
    resources={
        NEW_SITE: ('<html><body><script src="https://newsite.test/app.js"></script>'
                   '</body></html>'),
        NEW_SITE + "app.js": ('var d=document.createElement("div");d.id="made-by-app";'
                              'document.body.appendChild(d);'),
    },
)

# A news-style page for the GenTree integration test: a logo link, a headline,
# a nav bar, teasers, a newsletter form, an ad iframe from thirdparty.test, a
# first-party script that adds a banner, and a third-party script that adds a
# tracking image.
_TEASERS = "\n".join(
    f'      <article class="teaser"><a href="/story/{i}"><h2>Story {i}</h2></a>'
    f'<p>Summary of story {i}.</p></article>' for i in range(1, 13))
NEWS_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="description" content="A news page for tests.">
  <meta property="og:title" content="Example News">
  <title>Example News</title>
</head>
<body>
  <header>
    <a class="logo" href="/" aria-label="Home"><img src="/logo.gif" alt=""></a>
    <nav class="primary-nav">
      <a href="/world">World</a>
      <a href="/politics">Politics</a>
      <a href="/business">Business</a>
      <a href="/science">Science</a>
    </nav>
  </header>
  <main>
    <h1 class="headline">City council approves new park</h1>
    <p class="byline">By A. Reporter</p>
    <section class="teasers">
{_TEASERS}
    </section>
    <form class="newsletter-form" action="/subscribe" method="post">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" placeholder="you@example.test">
      <input type="hidden" name="source" value="footer">
      <button type="submit">Subscribe</button>
    </form>
    <iframe id="ad-iframe" src="{TP}ad.html" width="300" height="250"></iframe>
  </main>
  <footer><p>Example News</p></footer>
  <script src="/app.js"></script>
  <script src="{TP}analytics.js"></script>
  <script>window.__pageReady = true;</script>
</body>
</html>"""
NEWS = Page(
    name="news",
    url=FP,
    resources={
        FP: NEWS_HTML,
        FP + "app.js": ("var b = document.createElement('div'); b.id = 'banner';"
                        "b.textContent = 'Breaking: test banner'; document.body.prepend(b);"),
        TP + "analytics.js": ("var p = document.createElement('img'); p.id = 'tracker';"
                              "p.src = 'https://thirdparty.test/pixel.gif';"
                              "document.body.appendChild(p);"),
        TP + "ad.html": ('<!doctype html><html><body><a id="ad-link" '
                         'href="https://advertiser.test/">Buy now</a><script>'
                         'var s = document.createElement("span"); s.id = "ad-note";'
                         's.textContent = "Sponsored"; document.body.appendChild(s);'
                         '</script></body></html>'),
    },
)

# A third-party script inserts an inline script that fetches from cdn.test twice:
# at once, and in a 20 ms timer. Chrome reports the inline script's synthetic
# cdpprov:// URL as both requests' initiator; the capture must resolve it to
# inserter.js. The timer sets __fetchesIssued once the second fetch is issued.
INSERTED_FETCH = Page(
    name="inserted-fetch",
    url=FP,
    resources={
        FP: f'<!doctype html><html><body><script src="{TP}inserter.js"></script></body></html>',
        TP + "inserter.js": ("var s = document.createElement('script');"
                             "s.textContent = \"fetch('https://cdn.test/sync', {mode: 'no-cors'});"
                             "setTimeout(function () {"
                             " fetch('https://cdn.test/async', {mode: 'no-cors'});"
                             " window.__fetchesIssued = true; }, 20);\";"
                             "document.head.appendChild(s);"),
    },
    ready="() => window.__fetchesIssued === true",
)

# A third-party script runs code from two opaque URLs: a blob: script, whose URL
# embeds the first party's origin, and a data: script, whose text names a
# first-party script URL. The blob: script creates an element at once and another
# in a timer callback; the data: script creates one. Each sets a flag after
# creating its element. Code from an opaque URL has no party of its own, so these
# elements are unattributed, while the two script elements that opaque.js inserts
# (#blob-tag, #data-tag) stay third party.
OPAQUE_SCRIPTS = Page(
    name="opaque-scripts",
    url=FP,
    resources={
        FP: f'<!doctype html><html><body><script src="{TP}opaque.js"></script></body></html>',
        TP + "opaque.js": ("var blob = new Blob([\"var d = document.createElement('div');"
                           " d.id = 'from-blob'; document.body.appendChild(d);"
                           " window.__blobRan = true;"
                           " setTimeout(function () { var t = document.createElement('div');"
                           " t.id = 'from-blob-timer'; document.body.appendChild(t);"
                           " window.__blobTimerRan = true; }, 20);\"],"
                           " {type: 'text/javascript'});"
                           "var b = document.createElement('script'); b.id = 'blob-tag';"
                           "b.src = URL.createObjectURL(blob); document.head.appendChild(b);"
                           "var s = document.createElement('script'); s.id = 'data-tag';"
                           f"s.src = \"data:text/javascript,/*{FP}app.js*/"
                           "var e = document.createElement('div'); e.id = 'from-data';"
                           " document.body.appendChild(e); window.__dataRan = true;\";"
                           "document.head.appendChild(s);"),
    },
    ready=("() => window.__blobRan === true && window.__blobTimerRan === true"
           " && window.__dataRan === true"),
)

ALL_PAGES = (MAIN, INLINE_CREATE, TP_CREATE, DOC_WRITE, EVAL, TEXT_REWRITE, IFRAME_3P,
             DOMPARSER, CLONE, PLAIN_TEXT_INNERHTML, ADJACENT_SIBLING, ATTRIBUTE_WRITES,
             SHADOW_ROOT, ISOLATED_FRAMES, REDIRECT_LANDING, NEWS, INSERTED_FETCH,
             OPAQUE_SCRIPTS)
