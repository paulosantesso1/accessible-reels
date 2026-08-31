from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tiktok.cookie_importer import (
    CookieImportError,
    convert_cookies,
    load_cookie_file,
    load_cookies,
    parse_netscape,
)


def netscape_line(
    *,
    domain: str = ".tiktok.com",
    include_subdomains: str = "TRUE",
    path: str = "/",
    secure: str = "TRUE",
    expiration: str = "1893456000",
    name: str = "session-example",
    value: str = "fictitious-value",
) -> str:
    return "\t".join(
        [domain, include_subdomains, path, secure, expiration, name, value]
    )


def load_bytes(content: bytes, filename: str = "cookies.txt"):
    with patch("pathlib.Path.read_bytes", return_value=content):
        return load_cookie_file(filename)


def test_common_netscape_line_uses_tab_fields():
    result = parse_netscape(netscape_line())
    assert result.cookies == [
        {
            "name": "session-example",
            "value": "fictitious-value",
            "domain": ".tiktok.com",
            "path": "/",
            "secure": True,
            "expires": 1893456000.0,
        }
    ]


def test_http_only_prefix_is_not_treated_as_comment():
    result = parse_netscape("#HttpOnly_" + netscape_line())
    assert result.cookies[0]["domain"] == ".tiktok.com"
    assert result.cookies[0]["httpOnly"] is True
    assert result.diagnostics.http_only_cookies == 1


def test_real_comments_header_blank_and_malformed_lines_are_ignored():
    content = "\n".join(
        [
            "# Netscape HTTP Cookie File",
            "# comentário real",
            "",
            "linha sem tabulações",
            netscape_line(),
        ]
    )
    result = parse_netscape(content)
    assert result.diagnostics.total_lines == 5
    assert result.diagnostics.valid_cookies == 1
    assert result.diagnostics.ignored_lines == 4
    assert dict(result.diagnostics.ignored_reasons) == {
        "cabeçalho": 1,
        "campos inválidos": 1,
        "comentário": 1,
        "linha em branco": 1,
    }


def test_empty_value_is_valid_and_special_characters_are_preserved():
    empty = parse_netscape(netscape_line(name="nome-especial", value=""))
    special = parse_netscape(
        netscape_line(name="nome_ç-%", value="valor=ç;%20/+ espaço")
    )
    assert empty.cookies[0]["value"] == ""
    assert special.cookies[0]["name"] == "nome_ç-%"
    assert special.cookies[0]["value"] == "valor=ç;%20/+ espaço"


def test_zero_expiration_creates_session_cookie():
    result = parse_netscape(netscape_line(expiration="0"))
    assert "expires" not in result.cookies[0]
    assert result.diagnostics.session_cookies == 1


def test_numeric_expiration_is_unix_seconds():
    assert parse_netscape(netscape_line(expiration="1700000000")).cookies[0][
        "expires"
    ] == 1700000000.0


@pytest.mark.parametrize(
    ("domain", "include_subdomains", "expected"),
    [
        (".tiktok.com", "TRUE", ".tiktok.com"),
        ("www.tiktok.com", "FALSE", "www.tiktok.com"),
        ("tiktok.com", "TRUE", ".tiktok.com"),
    ],
)
def test_domain_and_include_subdomains_conversion(
    domain, include_subdomains, expected
):
    result = parse_netscape(
        netscape_line(domain=domain, include_subdomains=include_subdomains)
    )
    assert result.cookies[0]["domain"] == expected


@pytest.mark.parametrize(("secure", "expected"), [("TRUE", True), ("FALSE", False)])
def test_secure_true_and_false(secure, expected):
    assert parse_netscape(netscape_line(secure=secure)).cookies[0]["secure"] is expected


def test_empty_path_uses_root():
    assert parse_netscape(netscape_line(path="")).cookies[0]["path"] == "/"


def test_utf8_bom_is_accepted():
    content = ("\ufeff# Netscape HTTP Cookie File\n" + netscape_line()).encode(
        "utf-8"
    )
    result = load_bytes(content)
    assert result.diagnostics.encoding == "UTF-8"
    assert result.cookies[0]["domain"] == ".tiktok.com"


def test_windows_1252_fallback_is_safe():
    content = netscape_line(value="valor-fictício").encode("cp1252")
    result = load_bytes(content)
    assert result.diagnostics.encoding == "Windows-1252"
    assert result.cookies[0]["value"] == "valor-fictício"


