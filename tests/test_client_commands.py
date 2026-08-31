from __future__ import annotations

from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from tiktok.client import BrowserCommand, BrowserWorker, WorkerEvent
from tiktok.video_controls import VideoControlError, VideoInfo


class FakeContext:
    def __init__(self):
        self.closed = False
        self.init_scripts = []

    def close(self):
        self.closed = True

    def add_init_script(self, *, script):
        self.init_scripts.append(script)


class FakePage:
    url = "https://www.tiktok.com/foryou"

    def __init__(self):
        self.context = FakeContext()
        self.brought_to_front = 0

    def is_closed(self) -> bool:
        return False

    def bring_to_front(self):
        self.brought_to_front += 1


class FakeVideoController:
    last_instance = None

    def __init__(self, _page, preferred_volume=1.0) -> None:
        self.info = VideoInfo("@autor", "descrição")
        self.volume = preferred_volume
        self.muted = False
        FakeVideoController.last_instance = self

    def next_video(self) -> VideoInfo:
        return self.info

    def previous_video(self) -> VideoInfo:
        return self.info

    def toggle_playback(self) -> bool:
        return True

    def get_info(self) -> VideoInfo:
        return self.info

    def current_url(self) -> str:
        return "https://www.tiktok.com/@autor/video/123"

    def set_volume(self, value: float) -> float:
        self.volume = value
        return value

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def read_comments(self) -> tuple[str, ...]:
        return ("@ana: Excelente vídeo", "@joao: Muito bom")

    def post_comment(self, text: str) -> None:
        self.posted_comment = text

    def close_comments(self) -> None:
        self.comments_closed = True

    def toggle_like(self) -> bool:
        return True

    def toggle_favorite(self) -> bool:
        return False

    def diagnostics(self):
        return {
            "count": 2,
            "active": True,
            "paused": False,
            "volume": 0.5,
            "muted": False,
            "visibility": "visible",
        }


class MemoryPreferences:
    def __init__(self, volume=0.5):
        self.volume = volume
        self.saved = []

    def load(self):
        return self.volume

    def save(self, volume):
        self.volume = volume
        self.saved.append(volume)


def make_worker(events: list[WorkerEvent], preferences=None) -> BrowserWorker:
    worker = BrowserWorker(
        Path("profile-ficticio"),
        events.append,
        FakeVideoController,
        preferences=preferences or MemoryPreferences(),
    )
    worker._page = FakePage()
    worker._context = worker._page.context
    return worker


def test_public_command_is_sent_to_queue():
    worker = BrowserWorker(
        Path("profile-ficticio"),
        lambda _event: None,
        preferences=MemoryPreferences(0.5),
    )
    worker.next_video()
    assert worker._commands.get_nowait() == BrowserCommand("next")


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("next", "Próximo vídeo carregado. Volume 50%."),
        ("previous", "Vídeo anterior carregado. Volume 50%."),
        ("toggle", "Vídeo pausado."),
        ("refresh_info", "Informações atualizadas."),
    ],
)
def test_commands_produce_structured_responses(command, message):
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand(command))
    assert events[-1].message == message


def test_author_response_updates_only_author():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("author"))
    assert events[-1] == WorkerEvent(
        "announcement", "Autor: @autor.", author="@autor"
    )


def test_description_response_is_an_explicit_accessible_announcement():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("description"))
    assert events[-1] == WorkerEvent(
        "announcement",
        "Descrição: descrição",
        description="descrição",
    )


def test_video_command_activates_persistent_tiktok_page_first():
    worker = make_worker([])
    worker._execute_command(BrowserCommand("author"))
    assert worker._page.brought_to_front == 1


def test_worker_prefers_most_recent_live_tiktok_tab():
    context = FakeContext()
    older = FakePage()
    newer = FakePage()
    older.context = context
    newer.context = context
    context.pages = [older, newer]
    worker = BrowserWorker(
        Path("profile-ficticio"),
        lambda _event: None,
        FakeVideoController,
        preferences=MemoryPreferences(),
    )
    worker._context = context
    worker._page = older
    assert worker._active_page() is newer


def test_copy_link_response_carries_url_without_putting_it_in_status():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("copy_link"))
    assert events[-1].kind == "copy_link"
    assert events[-1].message == ""
    assert events[-1].link.endswith("/video/123")


def test_comments_response_carries_accessible_comment_list():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("comments"))
    assert events[-1].kind == "comments"
    assert events[-1].comments == (
        "@ana: Excelente vídeo",
        "@joao: Muito bom",
    )
    assert events[-1].message == "Comentários carregados: 2."


def test_comment_is_only_published_after_explicit_command():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("post_comment", "Comentário consciente"))
    assert FakeVideoController.last_instance.posted_comment == "Comentário consciente"
    assert events[-1].message == "Comentário publicado."


def test_like_and_favorite_commands_announce_result():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._execute_command(BrowserCommand("toggle_like"))
    assert events[-1].message == "Vídeo curtido."
    worker._execute_command(BrowserCommand("toggle_favorite"))
    assert events[-1].message == "Vídeo removido dos favoritos."


