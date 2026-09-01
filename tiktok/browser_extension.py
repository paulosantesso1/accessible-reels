from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from tiktok.client import BrowserCommand, WorkerEvent
from tiktok.search import normalize_search_results, validate_search_result_url
from tiktok.video_controls import VideoControlError, clamp_volume, volume_message


BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 43119
BRIDGE_HEADER = "X-Accessible-Reels-Bridge"
EXTENSION_HEADER = "X-Accessible-Reels-Extension"
BRIDGE_TOKEN = "ar-local-tiktok-bridge-v1-8f24c6d1"
@dataclass
class _PendingCommand:
    identifier: str
    action: str
    argument: Any
    completed: threading.Event
    result: dict[str, Any] | None = None


class BrowserExtensionBridge:
    """Ponte HTTP exclusivamente local entre a interface e a extensão."""

    def __init__(self, port: int = BRIDGE_PORT) -> None:
        self.port = port
        self._commands: queue.Queue[_PendingCommand] = queue.Queue()
        self._pending: dict[str, _PendingCommand] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _extension_origin(self) -> str | None:
                origin = self.headers.get("Origin", "")
                if re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
                    return origin
                return None

            def _extension_id(self) -> str | None:
                extension_id = self.headers.get(EXTENSION_HEADER, "")
                if re.fullmatch(r"[a-p]{32}", extension_id):
                    return extension_id
                return None

            def _authorized(self) -> bool:
                extension_id = self._extension_id()
                origin = self.headers.get("Origin", "")
                return (
                    extension_id is not None
                    and self.headers.get(BRIDGE_HEADER) == BRIDGE_TOKEN
                    and (
                        not origin
                        or origin == f"chrome-extension://{extension_id}"
                    )
                )

            def _cors_headers(self) -> None:
                origin = self._extension_origin()
                if origin is None:
                    return
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    f"Content-Type, {BRIDGE_HEADER}, {EXTENSION_HEADER}",
                )

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self._cors_headers()
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                if self._extension_origin() is None:
                    self._json(403, {"error": "forbidden-origin"})
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self._cors_headers()
                self.end_headers()

            def do_GET(self) -> None:
                if not self._authorized():
                    self._json(403, {"error": "forbidden"})
                    return
                if self.path != "/v1/command":
                    self._json(404, {"error": "not-found"})
                    return
                command = bridge._next_command()
                if command is None:
                    self.send_response(204)
                    self.send_header("Cache-Control", "no-store")
                    self._cors_headers()
                    self.end_headers()
                    return
                self._json(
                    200,
                    {
                        "id": command.identifier,
                        "action": command.action,
                        "argument": command.argument,
                    },
                )

            def do_POST(self) -> None:
                if not self._authorized():
                    self._json(403, {"error": "forbidden"})
                    return
                if self.path != "/v1/result":
                    self._json(404, {"error": "not-found"})
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 131_072)
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception:
                    self._json(400, {"error": "invalid-json"})
                    return
                if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                    self._json(400, {"error": "invalid-result"})
                    return
                bridge._complete(payload["id"], payload)
                self._json(200, {"ok": True})

        try:
            self._server = ThreadingHTTPServer((BRIDGE_HOST, self.port), Handler)
        except OSError as exc:
            raise VideoControlError(
                "Não foi possível iniciar a ponte local da extensão. "
                f"Confira se a porta {self.port} já está em uso."
            ) from exc
        self.port = int(self._server.server_address[1])
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="AccessibleReelsExtensionBridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for command in pending:
            command.result = {"ok": False, "error": "A conexão foi encerrada."}
            command.completed.set()

    def execute(
        self, action: str, argument: Any = None, timeout: float = 12.0
    ) -> dict[str, Any]:
        if self._server is None:
            raise VideoControlError("Ative primeiro o modo Chrome ou Brave com extensão.")
        command = _PendingCommand(uuid.uuid4().hex, action, argument, threading.Event())
        with self._lock:
            self._pending[command.identifier] = command
        self._commands.put(command)
        if not command.completed.wait(timeout):
            with self._lock:
                self._pending.pop(command.identifier, None)
                self._cancelled.add(command.identifier)
            raise VideoControlError(
                "A extensão não respondeu. Abra uma aba do TikTok no Chrome ou Brave, "
                "confirme que a extensão Accessible Reels está ativada e tente novamente."
            )
        result = command.result or {"ok": False, "error": "Resposta vazia da extensão."}
        if result.get("ok") is not True:
            raise VideoControlError(str(result.get("error") or "A extensão recusou o comando."))
        return result

    def _next_command(self) -> _PendingCommand | None:
        first_attempt = True
        while True:
            try:
                command = self._commands.get(timeout=10 if first_attempt else 0)
            except queue.Empty:
                return None
            first_attempt = False
            with self._lock:
                if command.identifier in self._cancelled:
                    self._cancelled.discard(command.identifier)
                    continue
                if command.identifier not in self._pending:
                    continue
            return command

    def _complete(self, identifier: str, result: dict[str, Any]) -> None:
        with self._lock:
            command = self._pending.pop(identifier, None)
        if command is None:
            return
        command.result = result
        command.completed.set()


