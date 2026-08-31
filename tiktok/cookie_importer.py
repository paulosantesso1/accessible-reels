from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class CookieImportError(ValueError):
    """Erro seguro e compreensível ao validar um arquivo de cookies."""


@dataclass(frozen=True)
class CookieDiagnostics:
    source_format: str
    encoding: str
    total_lines: int
    valid_cookies: int
    ignored_lines: int
    ignored_reasons: tuple[tuple[str, int], ...]
    http_only_cookies: int
    session_cookies: int
    domains: tuple[str, ...]

    def file_summary(self) -> str:
        reasons = ", ".join(
            f"{reason}: {count}" for reason, count in self.ignored_reasons
        ) or "nenhuma"
        domains = ", ".join(self.domains) or "nenhum"
        return (
            f"Formato {self.source_format}; linhas {self.total_lines}; "
            f"cookies válidos {self.valid_cookies}; ignoradas {self.ignored_lines} "
            f"({reasons}); HttpOnly {self.http_only_cookies}; "
            f"sessão {self.session_cookies}; domínios {domains}."
        )

    def safe_summary(
        self,
        *,
        added_to_context: int,
        found_after_add: int,
        retained_after_navigation: int,
    ) -> str:
        return (
            f"{self.file_summary()} "
            f"adicionados {added_to_context}; verificados {found_after_add}; "
            f"mantidos após navegação {retained_after_navigation}."
        )


@dataclass(frozen=True)
class CookieImportResult:
    cookies: list[dict[str, Any]] = field(repr=False)
    diagnostics: CookieDiagnostics


_SAME_SITE = {
    "strict": "Strict",
    "lax": "Lax",
    "none": "None",
    "no_restriction": "None",
}

_NETSCAPE_HEADER_MARKERS = (
    "# netscape http cookie file",
    "# http cookie file",
)


def load_cookie_file(path: str | Path) -> CookieImportResult:
    """Carrega JSON ou Netscape diretamente, sem registrar conteúdo sensível."""
    text, encoding = _read_cookie_text(Path(path))
    stripped = text.lstrip()
    is_json = Path(path).suffix.lower() == ".json" or stripped.startswith(("[", "{"))

    if is_json:
        result = _parse_json(text, encoding)
    else:
        result = parse_netscape(text, encoding=encoding)

    if not result.cookies:
        reasons = _format_ignored_reasons(result.diagnostics.ignored_reasons)
        raise CookieImportError(
            "Nenhum cookie válido foi encontrado no arquivo. "
            f"Linhas ignoradas: {result.diagnostics.ignored_lines} ({reasons})."
        )
    if not any(is_tiktok_cookie(cookie) for cookie in result.cookies):
        raise CookieImportError(
            "Nenhum cookie aplicável a tiktok.com foi encontrado no arquivo."
        )
    return result


def load_cookies(path: str | Path) -> list[dict[str, Any]]:
    """Compatibilidade: retorna somente os cookies já validados."""
    return load_cookie_file(path).cookies


def parse_netscape(text: str, *, encoding: str = "utf-8") -> CookieImportResult:
    """Converte o formato Netscape cookies.txt para cookies do Playwright."""
    cookies: list[dict[str, Any]] = []
    ignored: Counter[str] = Counter()
    lines = text.splitlines()

    for raw_line in lines:
        if not raw_line.strip():
            ignored["linha em branco"] += 1
            continue

        http_only = raw_line.startswith("#HttpOnly_")
        if raw_line.startswith("#") and not http_only:
            normalized_comment = raw_line.strip().lower()
            reason = (
                "cabeçalho"
                if normalized_comment.startswith(_NETSCAPE_HEADER_MARKERS)
                else "comentário"
            )
            ignored[reason] += 1
            continue

        line = raw_line[len("#HttpOnly_") :] if http_only else raw_line
        fields = line.split("\t", 6)
        if len(fields) != 7:
            ignored["campos inválidos"] += 1
            continue

        domain, include_subdomains, path, secure, expiration, name, value = fields
        domain = domain.strip()
        path = path.strip() or "/"
        include_subdomains_value = _parse_netscape_bool(include_subdomains)
        secure_value = _parse_netscape_bool(secure)

        if not domain or not name:
            ignored["domínio ou nome ausente"] += 1
            continue
        if include_subdomains_value is None:
            ignored["includeSubdomains inválido"] += 1
            continue
        if secure_value is None:
            ignored["secure inválido"] += 1
            continue
        try:
            expiration_value = float(expiration.strip())
        except ValueError:
            ignored["expiração inválida"] += 1
            continue
        if expiration_value < 0 or not math.isfinite(expiration_value):
            ignored["expiração inválida"] += 1
            continue

        if include_subdomains_value and not domain.startswith("."):
            domain = f".{domain}"

        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": secure_value,
        }
        if http_only:
            cookie["httpOnly"] = True
        if expiration_value != 0:
            cookie["expires"] = expiration_value
        cookies.append(cookie)

    return CookieImportResult(
        cookies=cookies,
        diagnostics=_build_diagnostics(
            cookies=cookies,
            source_format="Netscape",
            encoding=encoding,
            total_lines=len(lines),
            ignored=ignored,
        ),
    )


