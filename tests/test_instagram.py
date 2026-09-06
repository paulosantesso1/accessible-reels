from unittest.mock import Mock

import pytest

from instagram.search import normalize_reel_results, validate_reel_url
from tiktok.browser_extension import BRIDGE_PORT, INSTAGRAM_BRIDGE_PORT, LocalBrowserWorker
from tiktok.client import BrowserCommand
from tiktok.video_controls import VideoControlError


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/reel/AbC_123-/",
    "https://instagram.com/reels/AbC_123-/?tracking=1#x",
])
def test_reel_link_is_canonical_and_removes_tracking(url):
    assert validate_reel_url(url) == "https://www.instagram.com/reel/AbC_123-/"


@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@a/video/123", "https://instagram.com.evil.test/reel/123/",
    "javascript:alert(1)", "http://instagram.com/reel/123/",
    "https://instagram.com/reels/", "https://instagram.com/reels/audio/123/",
    "https://instagram.com:8000/reel/123/", "https://a:b@instagram.com/reel/123/",
])
def test_reel_links_reject_other_destinations(url):
    with pytest.raises(VideoControlError):
        validate_reel_url(url)


def test_search_results_filter_invalid_and_duplicate_urls():
    results = normalize_reel_results([
        {"url": "https://instagram.com/reels/abc/", "author": "@ana"},
        {"url": "https://instagram.com/reel/abc/?x=1"},
        {"url": "https://www.tiktok.com/@ana/video/123"},
        {"url": "https://instagram.com/p/xyz/", "description": "  um  post "},
    ])
    assert len(results) == 2
    assert results[0].author == "@ana"
    assert results[1].description == "um post"


def test_workers_have_independent_platforms_and_ports():
    tiktok = LocalBrowserWorker(lambda _: None)
    instagram = LocalBrowserWorker(lambda _: None, platform="instagram")
    assert tiktok._bridge.port == BRIDGE_PORT
    assert instagram._bridge.port == INSTAGRAM_BRIDGE_PORT
    assert instagram._bridge.platform == "instagram"
    instagram.next_video()
    assert instagram._commands.get_nowait() == BrowserCommand("next")
    assert tiktok._commands.empty()


def test_instagram_worker_validates_and_returns_search_results():
    events = []
    worker = LocalBrowserWorker(events.append, platform="instagram")
    worker._bridge = Mock()
    worker._bridge.execute.return_value = {"ok": True, "results": [
        {"url": "https://instagram.com/reels/abc/", "author": "@ana"}
    ]}
    worker._execute(BrowserCommand("search", "gatos"))
    worker._bridge.execute.assert_called_once_with("search", "gatos", timeout=25)
    assert events[0].search_results[0].url == "https://www.instagram.com/reel/abc/"
    worker.open_search_result("https://instagram.com/p/abc/")
    assert worker._commands.get_nowait() == BrowserCommand("open_search_result", "https://www.instagram.com/p/abc/")


def test_instagram_shutdown_targets_only_instagram():
    worker = LocalBrowserWorker(lambda _: None, platform="instagram")
    worker._bridge = Mock()
    worker.shutdown()
    worker.run()
    worker._bridge.execute.assert_called_once_with("close_instagram", timeout=4)
    worker._bridge.stop.assert_called_once()


def test_instagram_open_verifies_version_before_opening_tab():
    worker = LocalBrowserWorker(lambda _: None, platform="instagram", open_minimized=False)
    worker._bridge = Mock()
    worker._bridge.execute.return_value = {"ok": True, "version": "1.3.0"}
    worker._execute(BrowserCommand("open"))
    assert [call.args[0] for call in worker._bridge.execute.call_args_list] == ["extension_info", "open_platform"]


def test_instagram_old_extension_does_not_open_tab():
    worker = LocalBrowserWorker(lambda _: None, platform="instagram", open_minimized=False)
    worker._bridge = Mock()
    worker._bridge.execute.return_value = {"version": "1.2.1"}
    with pytest.raises(VideoControlError, match="desatualizada"):
        worker._execute(BrowserCommand("open"))
    worker._bridge.execute.assert_called_once_with("extension_info", timeout=12)
