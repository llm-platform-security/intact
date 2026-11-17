"""Browser-free unit tests for _classify fail-closed attribution.

These exercise the pure-Python resolution logic directly with synthetic creator
tokens — no browser needed — so the taint-soundness invariant can be
verified independently of the live capture pipeline.
"""

import pytest

from intact.instrumentation.cdp_provenance import _classify, _etld1, _attribution_coverage


# ---------------------------------------------------------------------------
# Fail-closed: unattributable script-created content -> "unknown" (never 1p)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", [
    "inline", "blob:https://cnn.com/abc", "data:text/js,1", "about:blank",
    # Leaked internal synthetic ids must resolve to unknown, not a fake 3p party.
    "cdpprov://dynamic-eval/abc123", "cdpprov://dynamic-inline/deadbeef",
])
def test_unattributable_script_creator_is_unknown(token):
    # A script created the node but we cannot identify its party. Must NOT be 1p.
    assert _classify(token, "cnn.com") == "unknown"


def test_empty_creator_is_parser_first_party():
    # Empty creator = parser content touched by a mutation wrapper (createElement
    # always records at least 'inline'). Parser content is first-party, not unknown.
    assert _classify("", "cnn.com") == "1p:inline"
    assert _classify(None, "cnn.com") == "1p:inline"


# ---------------------------------------------------------------------------
# Positive first-party: real URL whose domain == page origin
# ---------------------------------------------------------------------------

def test_same_origin_file_is_first_party():
    assert _classify("https://cnn.com/app.js", "cnn.com") == "1p:app.js"


def test_same_origin_document_url_is_inline_first_party():
    # Genuine inline script in the top document executes with the document URL;
    # no filename → 1p:inline (a *positive* attribution, not the fail-open default).
    assert _classify("https://cnn.com/", "cnn.com") == "1p:inline"


# ---------------------------------------------------------------------------
# Third-party
# ---------------------------------------------------------------------------

def test_third_party_basic():
    assert _classify("https://doubleclick.net/ads.js", "cnn.com").startswith("3p:doubleclick.net/ads.js")


def test_third_party_ip_origin():
    # IP literal is its own party (a last-two-labels heuristic gives "0.1").
    assert _classify("http://127.0.0.1:8091/tp.js", "localhost").startswith("3p:127.0.0.1/tp.js")


# ---------------------------------------------------------------------------
# PSL correctness: multi-label public suffix must not collapse parties
# ---------------------------------------------------------------------------

def test_psl_distinguishes_couk_parties():
    # attacker.co.uk must be 3p relative to victim.co.uk (a last-two-labels heuristic gives both "co.uk", i.e. 1p)
    label = _classify("https://a.attacker.co.uk/x.js", "victim.co.uk")
    assert label.startswith("3p:attacker.co.uk/")


def test_psl_same_party_couk():
    assert _classify("https://www.victim.co.uk/app.js", "victim.co.uk") == "1p:app.js"


# ---------------------------------------------------------------------------
# _etld1 delegates to the PSL extractor
# ---------------------------------------------------------------------------

def test_etld1_delegates_to_psl():
    assert _etld1("https://a.attacker.co.uk/x") == "attacker.co.uk"
    assert _etld1("http://127.0.0.1:8091/") == "127.0.0.1"


# ---------------------------------------------------------------------------
# Attribution coverage metric
# ---------------------------------------------------------------------------

def test_attribution_coverage_buckets():
    elements = {
        1: {"creator": "1p:app.js"},
        2: {"creator": "1p:inline"},
        3: {"creator": "3p:doubleclick.net/ads.js"},
        4: {"creator": "unknown"},
        5: {"creator": ""},   # unrecognized → fails closed to unknown, never 1p
    }
    cov = _attribution_coverage(elements)
    assert cov["first_party"] == 2
    assert cov["third_party"] == 1
    assert cov["unknown"] == 2          # explicit unknown + the empty (fail-closed)
    assert cov["tracked_total"] == 5
