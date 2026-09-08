"""Regression tests for native hotkeys and delayed embedded-page focus."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import wx

from ui.webview_focus import EmbeddedFocusMixin as WebViewFrame, FOCUS_PAGE_HOTKEY


def test_windows_hotkeys_use_virtual_key_f6_and_valid_ids():
    frame = SimpleNamespace(_registered_hotkeys=set(), RegisterHotKey=Mock(return_value=True), status=Mock())
    event = Mock()
    event.GetActive.return_value = True
    WebViewFrame._activation_changed(frame, event)
    assert frame.RegisterHotKey.call_args_list == [
        ((FOCUS_PAGE_HOTKEY, 0, 0x75),),
    ]
    assert all(0 <= key <= 0xBFFF for key in frame._registered_hotkeys)
    frame.RegisterHotKey.reset_mock()
    WebViewFrame._activation_changed(frame, event)
    frame.RegisterHotKey.assert_not_called()
    frame.UnregisterHotKey = Mock()
    WebViewFrame._release_hotkey(frame)
    assert frame.UnregisterHotKey.call_count == 1
    assert not frame._registered_hotkeys


def test_f6_does_not_open_a_network_implicitly():
    frame = SimpleNamespace(current=Mock(return_value=None), open_network=Mock(), status=Mock())
    WebViewFrame.focus_page(frame)
    frame.open_network.assert_not_called()
    frame.status.assert_called_once()


def test_f6_waits_for_explicitly_opened_network():
    view = Mock()
    view.IsBusy.return_value = True
    view.GetCurrentURL.return_value = 'about:blank'
    frame = SimpleNamespace(current=Mock(return_value=view), open_network=Mock(),
                            status=Mock(), _enter_page=Mock(), network=Mock())
    WebViewFrame.focus_page(frame)
    frame.open_network.assert_not_called()
    assert frame._pending_page_focus is view
    frame._enter_page.assert_not_called()


def test_return_to_controls_cancels_pending_page_focus():
    view = Mock()
    frame = SimpleNamespace(_pending_page_focus=view, play_button=Mock(), status=Mock(),
                            current=Mock(return_value=view))
    WebViewFrame.focus_controls(frame)
    WebViewFrame._enter_page(frame, view)
    view.SetCanFocus.assert_called_once_with(False)
    frame.play_button.SetFocus.assert_called_once()
    view.SetFocus.assert_not_called()


def test_enter_page_focuses_document_content_not_only_host():
    view = Mock()
    frame = SimpleNamespace(_pending_page_focus=view, current=Mock(return_value=view),
                            network=Mock(), status=Mock())
    WebViewFrame._enter_page(frame, view)
    view.SetFocus.assert_called_once()
    view.RunScriptAsync.assert_called_once()
    assert 'target.focus' in view.RunScriptAsync.call_args.args[0]
    assert frame._pending_page_focus is None


def test_f6_restores_webview_focus_before_entering_page():
    view = Mock()
    view.IsBusy.return_value = False
    view.GetCurrentURL.return_value = 'https://www.tiktok.com/'
    frame = SimpleNamespace(current=Mock(return_value=view), status=Mock(), _enter_page=Mock(), network=Mock())
    WebViewFrame.focus_page(frame)
    view.SetCanFocus.assert_called_once_with(True)
    frame._enter_page.assert_called_once_with(view)


def test_f6_enters_login_document_while_subresources_are_loading():
    view = Mock()
    view.IsBusy.return_value = True
    view.GetCurrentURL.return_value = 'https://www.instagram.com/accounts/login/'
    frame = SimpleNamespace(current=Mock(return_value=view), status=Mock(),
                            _enter_page=Mock(), network=Mock())
    WebViewFrame.focus_page(frame)
    frame._enter_page.assert_called_once_with(view)
    frame.status.assert_not_called()


def test_document_load_resumes_pending_focus_without_video_bridge():
    view = Mock()
    view.GetCurrentURL.return_value = 'https://www.tiktok.com/login'
    frame = SimpleNamespace(current=Mock(return_value=view), _pending_page_focus=view,
                            _enter_page=Mock())
    event = Mock()
    event.GetEventObject.return_value = view
    with patch('ui.webview_focus.wx.CallAfter', side_effect=lambda fn, *args: fn(*args)):
        WebViewFrame._page_document_loaded(frame, event)
    frame._enter_page.assert_called_once_with(view)
    event.Skip.assert_called_once()


def test_document_load_does_not_steal_focus_after_cancel_or_platform_switch():
    view = Mock()
    event = Mock()
    event.GetEventObject.return_value = view
    frame = SimpleNamespace(current=Mock(return_value=view), _pending_page_focus=None,
                            _enter_page=Mock())
    with patch('ui.webview_focus.wx.CallAfter') as schedule:
        WebViewFrame._page_document_loaded(frame, event)
        frame._pending_page_focus = view
        frame.current.return_value = Mock()
        WebViewFrame._page_document_loaded(frame, event)
    schedule.assert_not_called()
