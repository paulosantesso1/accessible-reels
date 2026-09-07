
import pytest

from instagram.search import normalize_reel_results, validate_reel_url
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