def test_json_and_json_content_in_txt_remain_supported():
    content = json.dumps(
        [{"name": "example", "value": "fake", "domain": ".tiktok.com"}]
    ).encode()
    assert load_bytes(content, "example.json").diagnostics.source_format == "JSON"
    assert load_bytes(content, "example.txt").diagnostics.source_format == "JSON"


def test_invalid_json_has_safe_message():
    with patch("pathlib.Path.read_bytes", return_value=b"not json"):
        with pytest.raises(CookieImportError, match="Nenhum cookie válido"):
            load_cookie_file("invalid.txt")
    with patch("pathlib.Path.read_bytes", return_value=b"not json"):
        with pytest.raises(CookieImportError, match="JSON ou Netscape válido"):
            load_cookie_file("invalid.json")


def test_no_valid_cookie_fails_with_ignored_count():
    with patch("pathlib.Path.read_bytes", return_value=b"# header\nmalformed"):
        with pytest.raises(CookieImportError, match="Nenhum cookie válido") as error:
            load_cookie_file("cookies.txt")
    assert "Linhas ignoradas: 2" in str(error.value)


def test_file_without_tiktok_cookie_is_rejected():
    secret = "SECRET_VALUE_MUST_NOT_APPEAR"
    content = netscape_line(domain=".example.com", value=secret).encode()
    with patch("pathlib.Path.read_bytes", return_value=content):
        with pytest.raises(CookieImportError, match="tiktok.com") as error:
            load_cookie_file("cookies.txt")
    assert secret not in str(error.value)


def test_values_do_not_appear_in_diagnostics_result_repr_or_output(capsys):
    secret = "SECRET_VALUE_MUST_NOT_APPEAR"
    result = parse_netscape(netscape_line(value=secret))
    summary = result.diagnostics.safe_summary(
        added_to_context=1, found_after_add=1, retained_after_navigation=1
    )
    assert secret not in summary
    assert secret not in repr(result)
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_load_cookies_compatibility_returns_list():
    with patch("pathlib.Path.read_bytes", return_value=netscape_line().encode()):
        assert isinstance(load_cookies("cookies.txt"), list)


def test_json_root_must_be_list():
    with pytest.raises(CookieImportError, match="lista"):
        convert_cookies({"cookies": []})


@pytest.mark.parametrize(
    ("cookie", "message"),
    [
        ({"value": "fake", "domain": ".tiktok.com"}, "nome"),
        ({"name": "example", "domain": ".tiktok.com"}, "valor"),
        ({"name": "example", "value": "fake"}, "domínio ou URL"),
    ],
)
def test_json_required_fields(cookie, message):
    with pytest.raises(CookieImportError, match=message):
        convert_cookies([cookie])


def test_json_expiration_and_same_site_conversion():
    result = convert_cookies(
        [
            {
                "name": "example",
                "value": "fake",
                "domain": ".tiktok.com",
                "expirationDate": 123.5,
                "sameSite": "no_restriction",
            }
        ]
    )
    assert result[0]["expires"] == 123.5
    assert result[0]["sameSite"] == "None"
    assert "expirationDate" not in result[0]


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ("Strict", "Strict"),
        ("lax", "Lax"),
        ("None", "None"),
        ("no_restriction", "None"),
    ],
)
def test_json_common_same_site_values(input_value, expected):
    result = convert_cookies(
        [
            {
                "name": "example",
                "value": "fake",
                "url": "https://www.tiktok.com",
                "sameSite": input_value,
            }
        ]
    )
    assert result[0]["sameSite"] == expected


def test_json_unspecified_same_site_is_omitted():
    result = convert_cookies(
        [
            {
                "name": "example",
                "value": "fake",
                "domain": ".tiktok.com",
                "sameSite": "unspecified",
            }
        ]
    )
    assert "sameSite" not in result[0]


def test_json_zero_expiration_and_extension_fields_are_removed():
    result = convert_cookies(
        [
            {
                "name": "example",
                "value": "fake",
                "domain": ".tiktok.com",
                "expires": 0,
                "hostOnly": False,
                "session": True,
                "storeId": "0",
                "id": 1,
            }
        ]
    )
    assert set(result[0]) == {"name", "value", "domain", "path"}
