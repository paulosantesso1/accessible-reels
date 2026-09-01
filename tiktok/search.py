from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from tiktok.video_controls import VideoControlError, select_current_url


SEARCH_RESULTS_SCRIPT = r"""() => {
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const results = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('a[href*="/video/"]')) {
        let url;
        try { url = new URL(anchor.href, location.href).href; } catch (_error) { continue; }
        const match = new URL(url).pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
        if (!match || seen.has(match[0])) continue;
        seen.add(match[0]);
        const container = anchor.closest(
            '[data-e2e="search-card-video-container"], [data-e2e="user-post-item"], li'
        ) || anchor.parentElement;
        const image = anchor.querySelector('img') || (container && container.querySelector('img'));
        const description = clean(
            (image && (image.alt || image.getAttribute('aria-label'))) ||
            anchor.getAttribute('aria-label') || anchor.title ||
            (container && container.innerText) || ''
        );
        results.push({
            url,
            author: decodeURIComponent(match[1]),
            description
        });
        if (results.length >= 50) break;
    }
    return results;
}"""


@dataclass(frozen=True)
class SearchResult:
    url: str
    author: str
    description: str

    @property
    def label(self) -> str:
        detail = self.description or "Vídeo sem descrição"
        return f"{self.author}: {detail}"


def search_url(query: str) -> str:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        raise VideoControlError("Digite algo para pesquisar.")
    return f"https://www.tiktok.com/search/video?q={quote_plus(normalized)}"


def normalize_search_results(values: Any) -> tuple[SearchResult, ...]:
    if not isinstance(values, list):
        return ()
    results: list[SearchResult] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            url = select_current_url(value.get("url"), "https://www.tiktok.com/")
        except VideoControlError:
            continue
        if url in seen:
            continue
        seen.add(url)
        author = " ".join(str(value.get("author") or "Autor desconhecido").split())
        description = " ".join(str(value.get("description") or "").split())
        results.append(SearchResult(url, author, description))
        if len(results) >= 50:
            break
    return tuple(results)


def validate_search_result_url(value: Any) -> str:
    return select_current_url(value, "https://www.tiktok.com/")
