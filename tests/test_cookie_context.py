from __future__ import annotations

import traceback
from pathlib import Path
from unittest.mock import patch

import pytest

from tiktok.client import BrowserWorker
from tiktok.cookie_importer import CookieImportError, parse_netscape


COOKIE_VALUE = "SECRET_CONTEXT_VALUE"


def make_result():
    line = "\t".join(
        [
            ".tiktok.com",
            "TRUE",
            "/",
            "TRUE",
            "1893456000",
            "session-example",
            COOKIE_VALUE,
        ]
    )
    return parse_netscape(line)


def make_mixed_result():
    tiktok = "\t".join(
        [
            ".tiktok.com",
            "TRUE",
            "/",
            "TRUE",
            "1893456000",
            "session-example",
            COOKIE_VALUE,
        ]
    )
    other = "\t".join(
        [
            ".example.com",
            "TRUE",
            "/",
            "FALSE",
            "0",
            "other-example",
            "other-fictitious-value",
        ]
    )
    return parse_netscape(tiktok + "\n" + other)


class FakePage:
    def __init__(self, context, order: list[str]) -> None:
        self.context = context
        self.order = order
        self.url = "about:blank"

    def is_closed(self) -> bool:
        return False

    def goto(self, url: str, wait_until: str) -> None:
        self.order.append("goto")
        self.url = url
        self.context.navigated = True

    def wait_for_timeout(self, milliseconds: int) -> None:
        assert milliseconds == 2_000
        self.order.append("wait")

    def bring_to_front(self) -> None:
        self.order.append("front")


class FakeContext:
    def __init__(
        self,
        order: list[str],
        *,
        add_error: Exception | None = None,
        never_store: bool = False,
        drop_after_navigation: bool = False,
        filtered_clear_supported: bool = True,
    ) -> None:
        self.order = order
        self.add_error = add_error
        self.never_store = never_store
        self.drop_after_navigation = drop_after_navigation
        self.filtered_clear_supported = filtered_clear_supported
        self.navigated = False
        self.stored: list[dict] = [
            {
                "name": "old-cookie",
                "value": "old-secret",
                "domain": ".tiktok.com",
                "path": "/",
            }
        ]
        self.clear_filters = []
        self.page = FakePage(self, order)
        self.pages = [self.page]
        self.closed = False

    def clear_cookies(self, **filters) -> None:
        self.order.append("clear-filtered" if filters else "clear-all")
        if filters and not self.filtered_clear_supported:
            raise TypeError("filter unsupported")
        self.clear_filters.append(filters)
        self.stored = []

    def add_cookies(self, cookies) -> None:
        self.order.append("add")
        if self.add_error:
            raise self.add_error
        if not self.never_store:
            self.stored = [dict(cookie) for cookie in cookies]

    def cookies(self, urls=None):
        self.order.append("cookies-after-nav" if self.navigated else "cookies-after-add")
        if self.drop_after_navigation and self.navigated:
            return []
        return [dict(cookie) for cookie in self.stored]

    def close(self) -> None:
        self.closed = True


def make_worker(context: FakeContext, events: list) -> BrowserWorker:
    worker = BrowserWorker(Path("profile-ficticio"), events.append)
    worker._context = context
    worker._page = context.page
    return worker


def test_old_tiktok_cookies_are_cleared_before_add_and_verify():
    order: list[str] = []
    events: list = []
    context = FakeContext(order)
    worker = make_worker(context, events)
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        worker._import_cookies(Path("cookies.txt"))

    assert order == [
        "clear-filtered",
        "add",
        "cookies-after-add",
        "goto",
        "wait",
        "front",
        "cookies-after-nav",
    ]
    domain_filter = context.clear_filters[0]["domain"]
    assert domain_filter.search(".tiktok.com")
    assert domain_filter.search("www.tiktok.com")


def test_same_context_and_page_are_reused_through_import():
    order: list[str] = []
    context = FakeContext(order)
    original_page = context.page
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        worker._import_cookies(Path("cookies.txt"))
    assert worker._context is context
    assert worker._page is original_page
    assert original_page.context is context


def test_complete_valid_set_is_sent_to_context():
    context = FakeContext([])
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_mixed_result()):
        worker._import_cookies(Path("cookies.txt"))
    assert len(context.stored) == 2


def test_old_playwright_fallback_clears_only_context_cookies():
    order: list[str] = []
    context = FakeContext(order, filtered_clear_supported=False)
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        worker._import_cookies(Path("cookies.txt"))
    assert order[:3] == ["clear-filtered", "clear-all", "add"]


def test_add_failure_is_clear_and_does_not_reveal_values():
    context = FakeContext([], add_error=RuntimeError(COOKIE_VALUE))
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        with pytest.raises(CookieImportError, match="adicionar") as error:
            worker._import_cookies(Path("cookies.txt"))
    assert COOKIE_VALUE not in str(error.value)
    assert COOKIE_VALUE not in "".join(traceback.format_exception(error.value))
    assert "goto" not in context.order


def test_import_fails_if_no_cookie_appears_in_context():
    context = FakeContext([], never_store=True)
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        with pytest.raises(CookieImportError, match="Nenhum cookie importado"):
            worker._import_cookies(Path("cookies.txt"))
    assert "goto" not in context.order


def test_import_fails_if_tiktok_cookies_do_not_remain_after_navigation():
    context = FakeContext([], drop_after_navigation=True)
    worker = make_worker(context, [])
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        with pytest.raises(CookieImportError, match="não permaneceram"):
            worker._import_cookies(Path("cookies.txt"))


def test_success_status_contains_counts_but_not_values_or_names():
    events: list = []
    context = FakeContext([])
    worker = make_worker(context, events)
    with patch("tiktok.client.load_cookie_file", return_value=make_result()):
        worker._import_cookies(Path("cookies.txt"))
    message = events[-1].message
    assert "adicionados 1" in message
    assert "verificados 1" in message
    assert "mantidos após navegação 1" in message
    assert "tiktok.com" in message
    assert COOKIE_VALUE not in message
    assert "session-example" not in message
    assert (
        "Ocultamento temporariamente desativado para preservar a reprodução."
        in message
    )


def test_close_still_closes_persistent_context():
    context = FakeContext([])
    worker = make_worker(context, [])
    worker._close_resources()
    assert context.closed is True
    assert worker._context is None
    assert worker._page is None


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_shutdown_joins_worker_after_context_and_playwright_are_closed():
    context = FakeContext([])
    events = []
    worker = make_worker(context, events)
    playwright = FakePlaywright()
    worker._playwright = playwright
    worker.start()
    worker.shutdown()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert context.closed is True
    assert playwright.stopped is True
    assert events[-1].kind == "stopped"
