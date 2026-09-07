"""Regression tests for native hotkeys and delayed embedded-page focus."""
from types import SimpleNamespace
from unittest.mock import Mock

import wx

from ui.webview_focus import EmbeddedFocusMixin as WebViewFrame, FOCUS_PAGE_HOTKEY, FOCUS_CONTROLS_HOTKEY


def test_windows_hotkeys_use_virtual_key_f6_and_valid_ids():
    frame = SimpleNamespace(_registered_hotkeys=set(), RegisterHotKey=Mock(return_value=True), status=Mock())
    event = Mock()
    event.GetActive.return_value = True
    WebViewFrame._activation_changed(frame, event)
    assert frame.RegisterHotKey.call_args_list == [
        ((FOCUS_PAGE_HOTKEY, 0, 0x75),),
        ((FOCUS_CONTROLS_HOTKEY, wx.MOD_SHIFT, 0x75),),
    ]
    assert all(0 <= key <= 0xBFFF for key in frame._registered_hotkeys)
    frame.RegisterHotKey.reset_mock()
    WebViewFrame._activation_changed(frame, event)
    frame.RegisterHotKey.assert_not_called()
    frame.UnregisterHotKey = Mock()
    WebViewFrame._release_hotkey(frame)
    assert frame.UnregisterHotKey.call_count == 2
    assert not frame._registered_hotkeys


def test_f6_does_not_open_a_network_implicitly():
    frame = SimpleNamespace(current=Mock(return_value=None), open_network=Mock(), status=Mock())
    WebViewFrame.focus_page(frame)
    frame.open_network.assert_not_called()
    frame.status.assert_called_once()


def test_f6_waits_for_explicitly_opened_network():
    view = Mock()
    view.IsBusy.return_value = True
    frame = SimpleNamespace(current=Mock(return_value=view), open_network=Mock(),
                            status=Mock(), _enter_page=Mock())
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
