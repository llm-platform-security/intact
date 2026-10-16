"""Unit tests for the PSL-backed eTLD+1 extraction (intact/etld.py).

Covers the cases a last-two-labels heuristic gets wrong.
"""

import pytest

from intact.etld import etld1


@pytest.mark.parametrize("inp,expected", [
    # Plain registrable domains
    ("https://www.cnn.com/x", "cnn.com"),
    ("cnn.com", "cnn.com"),
    ("sub.dom.example.com", "example.com"),
    # Multi-label public suffix — the headline bug: must NOT collapse to co.uk
    ("https://a.attacker.co.uk/p", "attacker.co.uk"),
    ("victim.co.uk", "victim.co.uk"),
    # Private/hosting suffixes are party boundaries
    ("foo.github.io", "foo.github.io"),
    ("bar.github.io", "bar.github.io"),
    ("x.s3.amazonaws.com", "x.s3.amazonaws.com"),
    # IP literals map to themselves (a last-two-labels heuristic gives "0.1")
    ("http://127.0.0.1:8091/a.js", "127.0.0.1"),
    ("127.0.0.1", "127.0.0.1"),
    # Single-label hosts
    ("http://localhost:8090/", "localhost"),
    ("localhost", "localhost"),
    # Empty / junk
    ("", ""),
    ("about:blank", ""),
    # Internal synthetic-id scheme must NOT become a real party (→ "" → unknown)
    ("cdpprov://dynamic-eval/abc123", ""),
    ("cdpprov://dynamic-inline/deadbeef", ""),
])
def test_etld1(inp, expected):
    assert etld1(inp) == expected


def test_distinct_parties_under_shared_public_suffix():
    # The two .co.uk sites must be different parties
    assert etld1("a.attacker.co.uk") != etld1("victim.co.uk")
    # The two github.io sites must be different parties
    assert etld1("foo.github.io") != etld1("bar.github.io")
