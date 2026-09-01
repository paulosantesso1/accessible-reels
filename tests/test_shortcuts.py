from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import wx

from tiktok.client import BrowserCommand, BrowserWorker, WorkerEvent
from ui.main_frame import ACCELERATOR_SPECS, MainFrame


class AcceleratorHarness:
    _configure_accelerators = MainFrame._configure_accelerators
    _dispatch_shortcut = MainFrame._dispatch_shortcut
    _run_video_command = MainFrame._run_video_command

    def __init__(self):
        self.statuses = []
        self.closed = False
        self.handlers = {}
        self.worker = BrowserWorker(Path("perfil-ficticio"), lambda _event: None)
        self.search_opened = 0
        self._configure_accelerators()

    def SetAcceleratorTable(self, table):
        self.table = table

    def Bind(self, _event_type, handler, *, id):
        self.handlers[id] = handler

    def _set_status(self, message):
        self.statuses.append(message)

    def _get_worker(self):
        return self.worker

    def Close(self):
        self.closed = True

    def _show_search(self):
        self.search_opened += 1

    def trigger(self, action):
        self.handlers[self._accelerator_ids[action]](object())


def shortcuts():
    return {action: (modifiers, key) for action, modifiers, key in ACCELERATOR_SPECS}


def test_alt_p_accelerator_is_bound_announced_and_enqueued():
    harness = AcceleratorHarness()
    harness.trigger("toggle_playback")
    assert shortcuts()["toggle_playback"] == (wx.ACCEL_ALT, ord("P"))
    assert harness.statuses == ["Comando recebido: pausar ou reproduzir."]
    assert harness.worker._commands.get_nowait() == BrowserCommand("toggle")


def test_alt_arrows_are_bound_and_enqueued():
    harness = AcceleratorHarness()
    harness.trigger("next_video")
    harness.trigger("previous_video")
    assert shortcuts()["next_video"] == (wx.ACCEL_ALT, wx.WXK_DOWN)
    assert shortcuts()["previous_video"] == (wx.ACCEL_ALT, wx.WXK_UP)
    assert harness.worker._commands.get_nowait() == BrowserCommand("next")
    assert harness.worker._commands.get_nowait() == BrowserCommand("previous")


def test_alt_shift_arrows_have_exact_distinct_accelerators():
    mapping = shortcuts()
    assert mapping["volume_up"] == (
        wx.ACCEL_ALT | wx.ACCEL_SHIFT,
        wx.WXK_UP,
    )
    assert mapping["volume_down"] == (
        wx.ACCEL_ALT | wx.ACCEL_SHIFT,
        wx.WXK_DOWN,
    )
    assert mapping["volume_up"] != mapping["previous_video"]
    assert mapping["volume_down"] != mapping["next_video"]


def test_volume_accelerator_handlers_enqueue_volume_not_navigation():
    harness = AcceleratorHarness()
    harness.trigger("volume_up")
    harness.trigger("volume_down")
    assert harness.worker._commands.get_nowait() == BrowserCommand("volume_up")
    assert harness.worker._commands.get_nowait() == BrowserCommand("volume_down")


def test_all_required_accelerators_are_explicitly_registered():
    mapping = shortcuts()
    assert mapping["read_author"] == (wx.ACCEL_ALT, ord("A"))
    assert mapping["read_description"] == (wx.ACCEL_ALT, ord("D"))
    assert mapping["copy_link"] == (wx.ACCEL_ALT, ord("C"))
    assert mapping["refresh_info"] == (wx.ACCEL_NORMAL, wx.WXK_F5)
    assert mapping["exit"] == (wx.ACCEL_ALT, ord("S"))
    assert mapping["toggle_mute"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("M"))
    assert mapping["diagnostics"] == (wx.ACCEL_ALT, wx.WXK_F12)
    assert mapping["open_comments"] == (wx.ACCEL_NORMAL, ord("C"))
    assert mapping["toggle_like"] == (wx.ACCEL_NORMAL, ord("L"))
    assert mapping["toggle_favorite"] == (wx.ACCEL_NORMAL, ord("F"))
    assert mapping["search"] == (wx.ACCEL_ALT, ord("E"))


def test_alt_e_opens_search_without_sending_a_video_command():
    harness = AcceleratorHarness()
    harness.trigger("search")
    assert harness.search_opened == 1
    assert harness.statuses == ["Abrindo pesquisa de vídeos."]
    assert harness.worker._commands.empty()


def test_social_shortcuts_enqueue_distinct_commands():
    harness = AcceleratorHarness()
    harness.trigger("open_comments")
    harness.trigger("toggle_like")
    harness.trigger("toggle_favorite")
    assert harness.worker._commands.get_nowait() == BrowserCommand("comments")
    assert harness.worker._commands.get_nowait() == BrowserCommand("toggle_like")
    assert harness.worker._commands.get_nowait() == BrowserCommand("toggle_favorite")


def test_alt_s_accelerator_closes_frame():
    harness = AcceleratorHarness()
    harness.trigger("exit")
    assert harness.closed is True


def test_worker_callback_returns_to_interface_through_wx_call_after():
    event = WorkerEvent("status", "concluído")

    class CallbackHarness:
        _receive_worker_event = MainFrame._receive_worker_event

        def _handle_worker_event(self, received):
            raise AssertionError("deve ser agendado, não chamado diretamente")

    harness = CallbackHarness()
    with patch("ui.main_frame.wx.CallAfter") as call_after:
        harness._receive_worker_event(event)
    call_after.assert_called_once_with(harness._handle_worker_event, event)


