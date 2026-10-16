"""The command-line entry points, run with a stand-in browser session."""

import json

import pytest

from intact.cli import capture, crawl


class FakePage:
    url = "https://example.test/"

    def evaluate(self, script):
        return None


class FakeSession:
    """Stands in for BrowserSession: records how it was built and what it
    visited, and returns an empty capture."""
    instances = []

    def __init__(self, headless=False, ignore_https_errors=False, browser_args=None):
        self.headless = headless
        self.browser_args = list(browser_args or [])
        self.page = FakePage()
        self.visited = []
        FakeSession.instances.append(self)

    def navigate(self, url, wait=8.0):
        self.visited.append(url)

    def scroll(self, direction="down", amount=500):
        pass

    def capture(self):
        return {"elements": [], "ax_nodes": [], "provenance": {"elements": {}},
                "frames": [], "uncaptured_frames": []}

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch):
    FakeSession.instances = []
    monkeypatch.setattr(capture, "BrowserSession", FakeSession)
    monkeypatch.setattr("intact.browser.session.BrowserSession", FakeSession)
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)
    return FakeSession


def test_capture_is_headful_by_default_and_writes_to_the_current_directory(
        fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["capture", "https://example.test/", "0"])
    capture.main()
    session = fake.instances[0]
    assert session.headless is False
    assert session.browser_args == capture.STEALTH_ARGS
    out = tmp_path / "example.test"
    rep = json.loads((out / "representation.json").read_text())
    assert rep["url"] == "https://example.test/" and rep["element_count"] == 0
    assert (out / "ax_tree.json").exists() and (out / "provenance.json").exists()


def test_capture_headless_flag_and_explicit_output_directory(fake, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["capture", "https://example.test/a/b", "0",
                                     str(out), "--headless"])
    capture.main()
    assert fake.instances[0].headless is True
    assert (out / "example.test_a_b" / "representation.json").exists()


def test_capture_never_remaps_hosts(fake, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["capture", "https://example.test/", "0"])
    capture.main()
    assert not any(a.startswith("--host-resolver-rules")
                   for a in fake.instances[0].browser_args)
    assert not hasattr(capture, "_host_resolver_rules_arg")


def test_crawl_headless_flag_and_outputs(fake, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["crawl", str(tmp_path), "https://example.test/",
                                     "--headless"])
    crawl.main()
    session = fake.instances[0]
    assert session.headless is True
    assert session.visited == ["https://example.test/"]
    rep = json.loads((tmp_path / "example.test" / "representation.json").read_text())
    assert rep["capture"]["status"] == "ok" and rep["capture"]["attempts"] == 1


def test_crawl_is_headful_by_default(fake, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["crawl", str(tmp_path), "https://example.test/"])
    crawl.main()
    assert fake.instances[0].headless is False
