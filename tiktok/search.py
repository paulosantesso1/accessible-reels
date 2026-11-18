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
    for (const anchor of videoAnchors) {
        let url;
        try { url = new URL(anchor.href, location.href).href; } catch (_error) { continue; }
        const pathname = new URL(url).pathname;
        const videoMatch = pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
        if (!videoMatch) continue;
        const key = videoMatch[0];
        if (seen.has(key)) continue;
        seen.add(key);
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
            author: decodeURIComponent(videoMatch[1]),
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
    if len(normalized) > 300:
        raise VideoControlError("O termo de pesquisa é muito longo. Use até 300 caracteres.")
    return f"https://www.tiktok.com/search/video?q={quote_plus(normalized)}"


# Limite maximo de resultados na biblioteca pessoal (curtidos/favoritos).
# Importada por ui/app_frame.py e tests/test_library.py; os scripts web
# (tiktok.js, youtube.js) declaram sua propria copia local independente.
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
        results.append(SearchResult(url, author, description))
        if len(results) >= limit:
            break
    return tuple(results)


def validate_search_result_url(value: Any) -> str:
    return select_current_url(value, "https://www.tiktok.com/")
