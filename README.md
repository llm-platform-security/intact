# Intact

A framework for secure agentic web interactions.

- **Browser instrumentation.** Intact uses the Chrome DevTools Protocol (CDP) to register a script that runs in every frame before the page's own scripts. The script wraps the main DOM interfaces through which scripts create, insert, and modify elements, and it attributes each call to the script on the JavaScript call stack.
- **GenTree.** Intact builds GenTree, a representation of the page with one record per element. GenTree combines the DOM of every frame, the accessibility tree, and the instrumentation's provenance, and it labels each element with its capabilities: the interactions it affords, the effects those can have in the browser, and the channels through which its content reaches an agent.

Coming soon!

- **Planner.** Intact passes the page to the LLM one element of GenTree at a time, so the LLM decides on each element without any other element's text. Each call sees the user's request, the element's own markup, and a log of the operations decided so far.
- **Harness.** The harness turns the plan into browser actions. It executes each step only within the capabilities of the step's element, and it asks the user before it acts on third-party content.
- **Functionality extraction.** An LLM writes the tasks for our evaluation. It reads each page's markup, in the same view that the planner uses, and returns five realistic requests that a user might make of an agent on that page.
- **Attack benchmark.** The benchmark holds 1,091 real webpages, each with a user task and one injected attack. The paper compares Intact's planner with a conventional planner on these pages.

## Install

Intact needs Python 3.11 or later and drives Chromium through Playwright.

```bash
git clone https://github.com/llm-platform-security/intact
cd intact
pip install -e .
playwright install chromium
```

On Linux, `playwright install --with-deps chromium` also installs the system libraries.

`pyproject.toml` pins Playwright (1.58.0) and tldextract (5.3.1), because the Chromium build and the Public Suffix List snapshot both affect the labels.

## Capture a page

```bash
python -m intact.cli.capture https://example.com 6 out --headless
```

The arguments are the URL, the seconds to let the page settle (default 6), and the output directory (default: the current directory). The browser is headful unless you pass `--headless`. The command sets `navigator.webdriver` to false and scrolls the page briefly, as our crawl did, so that sites serve their usual content.

It writes three files to `out/<host>/` (for an inner page, the host plus its path):

| File | Content |
|---|---|
| `representation.json` | the page's GenTree |
| `ax_tree.json` | the raw accessibility tree from CDP |
| `provenance.json` | the raw provenance records, scripts, and third-party requests |

## Crawl many pages

```bash
python -m intact.cli.crawl out --url-file urls.txt --resume --skip-file skip.txt
```

The crawler reuses one browser for all URLs, given as arguments or in a file (one per line; it skips blank lines and `#` comments). It records each page's status in `representation.json` (`ok`, `error`, or `blocked` for a bot challenge) and retries a failed or blocked load once with a longer wait. `--resume` skips pages that already have a `representation.json`. `--skip-file` names a file of URLs to skip. When a page takes longer than five minutes, the crawler adds it to the file and exits with code 3, so that a supervisor loop can restart the crawler with `--resume`. The crawler, like `capture`, runs a headful browser unless you pass `--headless`, which a machine without a display needs.

## Use from Python

```python
from intact.browser.session import BrowserSession
from intact.gentree.serialize import serialize_representation
from intact.gentree.provenance_taint import is_provenance_tainted

session = BrowserSession(headless=True)
try:
    session.navigate("https://example.com", wait=6)
    state = session.capture()
finally:
    session.close()

gentree = serialize_representation(state, url="https://example.com")
untrusted = [e for e in gentree["elements"]
             if is_provenance_tainted(e["provenance"], e["document"]["scope"])]
```

`is_provenance_tainted` fails closed. An element is untrusted if a third party, or a script that the instrumentation could not identify, appears anywhere in its provenance, or if its document is third-party.

## Documentation

- [`intact/instrumentation/`](intact/instrumentation/README.md): what the instrumentation records.
- [`intact/gentree/`](intact/gentree/README.md): the GenTree record, field by field, and the capability labels.
- [`intact/gentree/taxonomy/`](intact/gentree/taxonomy/README.md): the rules that assign the capability labels.

## Tests

```bash
pip install -e '.[test]'
pytest
```

`pytest tests/test_attribution_cases.py` runs the paper's 24 attribution cases (Appendix C) and reports `24 passed, 1 xfailed`; the expected failure is the shadow-root gap below. The browser tests serve their pages through Playwright's request routing and open no local ports.

## Limitations

- The instrumentation does not yet cover cookies, `postMessage` exchanges, content that browser extensions inject, or shadow roots.
- The injected script runs in the page's JavaScript environment, so the instrumentation assumes that page scripts do not evade or tamper with it; moving the hooks into the browser, as prior in-browser instrumentation does, would remove this assumption.
- The taxonomy is static. It labels an element from its tag, attributes, ancestors, and computed style, and it does not see event listeners that scripts attach. Custom elements get interactions only from their attributes (e.g., an ARIA role or `tabindex`) or their ancestors.

## License

Apache License 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use this code in your research, please cite our paper:

```bibtex
@misc{iqbal2026intact,
  title={{What It Is, Not What It Says: Securing Agentic Browsing Interactions with Web Semantics}},
  author={Iqbal, Umar},
  howpublished={arXiv preprint},
  year={2026}
}
```
