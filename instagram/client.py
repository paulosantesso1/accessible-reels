from __future__ import annotations

import json
import math
import queue
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import sync_playwright

from instagram.search import validate_reel_url
from tiktok.browser_extension import LocalBrowserWorker
from tiktok.client import BrowserCommand, WorkerEvent
from tiktok.cookie_importer import CookieImportError, load_cookie_file, normalized_cookie_domain
from tiktok.video_controls import VideoControlError


INSTAGRAM_URL = "https://www.instagram.com/reels/"
VOLUME_KEY = "accessibleReelsInstagramVolume"
MUTED_KEY = "accessibleReelsInstagramMuted"


def instagram_cookie(cookie):
    domain = normalized_cookie_domain(cookie)
    return domain == "instagram.com" or domain.endswith(".instagram.com")


class IntegratedInstagramBridge:
    """Runs the shared Reel controls directly in an owned Chromium context."""

    def __init__(self, profile: Path):
        self.profile = profile
        self.preferences = profile.parent / "instagram_preferences.json"
        self.context = self.page = self.playwright = None

    def start(self):
        if self.context is not None:
            return
        try:
            self.profile.mkdir(parents=True, exist_ok=True)
            self.playwright = sync_playwright().start()
            self.context = self.playwright.chromium.launch_persistent_context(
                str(self.profile), headless=False,
                args=["--autoplay-policy=no-user-gesture-required"],
            )
            self.install_controls(self.context)
        except Exception:
            self.stop()
            raise VideoControlError(
                "Não foi possível abrir o Chromium do Instagram. Confira a instalação "
                "do Chromium e se este perfil já está aberto em outra instância."
            ) from None

    def install_controls(self, context):
        root = Path(__file__).resolve().parents[1]
        scripts = [root / "instagram/integrated_transport.js",
                   root / "browser_extension/audio_guard.js",
                   root / "browser_extension/instagram.js"]
        context.expose_binding("__accessibleInstagramHost", self._host)
        script = "\n".join(path.read_text(encoding="utf-8") for path in scripts)
        context.add_init_script("if (window === top && ['instagram.com', 'www.instagram.com'].includes(location.hostname)) {\n" + script + "\n}")

    def _host(self, source, action, values):
        page = source["page"]
        if (source["frame"] != page.main_frame or
                urlsplit(page.url).hostname not in {"instagram.com", "www.instagram.com"}):
            raise ValueError("Origem inválida")
        if action == "load":
            try:
                return self._valid_preferences(json.loads(self.preferences.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                return {}
        if action == "save":
            safe = self._valid_preferences(values)
            self.preferences.parent.mkdir(parents=True, exist_ok=True)
            self.preferences.write_text(json.dumps(safe), encoding="utf-8")
            return {"ok": True}
        raise ValueError("Comando desconhecido")

    def pump(self):
        page = self.page
        if page is None or page.is_closed():
            return
        requests = page.evaluate("() => window.__accessibleInstagramClicks?.splice(0) || []")
        for request in requests:
            x, y = request.get("x"), request.get("y")
            valid = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (x, y))
            if valid:
                page.mouse.click(x, y)
            page.evaluate("([id, ok]) => window.__accessibleInstagramClickDone?.(id, {ok})", [request["id"], valid])
        page.wait_for_timeout(25)

    @staticmethod
    def _valid_preferences(values):
        result = {}
        if not isinstance(values, dict):
            return result
        volume = values.get(VOLUME_KEY)
        if type(volume) in (int, float) and math.isfinite(volume):
            result[VOLUME_KEY] = max(0, min(1, volume))
        if type(values.get(MUTED_KEY)) is bool:
            result[MUTED_KEY] = values[MUTED_KEY]
        return result

    def _page(self):
        self.start()
        if self.page is None or self.page.is_closed():
            self.page = next((p for p in self.context.pages if not p.is_closed()), None) or self.context.new_page()
        return self.page

    def execute(self, action, argument=None, timeout=20):
        if action == "close_instagram":
            self.stop()
            return {"ok": True}
        page = self._page()
        if action == "open_platform":
            if urlsplit(page.url).hostname not in {"instagram.com", "www.instagram.com"}:
                page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
            page.bring_to_front()
            return {"ok": True}
        if action == "search":
            query = " ".join(str(argument or "").split())
            if not query:
                raise VideoControlError("Digite o que deseja pesquisar.")
            page.goto("https://www.instagram.com/explore/search/keyword/?" + urlencode({"q": query}), wait_until="domcontentloaded")
            action = "collect_search_results"
        elif action == "open_search_result":
            page.goto(validate_reel_url(argument), wait_until="domcontentloaded")
            action = "refresh_info"
        if urlsplit(page.url).hostname not in {"instagram.com", "www.instagram.com"}:
            raise VideoControlError("Abra o Instagram e faça login no Chromium integrado.")
        page.wait_for_function("typeof window.__accessibleInstagramCommand === 'function'", timeout=timeout * 1000)
        page.evaluate("([action, argument]) => { window.__accessibleInstagramResult = null; window.__accessibleInstagramCommand(action, argument).then(result => { window.__accessibleInstagramResult = result; }); }", [action, argument])
        deadline = time.monotonic() + timeout
        while True:
            self.pump()
            result = page.evaluate("window.__accessibleInstagramResult")
            if result is not None:
                break
            if time.monotonic() >= deadline:
                # Cancel the old document so a timed-out action cannot run later.
                page.reload(wait_until="domcontentloaded")
                raise VideoControlError("O Instagram não respondeu a tempo. Confira o estado do Reel antes de tentar novamente.")
        if result.get("ok") is not True:
            raise VideoControlError(result.get("error") or "Não foi possível executar o comando no Instagram.")
        return result

    def import_cookies(self, path):
        parsed = load_cookie_file(path, domain="instagram.com")
        cookies = [cookie for cookie in parsed.cookies if instagram_cookie(cookie)]
        self.start()
        # Replace matching cookies without erasing unrelated session settings.
        self.context.add_cookies(cookies)
        found = self.context.cookies()
        count = sum(any(all(actual.get(k) == cookie.get(k) for k in ("name", "value", "domain", "path"))
                        for actual in found) for cookie in cookies)
        if not count:
            raise VideoControlError("O Chromium não manteve os cookies importados do Instagram.")
        page = self._page()
        page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
        page.bring_to_front()
        return count

    def stop(self):
        context, playwright = self.context, self.playwright
        self.context = self.page = self.playwright = None
        try:
            if context is not None:
                context.close()
        finally:
            if playwright is not None:
                playwright.stop()


class InstagramBrowserWorker(LocalBrowserWorker):
    """Same commands and announcements as extension mode, with an owned browser."""

    def __init__(self, profile: Path, callback):
        super().__init__(callback, platform="instagram", open_minimized=False)
        self._bridge = IntegratedInstagramBridge(profile)

    def import_cookies(self, path):
        self._enqueue("import", path)

    def run(self):
        try:
            while True:
                try:
                    command = self._commands.get(timeout=0.1)
                except queue.Empty:
                    # Dispatch browser bindings even when the interface is idle.
                    page = self._bridge.page
                    if page is not None and not page.is_closed():
                        try:
                            self._bridge.pump()
                        except Exception:
                            pass
                    continue
                if command.action == "shutdown":
                    break
                try:
                    self._execute(command)
                except VideoControlError as exc:
                    self._notify(WorkerEvent("error", str(exc)))
                except Exception:
                    self._notify(WorkerEvent("error", "Falha no Chromium do Instagram. Confira o navegador e tente novamente."))
        finally:
            try:
                self._bridge.stop()
            finally:
                self._notify(WorkerEvent("stopped", "Chromium do Instagram fechado."))

    def _execute(self, command: BrowserCommand):
        if command.action == "open":
            self._bridge.execute("open_platform")
            self._notify(WorkerEvent("status", "Chromium do Instagram aberto. Faça login se necessário.", browser_visible=True))
        elif command.action == "import":
            try:
                count = self._bridge.import_cookies(command.argument)
            except CookieImportError as exc:
                raise VideoControlError(str(exc)) from None
            self._notify(WorkerEvent("status", f"{count} cookies do Instagram importados. Confira se a sessão foi aceita no navegador."))
        else:
            super()._execute(command)

    def _notify(self, event):
        if event.kind == "stopped":
            event = WorkerEvent("stopped", "Chromium do Instagram fechado.")
        elif event.kind == "error" and event.message == "Falha interna na comunicação com a extensão.":
            event = WorkerEvent("error", "Falha no Chromium do Instagram. Confira o navegador e tente novamente.")
        super()._notify(event)
