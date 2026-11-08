"""Suíte de testes unificada para as novas funcionalidades e correções de bugs:
1. TikTok Lives (extração de link canônico, rotas padrão e subdomínio, busca e cópia).
2. Trava de segurança contra download de transmissões ao vivo em andamento.
3. Alternância e silenciamento do chat ao vivo (detecção de carregamento, ocultação visual e ARIA).
4. Roteamento seguro de links externos e blindagem contra auto-execução ou IE.
5. Interceptação de navegação externa no WebView com preservação do player.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import sync_playwright

import link_router
from tiktok.search import normalize_search_results, search_url
from tiktok.video_controls import VideoControlError
from tiktok.window_controller import playwright_driver_pid
from ui.app_frame import MainFrame
from ui.download_controls import DownloadControlsMixin
from ui.video_link import parse_video_link
from ui.webview_client import ACTIONS, WebViewClient


# =============================================================================
# Fixtures para testes no DOM com Playwright
# =============================================================================

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        assert playwright_driver_pid(playwright) is not None
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 800, "height": 600})
    yield page
    page.close()


def install_embedded_tiktok(page):
    page.evaluate("""() => {
      window.__accessibleTransport = {
        storage: {local: {get: async () => ({}), set: async () => {}}},
        runtime: {
          onMessage: {addListener: fn => { window.commandListener = fn; }},
          sendMessage: async ({x, y}) => {
            const el = document.elementFromPoint(x, y);
            if (el) el.click();
            return {ok: true};
          }
        }
      };
      window.command = (action, argument) => new Promise(resolve =>
        window.commandListener({type: 'accessible-reels-command', action, argument}, {}, resolve));
      for (const video of document.querySelectorAll('video')) {
        video.testPaused = video.id !== 'active';
        Object.defineProperty(video, 'paused', {get: () => video.testPaused});
        video.pause = () => { video.testPaused = true; };
        video.play = async () => { video.testPaused = false; };
      }
    }""")
    script_path = Path(__file__).resolve().parents[1] / "ui/web_scripts/tiktok.js"
    page.add_script_tag(content=script_path.read_text(encoding="utf-8"))


def load_tiktok_page(page, path_or_url, body):
    page.route("https://www.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body=body
    ))
    page.route("https://live.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body=body
    ))
    target = path_or_url if path_or_url.startswith("http") else ("https://www.tiktok.com" + path_or_url)
    page.goto(target)


# =============================================================================
# 1. TESTES DE LIVES NO TIKTOK (DOM, Links Canônicos e Busca)
# =============================================================================

def test_canonical_live_link_and_copy_on_standard_live_path(page):
    html = """
    <article>
      <div data-e2e="video-author-uniqueid">streamer_top</div>
      <div data-e2e="video-desc">Live jogando ao vivo</div>
      <video id="active" style="width:400px;height:400px"></video>
    </article>
    """
    load_tiktok_page(page, "/@streamer_top/live", html)
    install_embedded_tiktok(page)

    info = page.evaluate("command('refresh_info')")
    assert info["author"] == "@streamer_top"
    assert info["link"] == "https://www.tiktok.com/@streamer_top/live"

    copy_res = page.evaluate("command('copy_link')")
    assert copy_res["ok"] is True
    assert copy_res["link"] == "https://www.tiktok.com/@streamer_top/live"


def test_canonical_live_link_on_subdomain(page):
    html = """
    <article>
      <div data-e2e="video-author-uniqueid">streamer_sub</div>
      <video id="active" style="width:400px;height:400px"></video>
    </article>
    """
    load_tiktok_page(page, "https://live.tiktok.com/@streamer_sub", html)
    install_embedded_tiktok(page)

    info = page.evaluate("command('refresh_info')")
    assert info["link"] == "https://www.tiktok.com/@streamer_sub/live"


@pytest.mark.parametrize("url, expected_platform, expected_canonical", [
    ("https://www.tiktok.com/@streamer/live", "TikTok", "https://www.tiktok.com/@streamer/live"),
    ("https://live.tiktok.com/@streamer", "TikTok", "https://www.tiktok.com/@streamer/live"),
    ("https://www.tiktok.com/@streamer/live?share=1&lang=pt", "TikTok", "https://www.tiktok.com/@streamer/live"),
])
def test_parse_video_link_recognizes_tiktok_lives(url, expected_platform, expected_canonical):
    platform, canonical = parse_video_link(url)
    assert platform == expected_platform
    assert canonical == expected_canonical


@pytest.mark.parametrize("invalid_live_url", [
    "https://www.tiktok.com/@streamer/livestream",
    "https://www.tiktok.com/@streamer/live/extra",
])
def test_parse_video_link_rejects_pseudo_live_urls(invalid_live_url):
    with pytest.raises(VideoControlError):
        parse_video_link(invalid_live_url)


def test_search_url_with_and_without_lives():
    assert search_url("games", include_lives=True) == "https://www.tiktok.com/search?q=games"
    assert search_url("games", include_lives=False) == "https://www.tiktok.com/search/video?q=games"


def test_normalize_search_results_with_live_stream():
    items = [{
        "url": "https://www.tiktok.com/@gamer/live",
        "author": "@gamer",
        "description": "jogando partida decisiva",
        "is_live": True,
    }]
    results = normalize_search_results(items)
    assert len(results) == 1
    assert results[0].is_live is True
    assert results[0].url == "https://www.tiktok.com/@gamer/live"
    assert results[0].label == "[AO VIVO] @gamer: jogando partida decisiva"


# =============================================================================
# 2. TESTES DE BLOQUEIO DE DOWNLOAD EM TRANSMISSÕES AO VIVO
# =============================================================================

def test_live_stream_video_download_is_blocked():
    frame = Mock(_closing_app=False, _download_busy=True)
    DownloadControlsMixin._download_resolved(
        frame, "TikTok", {"ok": True, "link": "https://www.tiktok.com/@streamer/live"}, audio=False
    )
    assert frame._download_busy is False
    frame.choose_download_file.assert_not_called()
    frame.status.assert_called_once_with("Não é possível baixar uma transmissão ao vivo em andamento.")


def test_live_stream_audio_download_is_blocked():
    frame = Mock(_closing_app=False, _download_busy=True)
    DownloadControlsMixin._download_resolved(
        frame, "TikTok", {"ok": True, "link": "https://www.tiktok.com/@streamer/live"}, audio=True
    )
    assert frame._download_busy is False
    frame.choose_download_file.assert_not_called()
    frame.status.assert_called_once_with("Não é possível baixar uma transmissão ao vivo em andamento.")


# =============================================================================
# 3. TESTES DO CHAT DA LIVE (Alternância, Carregamento, Silenciamento e ARIA)
# =============================================================================

def test_live_chat_toggle_is_in_allowed_actions():
    assert "toggle_live_chat" in ACTIONS


def test_live_chat_toggle_reports_loading_when_unmounted_on_live(page):
    load_tiktok_page(page, "/@streamer/live", '<video id="active" style="width:400px;height:400px"></video>')
    install_embedded_tiktok(page)

    res = page.evaluate("command('toggle_live_chat')")
    assert res["ok"] is False
    assert res["error"] == "O chat da live ainda está carregando ou não está disponível."


def test_live_chat_toggle_fails_outside_live(page):
    load_tiktok_page(page, "/@streamer/video/123", '<video id="active" style="width:400px;height:400px"></video>')
    install_embedded_tiktok(page)

    res = page.evaluate("command('toggle_live_chat')")
    assert res["ok"] is False
    assert res["error"] == "Você não está em uma live."


def test_live_chat_toggle_hides_silences_and_restores_chat(page):
    html = """
    <video id="active" style="width:400px;height:400px"></video>
    <div data-e2e="chat-room" aria-live="polite"><span>Mensagem 1</span></div>
    """
    load_tiktok_page(page, "/@streamer/live", html)
    install_embedded_tiktok(page)

    chat_selector = "document.querySelector('[data-e2e=chat-room]')"

    # 1. Silencia e oculta o chat
    hide_res = page.evaluate("command('toggle_live_chat')")
    assert hide_res == {"ok": True, "hidden": True}
    assert page.evaluate(f"{chat_selector}.style.display") == "none"
    assert page.evaluate(f"{chat_selector}.getAttribute('aria-hidden')") == "true"
    assert page.evaluate(f"{chat_selector}.getAttribute('aria-live')") == "off"

    # 2. Reativa e restaura os atributos originais
    show_res = page.evaluate("command('toggle_live_chat')")
    assert show_res == {"ok": True, "hidden": False}
    assert page.evaluate(f"{chat_selector}.style.display") == ""
    assert page.evaluate(f"{chat_selector}.hasAttribute('aria-hidden')") is False
    assert page.evaluate(f"{chat_selector}.getAttribute('aria-live')") == "polite"


def test_mainframe_on_live_chat_toggled_notifications():
    frame = Mock()
    MainFrame._on_live_chat_toggled(frame, {"ok": True, "hidden": True})
    frame.status.assert_called_with("Chat ao vivo da live desativado e silenciado.")

    MainFrame._on_live_chat_toggled(frame, {"ok": True, "hidden": False})
    frame.status.assert_called_with("Chat ao vivo da live ativado.")

    MainFrame._on_live_chat_toggled(frame, {"ok": False, "error": "O chat da live ainda está carregando ou não está disponível."})
    frame.status.assert_called_with("O chat da live ainda está carregando ou não está disponível.")

    MainFrame._on_live_chat_toggled(frame, {"ignored": True})
    frame.status.assert_called_with("Aguarde o comando anterior terminar e tente novamente.")


# =============================================================================
# 4. TESTES DO ROTEADOR DE NAVEGADORES EXTERNOS (link_router.py)
# =============================================================================

def test_is_forbidden_browser_filters_app_and_ie():
    assert link_router._is_forbidden_browser("") is True
    assert link_router._is_forbidden_browser("   ") is True
    assert link_router._is_forbidden_browser("iexplore.exe") is True
    assert link_router._is_forbidden_browser('"C:\\Program Files\\Internet Explorer\\iexplore.exe"') is True
    assert link_router._is_forbidden_browser(f'"{link_router.APP_NAME}.exe" %1') is True
    assert link_router._is_forbidden_browser('"C:\\Program Files\\Google\\Chrome\\chrome.exe" -- "%1"') is False


def test_browser_commands_excludes_own_command_and_app_name(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(link_router, "get_preferred_browser", lambda: None)
    monkeypatch.setattr(link_router, "current_default_progid", lambda: "MSEdgeHTM")
    monkeypatch.setattr(link_router, "_progid_command", lambda progid: f'"{link_router.APP_NAME}.exe" %1')
    monkeypatch.setattr(link_router, "_registered_browser_commands", lambda: ["iexplore.exe", "valid_browser.exe %1"])

    commands = list(link_router._browser_commands())
    assert commands == ["valid_browser.exe %1"]


def test_browser_commands_deduplicates_by_executable_path(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(link_router, "get_preferred_browser", lambda: None)
    monkeypatch.setattr(link_router, "current_default_progid", lambda: "ChromeHTML")
    monkeypatch.setattr(link_router, "_progid_command", lambda progid: '"C:\\Program Files\\Chrome\\chrome.exe" -- "%1"')
    monkeypatch.setattr(link_router, "_registered_browser_commands", lambda: ['"C:\\Program Files\\Chrome\\chrome.exe"', "edge.exe %1"])

    commands = list(link_router._browser_commands())
    assert len(commands) == 2
    assert commands[0] == '"C:\\Program Files\\Chrome\\chrome.exe" -- "%1"'
    assert commands[1] == "edge.exe %1"


def test_open_in_default_browser_skips_forbidden_and_opens_valid(monkeypatch):
    monkeypatch.setattr(link_router, "_browser_commands", lambda: ['iexplore.exe', '"C:\\Chrome\\chrome.exe" %1'])
    launched = []
    with patch("subprocess.Popen", side_effect=lambda cmd, **kw: launched.append(cmd) or Mock()):
        result = link_router.open_in_default_browser("https://example.com")
        assert result is True
        assert len(launched) == 1
        assert "chrome.exe" in str(launched[0]).lower()


def test_link_server_set_handler_properly_assigns_handler():
    server = link_router.LinkServer()
    mock_handler = Mock()
    server.set_handler(mock_handler)
    assert server._handler is mock_handler


# =============================================================================
# 5. TESTES DE NAVEGAÇÃO EXTERNA NO WEBVIEW (Veto e Envio ao Navegador)
# =============================================================================

def test_external_link_navigation_is_vetoed_and_opened_in_default_browser():
    view = Mock()
    client = WebViewClient(view, "TikTok", Mock(), Mock())
    client.ready = True

    event = Mock()
    event.IsTargetMainFrame.return_value = True
    event.GetURL.return_value = "https://instagram.com/reel/123"

    opened_urls = []
    with patch("link_router.open_in_default_browser", side_effect=lambda u: opened_urls.append(u) or True):
        client._navigating(event)

    event.Veto.assert_called_once()
    assert opened_urls == ["https://instagram.com/reel/123"]
    assert client.ready is True


def test_auth_domain_navigation_is_allowed_in_webview():
    view = Mock()
    client = WebViewClient(view, "TikTok", Mock(), Mock())
    client.ready = True

    for auth_url in [
        "https://accounts.google.com/o/oauth2/auth",
        "https://appleid.apple.com/auth/authorize",
        "https://facebook.com/v12.0/dialog/oauth",
    ]:
        event = Mock()
        event.IsTargetMainFrame.return_value = True
        event.GetURL.return_value = auth_url

        with patch("link_router.open_in_default_browser") as mock_open:
            client._navigating(event)
            event.Veto.assert_not_called()
            mock_open.assert_not_called()


def test_internal_platform_navigation_is_not_vetoed():
    view = Mock()
    client = WebViewClient(view, "TikTok", Mock(), Mock())
    client.ready = True

    event = Mock()
    event.IsTargetMainFrame.return_value = True
    event.GetURL.return_value = "https://www.tiktok.com/@ana/video/456"

    with patch("link_router.open_in_default_browser") as mock_open:
        client._navigating(event)
        event.Veto.assert_not_called()
        mock_open.assert_not_called()
