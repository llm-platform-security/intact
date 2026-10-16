"""Per-page watchdog for the crawler: a page that hangs past the timeout is
recorded in a skip file and the process exits (code 3) so the supervisor loop
restarts the shard with --resume, skipping that URL."""

import time

from intact.cli import crawl as C


def test_watchdog_fires_after_timeout():
    fired = []
    w = C.PageWatchdog(0.1, fired.append)
    w.start("https://a.test")
    time.sleep(0.35)
    assert fired == ["https://a.test"]


def test_stopped_watchdog_does_not_fire():
    fired = []
    w = C.PageWatchdog(0.2, fired.append)
    w.start("https://a.test")
    w.stop()
    time.sleep(0.4)
    assert fired == []


def test_restarting_watchdog_only_times_the_current_page():
    fired = []
    w = C.PageWatchdog(0.25, fired.append)
    w.start("https://a.test")
    time.sleep(0.1)
    w.start("https://b.test")
    time.sleep(0.45)
    w.stop()
    assert fired == ["https://b.test"]


def test_timeout_handler_records_url_and_exits_with_restart_code(tmp_path):
    skip = tmp_path / "skip.txt"
    codes = []
    handler = C.make_timeout_handler(skip, exit_fn=codes.append)
    handler("https://hung.test")
    assert "https://hung.test" in skip.read_text().split()
    assert codes == [C.WATCHDOG_EXIT]


def test_read_skip_file_missing_is_empty(tmp_path):
    assert C.read_skip_file(tmp_path / "nope.txt") == set()


def test_read_skip_file_lists_urls(tmp_path):
    p = tmp_path / "skip.txt"
    p.write_text("https://a.test\n\nhttps://b.test\n")
    assert C.read_skip_file(p) == {"https://a.test", "https://b.test"}
