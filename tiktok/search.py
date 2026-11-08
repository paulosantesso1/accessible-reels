from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from tiktok.video_controls import VideoControlError, select_current_url


SEARCH_RESULTS_SCRIPT = r"""() => {
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const results = [];
    const seen = new Set();
    const videoAnchors = [...document.querySelectorAll('a[href*="/video/"]')];
    const liveAnchors = [...document.querySelectorAll('a[href*="/live"]')];
    for (const anchor of [...videoAnchors, ...liveAnchors]) {
        let url;
        try { url = new URL(anchor.href, location.href).href; } catch (_error) { continue; }
        const pathname = new URL(url).pathname;
        const liveMatch = pathname.match(/\/(\@[^/?#]+)\/live\/?$/);
        const videoMatch = pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
        if (!liveMatch && !videoMatch) continue;
        const key = liveMatch ? liveMatch[0] : videoMatch[0];
        if (seen.has(key)) continue;
        seen.add(key);
        const container = anchor.closest(
            '[data-e2e="search-card-video-container"], [data-e2e="user-post-item"], [data-e2e="search-card-live-container"], li'
        ) || anchor.parentElement;
        const image = anchor.querySelector('img') || (container && container.querySelector('img'));
        const description = clean(
            (image && (image.alt || image.getAttribute('aria-label'))) ||
            anchor.getAttribute('aria-label') || anchor.title ||
            (container && container.innerText) || ''
        );
        results.push({
            url,
            author: decodeURIComponent(liveMatch ? liveMatch[1] : videoMatch[1]),
            description,
            is_live: Boolean(liveMatch)
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
    is_live: bool = False

    @property
    def label(self) -> str:
        prefix = "[AO VIVO] " if self.is_live else ""
        detail = self.description or ("Transmissão ao vivo" if self.is_live else "Vídeo sem descrição")
        return f"{prefix}{self.author}: {detail}"


def search_url(query: str, include_lives: bool = False) -> str:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        raise VideoControlError("Digite algo para pesquisar.")
    if include_lives:
        return f"https://www.tiktok.com/search?q={quote_plus(normalized)}"
    return f"https://www.tiktok.com/search/video?q={quote_plus(normalized)}"


LIBRARY_LIMIT = 500


def normalize_search_results(values: Any, limit: int = 50) -> tuple[SearchResult, ...]:
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
        is_live = bool(value.get("is_live")) or url.endswith("/live")
        results.append(SearchResult(url, author, description, is_live=is_live))
        if len(results) >= limit:
            break
    return tuple(results)


def validate_search_result_url(value: Any) -> str:
    return select_current_url(value, "https://www.tiktok.com/")