class LocalBrowserWorker(threading.Thread):
    """Mantém os atalhos na interface e executa ações pela extensão local."""

    def __init__(
        self,
        callback: Callable[[WorkerEvent], None],
        *,
        open_minimized: bool = True,
    ) -> None:
        super().__init__(name="TikTokLocalBrowserWorker", daemon=False)
        self._callback = callback
        self._open_minimized = open_minimized
        self._commands: queue.Queue[BrowserCommand] = queue.Queue()
        self._bridge = BrowserExtensionBridge()

    def open_tiktok(self) -> None:
        self._enqueue("open")

    def import_cookies(self, _path: Any) -> None:
        raise VideoControlError("A importação de cookies pertence ao Chromium integrado.")

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
        self._enqueue("open_search_result", validate_search_result_url(url))

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

    def diagnostics(self) -> None:
        self._enqueue("diagnostics")

    def show_browser(self, _visible: bool) -> None:
        return

    def disconnect(self) -> None:
        """Encerra a ponte sem fechar a aba controlada."""
        self._enqueue("shutdown", False)

    def shutdown(self) -> None:
        """Encerra a ponte e fecha a aba controlada ao sair do aplicativo."""
        self._enqueue("shutdown", True)

    def _enqueue(self, action: str, argument: Any = None) -> None:
        self._commands.put(BrowserCommand(action, argument))

    def run(self) -> None:
        try:
            while True:
                command = self._commands.get()
                if command.action == "shutdown":
                    if command.argument:
                        try:
                            self._bridge.execute("close_tiktok", timeout=4)
                        except VideoControlError:
                            # O aplicativo deve conseguir encerrar mesmo se o navegador
                            # ou a extensão já tiverem sido fechados pelo usuário.
                            pass
                    break
                try:
                    self._execute(command)
                except VideoControlError as exc:
                    self._notify(WorkerEvent("error", str(exc)))
                except Exception:
                    self._notify(
                        WorkerEvent(
                            "error", "Falha interna na comunicação com a extensão."
                        )
                    )
        finally:
            self._bridge.stop()
            self._notify(
                WorkerEvent(
                    "stopped",
                    "Conexão com a extensão encerrada; Chrome ou Brave permaneceu aberto.",
                )
            )

    def _execute(self, command: BrowserCommand) -> None:
        if command.action == "open":
            self._bridge.start()
            if self._open_minimized:
                self._bridge.execute("open_minimized", timeout=15)
            self._notify(
                WorkerEvent(
                    "status",
                    "Ponte local ativa em janela minimizada."
                    if self._open_minimized
                    else "Ponte local ativa. Mantendo a aba já autenticada do Chrome ou Brave.",
                    browser_visible=True,
                )
            )
            return
        timeout = 25 if command.action in {"search", "open_search_result"} else 12
        result = self._bridge.execute(command.action, command.argument, timeout=timeout)
        action = command.action
        if action == "search":
            results = normalize_search_results(result.get("results"))
            count = len(results)
            self._notify(
                WorkerEvent(
                    "search_results",
                    f"Pesquisa concluída: {count} resultado{'s' if count != 1 else ''}.",
                    search_results=results,
                )
            )
        elif action in {"next", "previous", "refresh_info", "open_search_result"}:
            self._notify(
                WorkerEvent(
                    "video_info",
                    "Vídeo da pesquisa aberto."
                    if action == "open_search_result"
                    else "Informações do vídeo atualizadas.",
                    author=str(result.get("author") or "Autor não encontrado"),
                    description=str(result.get("description") or "Descrição não encontrada"),
                )
            )
        elif action == "author":
            author = str(result.get("author") or "Autor não encontrado")
            self._notify(WorkerEvent("announcement", f"Autor: {author}.", author=author))
        elif action == "description":
            description = str(result.get("description") or "Descrição não encontrada")
            self._notify(
                WorkerEvent(
                    "announcement",
                    f"Descrição: {description}",
                    description=description,
                )
            )
        elif action == "copy_link":
            self._notify(WorkerEvent("copy_link", "", link=result.get("link")))
        elif action == "toggle":
            self._notify(
                WorkerEvent(
                    "status",
                    "Vídeo pausado." if result.get("paused") else "Vídeo reproduzindo.",
                )
            )
        elif action in {"volume_up", "volume_down"}:
            self._notify(
                WorkerEvent("status", volume_message(clamp_volume(result.get("volume", 1))))
            )
        elif action == "toggle_mute":
            self._notify(
                WorkerEvent(
                    "status", "Som desativado" if result.get("muted") else "Som ativado"
                )
            )
        elif action == "comments":
            comments = tuple(str(item) for item in result.get("comments", []) if item)
            self._notify(
                WorkerEvent(
                    "comments",
                    f"Comentários carregados: {len(comments)}."
                    if comments
                    else "Nenhum comentário encontrado.",
                    comments=comments,
                )
            )
        elif action == "post_comment":
            self._notify(WorkerEvent("announcement", "Comentário publicado."))
        elif action == "close_comments":
            self._notify(WorkerEvent("status", "Comentários fechados."))
        elif action == "toggle_like":
            self._notify(
                WorkerEvent(
                    "announcement",
                    "Vídeo curtido." if result.get("state") else "Curtida removida.",
                )
            )
        elif action == "toggle_favorite":
            self._notify(
                WorkerEvent(
                    "announcement",
                    "Vídeo adicionado aos favoritos."
                    if result.get("state")
                    else "Vídeo removido dos favoritos.",
                )
            )
        elif action == "diagnostics":
            self._notify(
                WorkerEvent(
                    "announcement",
                    str(result.get("message") or "Extensão conectada ao TikTok."),
                )
            )

    def _notify(self, event: WorkerEvent) -> None:
        try:
            self._callback(event)
        except Exception:
            pass