def test_video_commands_require_a_tiktok_page():
    worker = BrowserWorker(
        Path("profile-ficticio"),
        lambda _event: None,
        preferences=MemoryPreferences(0.5),
    )
    worker._page = FakePage()
    worker._page.url = "about:blank"
    with pytest.raises(VideoControlError, match="Abra o TikTok"):
        worker._execute_command(BrowserCommand("next"))


def test_volume_commands_change_ten_percent_and_persist_only_volume():
    events: list[WorkerEvent] = []
    preferences = MemoryPreferences(0.5)
    worker = make_worker(events, preferences)
    worker._execute_command(BrowserCommand("volume_up"))
    assert preferences.saved == [0.6]
    assert events[-1].message == "Volume 60%"
    worker._execute_command(BrowserCommand("volume_down"))
    assert preferences.saved[-1] == 0.5


def test_mute_command_is_not_persisted_as_sensitive_or_extra_state():
    events: list[WorkerEvent] = []
    preferences = MemoryPreferences()
    worker = make_worker(events, preferences)
    worker._execute_command(BrowserCommand("toggle_mute"))
    assert events[-1].message == "Som desativado"
    assert preferences.saved == []


def test_public_navigation_and_volume_commands_remain_distinct():
    worker = BrowserWorker(Path("profile-ficticio"), lambda _event: None)
    worker.next_video()
    worker.volume_up()
    assert worker._commands.get_nowait() == BrowserCommand("next")
    assert worker._commands.get_nowait() == BrowserCommand("volume_up")


def test_browser_hiding_is_temporarily_disabled():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._change_browser_visibility(False)
    assert events[-1].message == (
        "Ocultamento temporariamente desativado para preservar a reprodução."
    )
    assert events[-1].browser_visible is True
    assert not hasattr(worker, "_window_controller")


def test_queued_command_is_processed_by_worker_thread_and_returns_callback():
    events: list[WorkerEvent] = []
    received = threading.Event()

    def callback(event):
        events.append(event)
        if event.message == "Vídeo pausado.":
            received.set()

    worker = BrowserWorker(
        Path("profile-ficticio"),
        callback,
        FakeVideoController,
        preferences=MemoryPreferences(),
    )
    worker._page = FakePage()
    worker._context = worker._page.context
    worker.start()
    worker.toggle_playback()
    assert received.wait(timeout=2)
    worker.shutdown()
    worker.join(timeout=2)
    assert events[0].message == "Vídeo pausado."


def test_failure_contains_operation_stage_type_and_safe_detail():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._report_failure(
        BrowserCommand("toggle"),
        VideoControlError("falha controlada"),
        trusted_message=True,
    )
    assert events[-1].message == (
        "Falha em pausar ou reproduzir; etapa reprodução JavaScript; "
        "VideoControlError: falha controlada"
    )


def test_navigation_failure_omits_internal_playwright_details():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._report_failure(
        BrowserCommand("previous"),
        VideoControlError("O vídeo não mudou."),
        trusted_message=True,
    )
    assert events[-1].message == "O vídeo não mudou."


def test_accessible_diagnostics_reports_safe_page_and_command_state():
    events: list[WorkerEvent] = []
    worker = make_worker(events)
    worker._page.url = "https://www.tiktok.com/foryou?token=segredo#fragmento"
    worker._last_command_sent = "pausar ou reproduzir"
    worker._last_command_completed = "próximo vídeo"
    worker._publish_diagnostics()
    message = events[-1].message
    assert "página conectada sim" in message
    assert "https://www.tiktok.com/foryou" in message
    assert "segredo" not in message
    assert (
        "vídeos 2; vídeo ativo sim; estado reproduzindo; volume 50%; "
        "som ativado; visibilidade visible"
        in message
    )
    assert "último comando enviado pausar ou reproduzir" in message


def test_persistent_chromium_is_started_headed_with_autoplay_enabled():
    class FakeChromium:
        def __init__(self):
            self.kwargs = None

        def launch_persistent_context(self, **kwargs):
            self.kwargs = kwargs
            return FakeContext()

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

    class FakeStarter:
        def __init__(self, playwright):
            self.playwright = playwright

        def start(self):
            return self.playwright

    playwright = FakePlaywright()
    worker = BrowserWorker(
        Path("profile-ficticio"),
        lambda _event: None,
        preferences=MemoryPreferences(0.5),
    )
    with patch("tiktok.client.sync_playwright", return_value=FakeStarter(playwright)):
        with patch.object(Path, "mkdir"):
            worker._ensure_context()
    assert playwright.chromium.kwargs["headless"] is False
    assert playwright.chromium.kwargs["args"] == [
        "--autoplay-policy=no-user-gesture-required"
    ]
    assert "__tiktokAccessibleVolumeState" in worker._context.init_scripts[0]
    assert "(0.5);" in worker._context.init_scripts[0]
