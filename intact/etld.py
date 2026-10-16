"""Canonical eTLD+1 (registrable domain) extraction, Public Suffix List backed.

A last-two-labels approximation of the registrable domain mislabels:
  - multi-label public suffixes: ``attacker.co.uk`` vs ``victim.co.uk`` collapse
    to the same party (``co.uk``);
  - IP literals: ``127.0.0.1`` becomes ``0.1``;
  - hosting suffixes: ``foo.github.io`` and ``bar.github.io`` collapse together.

Design decisions:
  - **Bundled PSL snapshot** (``suffix_list_urls=()``): no network fetch at
    runtime, so labels are deterministic and reproducible across a crawl. The
    snapshot is pinned by the installed ``tldextract`` version.
  - **Private domains included** (``include_psl_private_domains=True``): hosting
    suffixes such as ``github.io`` and ``s3.amazonaws.com`` are treated as party
    boundaries, so ``foo.github.io`` and ``bar.github.io`` are distinct parties.
    This matches third-party taint semantics (separately-controlled content
    under a shared host is a separate party).
  - **IP literals** (v4/v6) map to themselves — each IP is its own party.
  - **Single-label hosts** (``localhost``, bare intranet names) map to
    themselves.

Known limitation: this is eTLD+1 only. Editorially same-owner domains with
different registrable domains (``cnn.com`` vs ``cnn.io``) classify as
different parties. An owner-group table would be a separate layer.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import tempfile

import tldextract

# Bundled snapshot, private domains as boundaries. Constructed once (it loads
# the PSL into memory); reused for every call.
#
# cache_dir is pinned to a writable temp location rather than the default
# ~/.cache: on locked-down/CI machines the home cache can be unwritable, and
# tldextract would raise a PermissionError mid-classification. With
# suffix_list_urls=() it never fetches over the network, so the cache is only a
# parse cache and a temp dir is fine and deterministic.
_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(),
    include_psl_private_domains=True,
    cache_dir=tempfile.gettempdir() + "/tldextract_cache",
)


# Non-network/opaque URI schemes that carry no host. A blob:/data: creator
# token has no party of its own; the consumer resolves these via the creation
# chain or to `unknown`. `cdpprov` is our internal synthetic-id scheme — it must
# never be treated as a real party (otherwise a leaked id becomes a fabricated
# `3p:dynamic-eval`); it resolves to no host → `unknown`.
_OPAQUE_SCHEMES = {"about", "data", "blob", "javascript", "mailto", "tel", "file",
                   "cdpprov"}


def _hostname(host_or_url: str) -> str:
    """Extract a lowercase hostname from a full URL, host:port, or bare host."""
    if not host_or_url:
        return ""
    s = host_or_url.strip()
    try:
        parsed = urlparse(s)
        if parsed.scheme.lower() in _OPAQUE_SCHEMES:
            return ""
        if parsed.netloc:
            # Absolute (http://host/…) or scheme-relative (//host/…)
            host = parsed.hostname or ""
        else:
            # Bare host, host:port, or host/path — prefix '//' so urlparse
            # treats the first segment as a netloc rather than a scheme or path.
            host = urlparse("//" + s).hostname or ""
    except ValueError:
        # Malformed, e.g. a bracketed host that is not an IP literal
        # ("https://[ccpa-preferences]/"), which Python 3.11+ rejects.
        return ""
    return (host or "").lower().strip(".")


def etld1(host_or_url: str) -> str:
    """Return the eTLD+1 (registrable domain) for a URL or hostname.

    IP literals and single-label hosts return themselves. Empty/unparsable
    input returns "".
    """
    host = _hostname(host_or_url)
    if not host:
        return ""
    # IP literal (v4 or v6) → its own party.
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    # Single-label host (localhost, intranet) → itself.
    if "." not in host:
        return host
    # Fail safe: a classifier must not crash on a PSL/cache hiccup. On any
    # extractor error, return the bare host so the caller still gets a usable
    # (if coarser) party rather than an exception.
    try:
        res = _EXTRACT(host)
    except Exception:
        return host
    # tldextract>=5.3 renamed registered_domain -> top_domain_under_public_suffix
    # (the old name emits a DeprecationWarning). Prefer the new name; only fall
    # back to the old one if the attribute is genuinely absent (older versions).
    reg = getattr(res, "top_domain_under_public_suffix", None)
    if reg is None:
        reg = res.registered_domain
    return reg or host
