from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from tiktok.cookie_importer import (
    CookieImportError,
    is_tiktok_cookie,
    load_cookie_file,
    normalized_cookie_domain,
)
from tiktok.preferences import VolumePreferences
from tiktok.search import (
    SEARCH_RESULTS_SCRIPT,
    SearchResult,
    normalize_search_results,
    search_url,
    validate_search_result_url,
)
from tiktok.video_controls import (
    TikTokVideoController,
    VideoControlError,
    VideoInfo,
    clamp_volume,
    volume_preference_init_script,
    volume_message,
)


TIKTOK_URL = "https://www.tiktok.com/"


@dataclass(frozen=True)
class BrowserCommand:
    action: str
    argument: Any = None


@dataclass(frozen=True)
class WorkerEvent:
    kind: str
    message: str
    author: str | None = None
    description: str | None = None
    link: str | None = None
    browser_visible: bool | None = None
    comments: tuple[str, ...] | None = None
    search_results: tuple[SearchResult, ...] | None = None


WorkerCallback = Callable[[WorkerEvent], None]
VideoControllerFactory = Callable[..., TikTokVideoController]

COMMAND_NAMES = {
    "open": "abrir TikTok",
    "import": "importar cookies",
    "next": "próximo vídeo",
    "previous": "vídeo anterior",
    "toggle": "pausar ou reproduzir",
    "author": "ler autor",
    "description": "ler descrição",
    "copy_link": "copiar link",
    "refresh_info": "atualizar informações",
    "search": "pesquisar vídeos",
    "open_search_result": "abrir resultado da pesquisa",
    "volume_up": "aumentar volume",
    "volume_down": "diminuir volume",
    "toggle_mute": "alternar mudo",
    "comments": "abrir comentários",
    "post_comment": "publicar comentário",
    "close_comments": "fechar comentários",
    "toggle_like": "curtir ou descurtir",
    "toggle_favorite": "favoritar ou desfavoritar",
    "diagnostics": "diagnóstico",
    "browser_visibility": "mostrar navegador",
    "shutdown": "encerrar",
}

COMMAND_STAGES = {
    "open": "abertura da página",
    "import": "validação e importação de cookies",
    "next": "navegação Playwright/JavaScript",
    "previous": "navegação Playwright/JavaScript",
    "toggle": "reprodução JavaScript",
    "author": "leitura do vídeo ativo",
    "description": "leitura do vídeo ativo",
    "copy_link": "identificação do link",
    "refresh_info": "leitura do vídeo ativo",
    "search": "carregamento dos resultados",
    "open_search_result": "abertura do vídeo selecionado",
    "volume_up": "controle de volume JavaScript",
    "volume_down": "controle de volume JavaScript",
    "toggle_mute": "controle de volume JavaScript",
    "comments": "leitura dos comentários",
    "post_comment": "publicação de comentário",
    "close_comments": "fechamento dos comentários",
    "toggle_like": "controle de curtida",
    "toggle_favorite": "controle de favorito",
    "diagnostics": "diagnóstico Playwright/JavaScript",
}


