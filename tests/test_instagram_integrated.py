import json
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from instagram.client import IntegratedInstagramBridge, InstagramBrowserWorker, VOLUME_KEY, MUTED_KEY
from tiktok.client import BrowserCommand
from tiktok.cookie_importer import CookieImportError, load_cookie_file


@pytest.mark.parametrize("suffix", ["json", "txt"])
def test_instagram_cookie_formats_and_platform_validation(tmp_path, suffix):
    path = tmp_path / f"session.{suffix}"
    cookie = {"name": "sessionid", "value": "fake-session", "domain": ".instagram.com", "path": "/"}
    path.write_text(json.dumps([cookie]) if suffix == "json" else ".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tfake-session\n", encoding="utf-8")
    assert load_cookie_file(path, domain="instagram.com").cookies[0]["name"] == "sessionid"
    with pytest.raises(CookieImportError, match="tiktok.com"):
        load_cookie_file(path)


def test_import_only_instagram_and_validate_before_browser_start(tmp_path):
    bridge = IntegratedInstagramBridge(tmp_path / "profile")
    bridge.start = Mock()
    bridge.context = Mock()
    bridge.page = Mock()
    bridge.page.is_closed.return_value = False
    path = tmp_path / "input.json"
    cookie = {"name": "sessionid", "value": "fake", "domain": ".instagram.com", "path": "/"}
    path.write_text(json.dumps([cookie, {**cookie, "domain": ".tiktok.com"}]))
    bridge.context.cookies.return_value = [cookie]
    assert bridge.import_cookies(path) == 1
    assert all(c["domain"] == ".instagram.com" for c in bridge.context.add_cookies.call_args.args[0])
    bridge.start.reset_mock()
    path.write_text(json.dumps([{**cookie, "domain": ".instagram.com.evil.example"}]))
    with pytest.raises(CookieImportError):
        bridge.import_cookies(path)
    bridge.start.assert_not_called()


def test_shared_controls_in_owned_chromium(tmp_path):
    bridge = IntegratedInstagramBridge(tmp_path / "profile")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        bridge.context = context
        bridge.install_controls(context)
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
          <style>video {display:block;width:300px;height:200px} button {width:100px;height:40px}</style>
          <main><article><video muted></video><a href="/ana/reels/">ana</a>
          <button>Legenda</button><a href="/reel/ABC/">Link</a>
          <button id="like" aria-label="Curtir" onclick="this.setAttribute('aria-label','Descurtir');window.trusted=event.isTrusted">Curtir</button>
          </article></main>
        '''))
        bridge.page = context.new_page()
        bridge.page.goto("https://www.instagram.com/reel/ABC/")
        assert bridge.execute("author")["author"] == "@ana"
        assert bridge.execute("volume_up")["volume"] == pytest.approx(.05)
        assert bridge.execute("volume_up")["volume"] == pytest.approx(.10)
        assert bridge.execute("toggle_like")["state"] is True
        assert bridge.page.evaluate("window.trusted") is True
        bridge.page.reload()
        assert bridge.execute("volume_up")["volume"] == pytest.approx(.15)
        saved = json.loads(bridge.preferences.read_text())
        assert saved == {VOLUME_KEY: .15, MUTED_KEY: False}
        bridge.stop()
        browser.close()


def test_integrated_shutdown_always_closes_browser(tmp_path):
    events = []
    worker = InstagramBrowserWorker(tmp_path / "profile", events.append)
    worker._bridge = Mock()
    worker.disconnect()
    worker.run()
    worker._bridge.stop.assert_called_once()
    assert events[-1].kind == "stopped"
    assert "Chromium" in events[-1].message
