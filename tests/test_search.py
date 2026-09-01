from __future__ import annotations

import pytest

from tiktok.search import (
    SearchResult,
    normalize_search_results,
    search_url,
    validate_search_result_url,
)
from tiktok.video_controls import VideoControlError


def test_search_url_normalizes_and_encodes_query():
    assert search_url("  gatos   engraçados  ") == (
        "https://www.tiktok.com/search/video?q=gatos+engra%C3%A7ados"
    )


def test_empty_search_is_rejected():
    with pytest.raises(VideoControlError, match="Digite algo"):
        search_url("   ")


def test_search_results_are_canonical_deduplicated_and_safe():
    results = normalize_search_results(
        [
            {
                "url": "https://www.tiktok.com/@ana/video/123?tracking=1",
                "author": " @ana ",
                "description": " gato   feliz ",
            },
            {"url": "https://www.tiktok.com/@ana/video/123", "author": "duplicado"},
            {"url": "https://example.com/@x/video/999", "author": "inválido"},
        ]
    )
    assert results == (
        SearchResult(
            "https://www.tiktok.com/@ana/video/123", "@ana", "gato feliz"
        ),
    )
    assert results[0].label == "@ana: gato feliz"


def test_only_canonical_tiktok_video_can_be_opened():
    assert validate_search_result_url("https://m.tiktok.com/@ana/video/123?x=1") == (
        "https://www.tiktok.com/@ana/video/123"
    )
    with pytest.raises(VideoControlError):
        validate_search_result_url("https://example.com/@ana/video/123")