def test_description_announcement_uses_system_alert_without_focus_change():
    class FakeStatus:
        def __init__(self):
            self.label = ""
            self.name = ""

        def SetLabel(self, value):
            self.label = value

        def SetName(self, value):
            self.name = value

    class AnnouncementHarness:
        _set_status = MainFrame._set_status
        _announce_accessible = MainFrame._announce_accessible

        def __init__(self):
            self.status = FakeStatus()

    harness = AnnouncementHarness()
    with patch("ui.main_frame.speak_with_accessible_output", return_value=False):
        with patch("ui.main_frame.speak_with_nvda", return_value=False):
            with patch("ui.main_frame.raise_uia_notification", return_value=False):
                with patch("ui.main_frame.wx.Accessible.NotifyEvent") as notify:
                    harness._announce_accessible("Descrição: texto completo do vídeo")
    assert harness.status.label == "Status: Descrição: texto completo do vídeo"
    assert [call.args[0] for call in notify.call_args_list] == [
        wx.ACC_EVENT_OBJECT_NAMECHANGE,
        wx.ACC_EVENT_SYSTEM_ALERT,
    ]


def test_description_uses_direct_nvda_speech_when_controller_is_available():
    class FakeStatus:
        def SetLabel(self, _value):
            pass

        def SetName(self, _value):
            pass

    class AnnouncementHarness:
        _set_status = MainFrame._set_status
        _announce_accessible = MainFrame._announce_accessible

        def __init__(self):
            self.status = FakeStatus()

    harness = AnnouncementHarness()
    with patch("ui.main_frame.speak_with_accessible_output", return_value=False):
        with patch("ui.main_frame.speak_with_nvda", return_value=True) as speak:
            with patch("ui.main_frame.wx.Accessible.NotifyEvent") as notify:
                harness._announce_accessible("Descrição: anúncio direto")
    speak.assert_called_once_with("Descrição: anúncio direto")
    assert [call.args[0] for call in notify.call_args_list] == [
        wx.ACC_EVENT_OBJECT_NAMECHANGE
    ]


def test_description_uses_uia_notification_before_legacy_alert():
    class FakeStatus:
        def SetLabel(self, _value):
            pass

        def SetName(self, _value):
            pass

    class AnnouncementHarness:
        _set_status = MainFrame._set_status
        _announce_accessible = MainFrame._announce_accessible

        def __init__(self):
            self.status = FakeStatus()

    harness = AnnouncementHarness()
    with patch("ui.main_frame.speak_with_accessible_output", return_value=False):
        with patch("ui.main_frame.speak_with_nvda", return_value=False):
            with patch("ui.main_frame.raise_uia_notification", return_value=True) as uia:
                with patch("ui.main_frame.wx.Accessible.NotifyEvent") as notify:
                    harness._announce_accessible("Descrição: anúncio UIA")
    uia.assert_called_once_with(harness.status, "Descrição: anúncio UIA")
    assert [call.args[0] for call in notify.call_args_list] == [
        wx.ACC_EVENT_OBJECT_NAMECHANGE
    ]


def test_description_prefers_accessible_output2_nvda_speech():
    class FakeStatus:
        def SetLabel(self, _value):
            pass

        def SetName(self, _value):
            pass

    class AnnouncementHarness:
        _set_status = MainFrame._set_status
        _announce_accessible = MainFrame._announce_accessible

        def __init__(self):
            self.status = FakeStatus()

    harness = AnnouncementHarness()
    with patch(
        "ui.main_frame.speak_with_accessible_output", return_value=True
    ) as accessible_output:
        with patch("ui.main_frame.speak_with_nvda") as direct_nvda:
            with patch("ui.main_frame.raise_uia_notification") as uia:
                with patch("ui.main_frame.wx.Accessible.NotifyEvent") as notify:
                    harness._announce_accessible("Descrição: saída acessível")
    accessible_output.assert_called_once_with("Descrição: saída acessível")
    direct_nvda.assert_not_called()
    uia.assert_not_called()
    assert [call.args[0] for call in notify.call_args_list] == [
        wx.ACC_EVENT_OBJECT_NAMECHANGE
    ]


def test_copy_link_success_is_announced_without_moving_to_a_field():
    class ClipboardHarness:
        _copy_to_clipboard = MainFrame._copy_to_clipboard

        def __init__(self):
            self.announcements = []

        def _announce_accessible(self, message):
            self.announcements.append(message)

    class FakeClipboard:
        def __init__(self):
            self.closed = False

        def Open(self):
            return True

        def SetData(self, _data):
            return True

        def Flush(self):
            return True

        def Close(self):
            self.closed = True

    harness = ClipboardHarness()
    clipboard = FakeClipboard()
    with patch("ui.main_frame.wx.TheClipboard", clipboard):
        harness._copy_to_clipboard("https://www.tiktok.com/@autor/video/123")
    assert harness.announcements == ["Link copiado."]
    assert clipboard.closed is True


def test_invalid_link_is_announced_and_does_not_open_clipboard():
    class ClipboardHarness:
        _copy_to_clipboard = MainFrame._copy_to_clipboard

        def __init__(self):
            self.announcements = []

        def _announce_accessible(self, message):
            self.announcements.append(message)

    harness = ClipboardHarness()
    harness._copy_to_clipboard("https://www.tiktok.com/")
    assert harness.announcements == [
        "Não foi possível identificar o link do vídeo atual"
    ]
