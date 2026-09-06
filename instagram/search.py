from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from tiktok.search import SearchResult
from tiktok.video_controls import VideoControlError


def validate_reel_url(value: Any) -> str:
    try:
        url = urlsplit(str(value or ""))
        match = re.fullmatch(r"/(reel|reels|p)/([A-Za-z0-9_-]+)/?", url.path)
        if (
            url.scheme != "https"
            or url.hostname not in {"instagram.com", "www.instagram.com"}
            or url.username is not None or url.password is not None
            or url.port not in {None, 443}
            or match is None or match[2] == "audio"
        ):
            raise ValueError
    except ValueError as exc:
        raise VideoControlError("O link não é um Reel ou post válido do Instagram.") from exc
    kind = "p" if match[1] == "p" else "reel"
    return f"https://www.instagram.com/{kind}/{match[2]}/"


def normalize_reel_results(values: Any) -> tuple[SearchResult, ...]:
    if not isinstance(values, list):
        return ()
    results = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            url = validate_reel_url(value.get("url"))
        except VideoControlError:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append(SearchResult(
            url,
            " ".join(str(value.get("author") or "Autor desconhecido").split()),
            " ".join(str(value.get("description") or "").split()),
        ))
        if len(results) == 50:
            break
    return tuple(results)