def convert_cookies(raw: Any) -> list[dict[str, Any]]:
    """Valida uma lista JSON exportada e produz cookies Playwright."""
    if not isinstance(raw, list):
        raise CookieImportError("A raiz do JSON deve ser uma lista de cookies.")

    converted: list[dict[str, Any]] = []
    for index, source in enumerate(raw, start=1):
        if not isinstance(source, dict):
            raise CookieImportError(f"O cookie {index} deve ser um objeto JSON.")

        name = source.get("name")
        value = source.get("value")
        if not isinstance(name, str) or not name:
            raise CookieImportError(f"O cookie {index} não possui um nome válido.")
        if not isinstance(value, str):
            raise CookieImportError(f"O cookie {index} não possui um valor válido.")

        domain = source.get("domain")
        url = source.get("url")
        if not isinstance(domain, str) or not domain:
            domain = None
        if not isinstance(url, str) or not url:
            url = None
        if domain is None and url is None:
            raise CookieImportError(f"O cookie {index} precisa de domínio ou URL.")

        cookie: dict[str, Any] = {"name": name, "value": value}
        if domain is not None:
            cookie["domain"] = domain
            path = source.get("path", "/")
            cookie["path"] = path if isinstance(path, str) and path else "/"
        else:
            cookie["url"] = url

        expires = source.get("expires", source.get("expirationDate"))
        if expires is not None:
            if isinstance(expires, bool) or not isinstance(expires, (int, float)):
                raise CookieImportError(f"O cookie {index} possui expiração inválida.")
            if float(expires) != 0:
                cookie["expires"] = float(expires)

        for field_name in ("httpOnly", "secure"):
            if field_name in source:
                if not isinstance(source[field_name], bool):
                    raise CookieImportError(
                        f"O cookie {index} possui {field_name} inválido."
                    )
                cookie[field_name] = source[field_name]

        if "sameSite" in source:
            same_site = source["sameSite"]
            if not isinstance(same_site, str):
                raise CookieImportError(f"O cookie {index} possui SameSite inválido.")
            normalized = same_site.strip().lower()
            if normalized != "unspecified":
                if normalized not in _SAME_SITE:
                    raise CookieImportError(
                        f"O cookie {index} possui SameSite desconhecido."
                    )
                cookie["sameSite"] = _SAME_SITE[normalized]

        converted.append(cookie)

    return converted


def is_tiktok_cookie(cookie: dict[str, Any]) -> bool:
    domain = normalized_cookie_domain(cookie)
    return domain == "tiktok.com" or domain.endswith(".tiktok.com")


def normalized_cookie_domain(cookie: dict[str, Any]) -> str:
    domain = cookie.get("domain")
    if isinstance(domain, str):
        return domain.strip().lower().lstrip(".")
    url = cookie.get("url")
    if isinstance(url, str):
        return (urlparse(url).hostname or "").lower().lstrip(".")
    return ""


def _read_cookie_text(path: Path) -> tuple[str, str]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CookieImportError("Não foi possível ler o arquivo de cookies.") from exc
    try:
        return content.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        try:
            return content.decode("cp1252"), "Windows-1252"
        except UnicodeDecodeError as exc:
            raise CookieImportError(
                "O arquivo de cookies usa uma codificação não reconhecida."
            ) from exc


def _parse_json(text: str, encoding: str) -> CookieImportResult:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieImportError(
            "O arquivo selecionado não contém JSON ou Netscape válido."
        ) from exc
    cookies = convert_cookies(raw)
    return CookieImportResult(
        cookies=cookies,
        diagnostics=_build_diagnostics(
            cookies=cookies,
            source_format="JSON",
            encoding=encoding,
            total_lines=len(text.splitlines()),
            ignored=Counter(),
        ),
    )


def _parse_netscape_bool(value: str) -> bool | None:
    normalized = value.strip().upper()
    if normalized == "TRUE":
        return True
    if normalized == "FALSE":
        return False
    return None


def _build_diagnostics(
    *,
    cookies: list[dict[str, Any]],
    source_format: str,
    encoding: str,
    total_lines: int,
    ignored: Counter[str],
) -> CookieDiagnostics:
    domains = sorted(
        {domain for cookie in cookies if (domain := normalized_cookie_domain(cookie))}
    )
    return CookieDiagnostics(
        source_format=source_format,
        encoding=encoding,
        total_lines=total_lines,
        valid_cookies=len(cookies),
        ignored_lines=sum(ignored.values()),
        ignored_reasons=tuple(sorted(ignored.items())),
        http_only_cookies=sum(bool(cookie.get("httpOnly")) for cookie in cookies),
        session_cookies=sum("expires" not in cookie for cookie in cookies),
        domains=tuple(domains),
    )


def _format_ignored_reasons(reasons: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{reason}: {count}" for reason, count in reasons) or "nenhuma"
