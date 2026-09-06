from unittest.mock import Mock, patch

import pytest
import wx

from tiktok.browser_extension import LocalBrowserWorker
from tiktok.client import BrowserCommand, WorkerEvent
from ui.main_frame import MainFrame


@pytest.fixture(scope="module")
def app():
    app = wx.App.Get() or wx.App(False)
    yield app


@pytest.fixture
def frame(app):
    frame = MainFrame()
    app.Yield()
    with patch.object(frame, "_announce_accessible"):
        yield frame
    frame.Destroy()
    app.Yield()


def test_instagram_shortcut_reaches_instagram_queue_only(frame):
    frame.platform_tabs.SetSelection(1)
    worker = LocalBrowserWorker(lambda _: None, platform="instagram")
    with patch.object(frame.instagram_panel, "_get_worker", return_value=worker):
        frame._dispatch_shortcut("next_video")
        frame._dispatch_shortcut("toggle_like")
    assert worker._commands.get_nowait() == BrowserCommand("next")
    assert worker._commands.get_nowait() == BrowserCommand("toggle_like")
    assert frame._worker is None


def test_instagram_response_does_not_replace_tiktok_fields(frame):
    frame.author_field.SetValue("@tiktok")
    frame.instagram_panel._handle_event(WorkerEvent("video_info", "ok", author="@instagram"))
    assert frame.author_field.GetValue() == "@tiktok"
    assert frame.instagram_panel.author_field.GetValue() == "@instagram"
    frame._announce_accessible.assert_not_called()


def test_tiktok_response_waits_while_instagram_selected(frame):
    frame.platform_tabs.SetSelection(1)
    event = WorkerEvent("announcement", "Descrição TikTok", description="Texto TikTok")
    frame._handle_worker_event(event)
    assert frame._pending_tiktok_events == [event]
    frame._announce_accessible.assert_not_called()
    frame.platform_tabs.SetSelection(0)
    with patch.object(frame, "_restore_wx_focus"):
        frame._deliver_platform_events()
    frame._announce_accessible.assert_called_once_with("Descrição TikTok")


def test_exit_waits_for_both_workers_to_stop(frame):
    tiktok, instagram = Mock(), Mock()
    tiktok.is_alive.return_value = instagram.is_alive.return_value = True
    frame._worker = tiktok
    frame.instagram_panel.worker = instagram
    event = Mock()
    with patch.object(frame, "Destroy") as destroy:
        frame._on_close_window(event)
        event.Veto.assert_called_once()
        tiktok.shutdown.assert_called_once()
        instagram.shutdown.assert_called_once()
        frame._handle_worker_event(WorkerEvent("stopped", "TikTok encerrado"))
        destroy.assert_not_called()
        frame.instagram_panel._handle_event(WorkerEvent("stopped", "Instagram encerrado"))
        destroy.assert_called_once()


def test_instagram_connection_uses_visible_browser_by_default(frame):
    assert frame.instagram_panel.minimized.GetValue() is False
    with patch("ui.instagram_panel.LocalBrowserWorker") as factory:
        factory.return_value.is_alive.return_value = True
        worker = frame.instagram_panel._get_worker()
        assert factory.call_args.kwargs == {"platform": "instagram", "open_minimized": False}
        worker.start.assert_called_once()
        worker.open_platform.assert_called_once()
    frame.instagram_panel.worker = None


def test_instagram_integrated_controls_and_separate_profile(frame):
    panel = frame.instagram_panel
    panel.browser_mode.SetSelection(0)
    panel._on_browser_mode_changed()
    assert panel.import_button.IsEnabled()
    assert not panel.minimized.IsEnabled()
    with patch("ui.instagram_panel.InstagramBrowserWorker") as factory:
        panel._get_worker(open_page=False)
        assert factory.call_args.args[0].name == "instagram_profile"
        factory.return_value.open_platform.assert_not_called()
        assert not panel.browser_mode.IsEnabled()
    panel._handle_event(WorkerEvent("stopped", "Fechado"))
    assert panel.browser_mode.IsEnabled()
    assert panel.import_button.IsEnabled()
    assert not panel.minimized.IsEnabled()


@pytest.mark.parametrize("selection", [0, 1])
def test_tab_enters_selected_platform_without_switching(frame, selection):
    frame.platform_tabs.SetSelection(selection)
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_TAB
    event.AltDown.return_value = event.ControlDown.return_value = event.HasAnyModifiers.return_value = False
    with patch.object(wx.Window, "FindFocus", return_value=frame.platform_tabs), patch.object(frame, "_focus_platform_content") as focus:
        frame._on_tab_navigation(event)
        focus.assert_called_once()
    assert frame.platform_tabs.GetSelection() == selection


def test_ctrl_tab_changes_platform_from_content(frame):
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_TAB
    event.AltDown.return_value = event.ShiftDown.return_value = False
    event.ControlDown.return_value = True
    with patch.object(wx.Window, "FindFocus", return_value=frame.open_button):
        frame._on_tab_navigation(event)
    assert frame.platform_tabs.GetSelection() == 1


def test_plain_tab_in_content_uses_native_traversal(frame):
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_TAB
    event.AltDown.return_value = event.ControlDown.return_value = False
    with patch.object(wx.Window, "FindFocus", return_value=frame.open_button):
        frame._on_tab_navigation(event)
    event.Skip.assert_called_once()
    assert frame.platform_tabs.GetSelection() == 0