class BrowserWorker(threading.Thread):
    """Dona exclusiva do Playwright e do contexto persistente do Chromium."""

    def __init__(
        self,
        profile_dir: Path,
        callback: WorkerCallback,
        video_controller_factory: VideoControllerFactory = TikTokVideoController,
        preferences: VolumePreferences | None = None,
    ) -> None:
        super().__init__(name="TikTokBrowserWorker", daemon=False)
        self._profile_dir = profile_dir
        self._callback = callback
        self._video_controller_factory = video_controller_factory
        self._commands: queue.Queue[BrowserCommand] = queue.Queue()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._browser_visible = True
        self._last_command_sent = "nenhum"
        self._last_command_completed = "nenhum"
        self._last_failure = "nenhuma"
        self._preferences = preferences or VolumePreferences(
            profile_dir.parent / "preferences.json"
        )
        self._volume = self._preferences.load()

    def open_tiktok(self) -> None:
        self._enqueue("open")

    def import_cookies(self, path: Path) -> None:
        self._enqueue("import", path)

    def next_video(self) -> None:
        self._enqueue("next")

    def previous_video(self) -> None:
        self._enqueue("previous")

    def toggle_playback(self) -> None:
        self._enqueue("toggle")

    def read_author(self) -> None:
        self._enqueue("author")

    def read_description(self) -> None:
        self._enqueue("description")

    def copy_link(self) -> None:
        self._enqueue("copy_link")

    def refresh_info(self) -> None:
        self._enqueue("refresh_info")

    def search(self, query: str) -> None:
        self._enqueue("search", query)

    def open_search_result(self, url: str) -> None:
        self._enqueue("open_search_result", url)

    def volume_up(self) -> None:
        self._enqueue("volume_up")

    def volume_down(self) -> None:
        self._enqueue("volume_down")

    def toggle_mute(self) -> None:
        self._enqueue("toggle_mute")

    def open_comments(self) -> None:
        self._enqueue("comments")

    def post_comment(self, text: str) -> None:
        self._enqueue("post_comment", text)

    def close_comments(self) -> None:
        self._enqueue("close_comments")

    def toggle_like(self) -> None:
        self._enqueue("toggle_like")

    def toggle_favorite(self) -> None:
        self._enqueue("toggle_favorite")

    def show_browser(self, visible: bool) -> None:
        self._enqueue("browser_visibility", bool(visible))

    def diagnostics(self) -> None:
        self._enqueue("diagnostics")

    def shutdown(self) -> None:
        self._enqueue("shutdown")

    def _enqueue(self, action: str, argument: Any = None) -> None:
        if action != "diagnostics":
            self._last_command_sent = COMMAND_NAMES.get(action, action)
        self._commands.put(BrowserCommand(action, argument))

    def run(self) -> None:
        try:
            while True:
                command = self._commands.get()
                if command.action == "shutdown":
                    break
                try:
                    self._execute_command(command)
                    if command.action != "diagnostics":
                        self._last_command_completed = COMMAND_NAMES.get(
                            command.action, command.action
                        )
                except (CookieImportError, VideoControlError) as exc:
                    self._report_failure(command, exc, trusted_message=True)
                except Exception as exc:
                    self._report_failure(command, exc, trusted_message=False)
        finally:
            self._close_resources()
            self._notify(WorkerEvent("stopped", "navegador fechado."))

    def _execute_command(self, command: BrowserCommand) -> None:
        if command.action == "open":
            self._open_tiktok()
            return
        if command.action == "import" and command.argument is not None:
            self._import_cookies(command.argument)
            return
        if command.action == "browser_visibility":
            self._change_browser_visibility(bool(command.argument))
            return
        if command.action == "diagnostics":
            self._publish_diagnostics()
            return
        if command.action == "search":
            self._search_videos(str(command.argument or ""))
            return
        if command.action == "open_search_result":
            self._open_search_result(command.argument)
            return

        controller = self._video_controller()
        if command.action == "next":
            self._publish_info(
                controller.next_video(),
                f"Próximo vídeo carregado. Volume {round(self._volume * 100)}%.",
            )
        elif command.action == "previous":
            self._publish_info(
                controller.previous_video(),
                f"Vídeo anterior carregado. Volume {round(self._volume * 100)}%.",
            )
        elif command.action == "toggle":
            paused = controller.toggle_playback()
            self._notify(
                WorkerEvent(
                    "status", "Vídeo pausado." if paused else "Vídeo reproduzindo."
                )
            )
        elif command.action == "author":
            info = controller.get_info()
            self._notify(
                WorkerEvent("announcement", f"Autor: {info.author}.", author=info.author)
            )
        elif command.action == "description":
            info = controller.get_info()
            self._notify(
                WorkerEvent(
                    "announcement",
                    f"Descrição: {info.description}",
                    description=info.description,
                )
            )
        elif command.action == "copy_link":
            self._notify(WorkerEvent("copy_link", "", link=controller.current_url()))
        elif command.action == "refresh_info":
            self._publish_info(controller.get_info(), "Informações atualizadas.")
        elif command.action == "volume_up":
            self._set_volume(controller, self._volume + 0.1)
        elif command.action == "volume_down":
            self._set_volume(controller, self._volume - 0.1)
        elif command.action == "toggle_mute":
            muted = controller.toggle_mute()
            self._notify(
                WorkerEvent("status", "Som desativado" if muted else "Som ativado")
            )
        elif command.action == "comments":
            comments = controller.read_comments()
            count = len(comments)
            self._notify(
                WorkerEvent(
                    "comments",
                    "Nenhum comentário encontrado."
                    if count == 0
                    else f"Comentários carregados: {count}.",
                    comments=comments,
                )
            )
        elif command.action == "post_comment":
            controller.post_comment(str(command.argument or ""))
            self._notify(WorkerEvent("announcement", "Comentário publicado."))
        elif command.action == "close_comments":
            controller.close_comments()
            self._notify(WorkerEvent("status", "Comentários fechados."))
        elif command.action == "toggle_like":
            liked = controller.toggle_like()
            message = (
                "Vídeo curtido."
                if liked is True
                else "Curtida removida."
                if liked is False
                else "Comando de curtir ou descurtir enviado."
            )
            self._notify(WorkerEvent("announcement", message))
        elif command.action == "toggle_favorite":
            favorited = controller.toggle_favorite()
            message = (
                "Vídeo adicionado aos favoritos."
                if favorited is True
                else "Vídeo removido dos favoritos."
                if favorited is False
                else "Comando de favoritar ou desfavoritar enviado."
            )
            self._notify(WorkerEvent("announcement", message))
        else:
            raise VideoControlError("Comando de navegador desconhecido.")

    def _set_volume(self, controller: TikTokVideoController, target: float) -> None:
        self._volume = controller.set_volume(clamp_volume(target))
        self._preferences.save(self._volume)
        self._notify(WorkerEvent("status", volume_message(self._volume)))

    def _search_videos(self, query: str) -> None:
        page = self._active_page()
        page.goto(search_url(query), wait_until="domcontentloaded")
        try:
            page.wait_for_selector('a[href*="/video/"]', timeout=10_000)
        except Exception:
            # Uma pesquisa válida também pode terminar sem nenhum resultado.
            pass
        results = normalize_search_results(page.evaluate(SEARCH_RESULTS_SCRIPT))
        count = len(results)
        self._notify(
            WorkerEvent(
                "search_results",
                f"Pesquisa concluída: {count} resultado{'s' if count != 1 else ''}.",
                search_results=results,
            )
        )

    def _open_search_result(self, value: Any) -> None:
        page = self._active_page()
        page.goto(validate_search_result_url(value), wait_until="domcontentloaded")
        page.bring_to_front()
        try:
            page.wait_for_selector("video", timeout=10_000)
        except Exception:
            pass
        controller = self._video_controller()
        controller.install_volume_preference()
        self._publish_info(controller.get_info(), "Vídeo da pesquisa aberto.")

    def _report_failure(
        self, command: BrowserCommand, exc: Exception, *, trusted_message: bool
    ) -> None:
        operation = COMMAND_NAMES.get(command.action, command.action)
        stage = COMMAND_STAGES.get(command.action, "processamento do comando")
        detail = (
            _sanitize_message(str(exc))
            if trusted_message
            else "detalhes externos omitidos por segurança"
        )
        if command.action in {"next", "previous"} and trusted_message:
            message = detail
        else:
            message = (
                f"Falha em {operation}; etapa {stage}; "
                f"{type(exc).__name__}: {detail}"
            )
        self._last_failure = message
        self._notify(WorkerEvent("error", message))

    def _publish_info(self, info: VideoInfo, message: str) -> None:
        self._notify(
            WorkerEvent(
                "video_info",
                message,
                author=info.author,
                description=info.description,
            )
        )

    def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=False,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        self._context.add_init_script(
            script=volume_preference_init_script(self._volume)
        )
        return self._context

    def _active_page(self) -> Page:
        if (
            self._context is None
            and self._page is not None
            and not self._page.is_closed()
        ):
            return self._page
        context = self._ensure_context()
        pages = getattr(context, "pages", None)
        if pages is None:
            if self._page is not None and not self._page.is_closed():
                return self._page
            raise VideoControlError("Não foi possível localizar a aba do TikTok.")
        live_tiktok_pages = []
        for candidate in pages:
            if candidate.is_closed():
                continue
            hostname = (urlsplit(candidate.url).hostname or "").lower()
            if hostname == "tiktok.com" or hostname.endswith(".tiktok.com"):
                live_tiktok_pages.append(candidate)
        if live_tiktok_pages:
            # Pop-ups e navegações do TikTok podem criar uma nova aba. A mais
            # recente é a que deve receber os comandos, não uma referência antiga.
            self._page = live_tiktok_pages[-1]
        elif self._page is None or self._page.is_closed():
            self._page = pages[-1] if pages else context.new_page()
        return self._page

    def _video_controller(self) -> TikTokVideoController:
        page = self._active_page()
        hostname = (urlsplit(page.url).hostname or "").lower()
        if hostname != "tiktok.com" and not hostname.endswith(".tiktok.com"):
            raise VideoControlError(
                "Abra o TikTok antes de usar os controles de vídeo."
            )
        if self._context is None or page.context is not self._context:
            raise VideoControlError(
                "A página do TikTok não pertence ao contexto persistente atual."
            )
        try:
            page.bring_to_front()
        except Exception as exc:
            raise VideoControlError(
                "Não foi possível ativar a página do TikTok para executar o comando."
            ) from exc
        return self._video_controller_factory(page, self._volume)

    def _open_tiktok(self) -> None:
        page = self._active_page()
        page.goto(TIKTOK_URL, wait_until="domcontentloaded")
        page.bring_to_front()
        self._notify(
            WorkerEvent(
                "browser_visibility",
                "Ocultamento temporariamente desativado para preservar a reprodução. "
                f"Volume inicial {round(self._volume * 100)}%.",
                browser_visible=True,
            )
        )

    def _import_cookies(self, path: Path) -> None:
        result = load_cookie_file(path)
        cookies = result.cookies
        diagnostics = result.diagnostics
        context = self._ensure_context()

        try:
            context.clear_cookies(domain=re.compile(r"(^|\.)tiktok\.com$", re.I))
        except TypeError:
            # Playwright anterior à filtragem por domínio: limpa apenas cookies,
            # sem remover localStorage, IndexedDB ou arquivos do perfil.
            try:
                context.clear_cookies()
            except Exception:
                raise CookieImportError(
                    f"{diagnostics.file_summary()} Não foi possível limpar os cookies "
                    "antigos do perfil."
                ) from None
        except Exception:
            raise CookieImportError(
                f"{diagnostics.file_summary()} Não foi possível limpar os cookies "
                "TikTok antigos do perfil."
            ) from None

        try:
            context.add_cookies(cookies)
        except Exception:
            raise CookieImportError(
                f"{diagnostics.file_summary()} Não foi possível adicionar os cookies "
                "ao contexto do navegador."
            ) from None

        try:
            cookies_in_context = context.cookies()
            found_after_add = _matching_cookie_count(cookies, cookies_in_context)
            tiktok_cookies = [cookie for cookie in cookies if is_tiktok_cookie(cookie)]
            tiktok_found_after_add = _matching_cookie_count(
                tiktok_cookies, cookies_in_context
            )
        except Exception:
            raise CookieImportError(
                "Os cookies foram enviados, mas não foi possível verificá-los no contexto."
            ) from None
        if found_after_add == 0:
            raise CookieImportError(
                "Nenhum cookie importado apareceu no contexto do navegador."
            )
        if tiktok_found_after_add == 0:
            raise CookieImportError(
                "Nenhum cookie TikTok importado apareceu no contexto do navegador."
            )

        page = self._active_page()
        if page.context is not context:
            raise CookieImportError(
                "A página do TikTok não pertence ao contexto que recebeu os cookies."
            )
        page.goto(TIKTOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2_000)
        page.bring_to_front()

        try:
            retained_after_navigation = _matching_cookie_count(
                tiktok_cookies, context.cookies(TIKTOK_URL)
            )
        except Exception:
            raise CookieImportError(
                "Não foi possível verificar a sessão após abrir o TikTok."
            ) from None
        if retained_after_navigation == 0:
            raise CookieImportError(
                "Os cookies TikTok não permaneceram no contexto após a navegação. "
                "Exporte uma sessão válida novamente."
            )

        self._notify(
            WorkerEvent(
                "status",
                "Cookies verificados e TikTok recarregado. "
                + diagnostics.safe_summary(
                    added_to_context=len(cookies),
                    found_after_add=found_after_add,
                    retained_after_navigation=retained_after_navigation,
                )
                + " Ocultamento temporariamente desativado para preservar a reprodução. "
                + f"Volume inicial {round(self._volume * 100)}%.",
                browser_visible=True,
            )
        )

    def _change_browser_visibility(self, visible: bool) -> None:
        self._browser_visible = True
        self._notify(
            WorkerEvent(
                "browser_visibility",
                "Ocultamento temporariamente desativado para preservar a reprodução.",
                browser_visible=True,
            )
        )

    def _publish_diagnostics(self) -> None:
        if self._context is None or self._page is None or self._page.is_closed():
            connected = "não"
            url = "indisponível"
            video_text = "vídeos 0; vídeo ativo não"
        else:
            connected = "sim"
            url = _safe_page_url(self._page.url)
            try:
                diagnostics = self._video_controller().diagnostics()
                count = int(diagnostics.get("count", 0))
                active = bool(diagnostics.get("active"))
                if active:
                    state = "pausado" if diagnostics.get("paused") else "reproduzindo"
                    volume = round(float(diagnostics.get("volume", 0)) * 100)
                    sound = "som desativado" if diagnostics.get("muted") else "som ativado"
                    visibility = str(diagnostics.get("visibility", "desconhecida"))
                    video_text = (
                        f"vídeos {count}; vídeo ativo sim; estado {state}; "
                        f"volume {volume}%; {sound}; visibilidade {visibility}"
                    )
                else:
                    video_text = f"vídeos {count}; vídeo ativo não"
            except VideoControlError as exc:
                video_text = f"inspeção falhou: {_sanitize_message(str(exc))}"
        self._notify(
            WorkerEvent(
                "diagnostics",
                f"Diagnóstico: página conectada {connected}; URL {url}; {video_text}; "
                f"último comando enviado {self._last_command_sent}; "
                f"último comando concluído {self._last_command_completed}; "
                f"última falha {self._last_failure}.",
                browser_visible=True,
            )
        )

    def _close_resources(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None

    def _notify(self, event: WorkerEvent) -> None:
        self._callback(event)


def _matching_cookie_count(
    imported: list[dict[str, Any]], found: list[dict[str, Any]]
) -> int:
    imported_identities = {_cookie_identity(cookie) for cookie in imported}
    return sum(_cookie_identity(cookie) in imported_identities for cookie in found)


def _cookie_identity(cookie: dict[str, Any]) -> tuple[str, str, str]:
    name = cookie.get("name") if isinstance(cookie.get("name"), str) else ""
    domain = normalized_cookie_domain(cookie)
    path = cookie.get("path") if isinstance(cookie.get("path"), str) else ""
    if not path:
        path = "/"
    return name, domain, path


def _safe_page_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "indisponível"


def _sanitize_message(value: str) -> str:
    text = re.sub(r"[\r\n\t]+", " ", value).strip()
    text = re.sub(r"([?&](?:token|auth|session|cookie)[^=\s]*)=[^&\s]+", r"\1=[removido]", text, flags=re.I)
    return text[:300] or "sem detalhes"
