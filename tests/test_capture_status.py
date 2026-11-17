"""Capture status: was the capture a usable page, a failed load, or a bot
block / challenge? Recorded per capture so analyses can exclude bad pages."""

from intact.cli import status as C


def test_ok_page():
    info = C.classify_capture("https://example.com", "https://www.example.com/",
                              "Example Domain", ["Welcome"])
    assert info["status"] == "ok" and info["cross_site_redirect"] is False


def test_chrome_error_page_is_error():
    info = C.classify_capture("https://down.example", "chrome-error://chromewebdata/",
                              "down.example", [])
    assert info["status"] == "error"


def test_cloudflare_challenge_title_is_blocked():
    info = C.classify_capture("https://site.com", "https://site.com/",
                              "Just a moment...", ["Checking your browser"])
    assert info["status"] == "blocked"


def test_cloudflare_block_page_is_blocked():
    info = C.classify_capture("https://upi.com", "https://upi.com/",
                              "Attention Required! | Cloudflare",
                              ["Sorry, you have been blocked"])
    assert info["status"] == "blocked"


def test_block_text_without_telltale_title_is_blocked():
    info = C.classify_capture("https://shop.com", "https://shop.com/",
                              "shop.com", ["Access Denied", "You don't have permission"])
    assert info["status"] == "blocked"


def test_ordinary_page_mentioning_captcha_in_body_is_not_blocked():
    info = C.classify_capture("https://blog.com", "https://blog.com/post",
                              "How CAPTCHAs work", ["Solving a captcha is ..."])
    assert info["status"] == "ok"


def test_cross_site_redirect_is_flagged_but_ok():
    info = C.classify_capture("https://3dcart.com", "https://www.shift4shop.com/",
                              "Shift4Shop", ["Ecommerce"])
    assert info["status"] == "ok" and info["cross_site_redirect"] is True
    assert info["final_url"] == "https://www.shift4shop.com/"


def test_retry_only_for_failed_or_blocked():
    assert C.should_retry({"status": "error"})
    assert C.should_retry({"status": "blocked"})
    assert not C.should_retry({"status": "ok"})


def _state(title, texts, n_extra=0, doc=0):
    els = [{"tag": "title", "text": title, "doc_index": doc}]
    els += [{"tag": "p", "text": t, "doc_index": doc} for t in texts]
    els += [{"tag": "div", "doc_index": doc} for _ in range(n_extra)]
    return {"elements": els}


def test_info_from_state_reads_title_and_top_document_text():
    info = C.info_from_state(_state("Attention Required! | Cloudflare",
                                    ["Sorry, you have been blocked"]),
                             "https://upi.com", "https://upi.com/")
    assert info["status"] == "blocked" and info["title"].startswith("Attention")


def test_info_from_state_ignores_block_phrases_on_large_pages():
    info = C.info_from_state(_state("News", ["Access denied to the archive, says court"],
                                    n_extra=500),
                             "https://news.com", "https://news.com/")
    assert info["status"] == "ok"
