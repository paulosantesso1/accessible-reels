from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from tiktok.search import SearchResult
from tiktok.video_controls import VideoControlError


def validate_youtube_url(value: Any) -> str:
    """
    Valida e normaliza links exclusivamente de YouTube Shorts.
    """
    try:
        url = urlsplit(str(value or ""))
        
        # Validações básicas de segurança e protocolo
        if (
            url.scheme != "https"
            or url.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
            or url.username is not None or url.password is not None
            or url.port not in {None, 443}
        ):
            raise ValueError
        
        if url.hostname == "youtu.be":
            video_id = url.path.strip("/")
        else:
            # O link PRECISA ser obrigatoriamente um "Short" ou "watch" com v=...
            if url.path.startswith("/shorts/"):
                parts = url.path.strip("/").split("/")
                if len(parts) < 2:
                    raise ValueError
                video_id = parts[1]
            elif url.path.startswith("/watch"):
                from urllib.parse import parse_qs
                qs = parse_qs(url.query)
                if "v" not in qs or not qs["v"]:
                    raise ValueError
                video_id = qs["v"][0]
            else:
                raise ValueError
            
        # O ID de vídeo do YouTube/Short possui exatamente 11 caracteres
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError
            
    except ValueError as exc:
        raise VideoControlError("O link não é um YouTube Short válido.") from exc

    # Retorna o link padronizado para o Short
    return f"https://www.youtube.com/shorts/{video_id}"


def normalize_youtube_results(values: Any) -> tuple[SearchResult, ...]:
    """Keep only canonical Shorts returned by the YouTube search page."""
    if not isinstance(values, list):
        return ()
    results: list[SearchResult] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            raw_url = urlsplit(str(value.get("url") or ""))
            if not raw_url.path.startswith("/shorts/"):
                continue
            url = validate_youtube_url(value.get("url"))
        except VideoControlError:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append(SearchResult(
            url,
            " ".join(str(value.get("author") or "YouTube").split()),
            " ".join(str(value.get("description") or "Short sem título").split()),
        ))
        if len(results) >= 50:
            break
    return tuple(results)
