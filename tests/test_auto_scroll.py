import pytest
from unittest.mock import Mock, patch
import wx
from ui.app_frame import MainFrame

@pytest.fixture
def frame():
    app = wx.App(False)
    with patch('ui.app_frame.webview_profile_path', return_value=Mock()), \
         patch('ui.app_frame.MainFrame.status'):
        f = MainFrame()
        yield f
        f.Close()

def test_toggle_auto_scroll(frame):
    assert getattr(frame, 'auto_scroll_enabled', False) is False

    with patch.object(frame, '_start_dynamic_timer') as start_timer:
        frame.toggle_auto_scroll()
        
        assert frame.auto_scroll_enabled is True
        start_timer.assert_called_once()
        
        frame.toggle_auto_scroll()
        
        assert frame.auto_scroll_enabled is False

def test_start_dynamic_timer(frame):
    frame.auto_scroll_enabled = True
    
    mock_client = Mock()
    with patch.object(frame, 'current', return_value=mock_client):
        frame._start_dynamic_timer()
        
        mock_client.RunScript.assert_called_once()
        script = mock_client.RunScript.call_args[0][0]
        assert "document.querySelectorAll('video')" in script
        assert "ontimeupdate" in script

def test_on_webview_message_triggers_next_video(frame):
    event = Mock()
    event.GetString.return_value = "auto_scroll_next"
    frame.auto_scroll_enabled = True
    
    with patch.object(frame, 'dispatch') as dispatch, \
         patch('wx.CallLater') as call_later:
         
        frame._on_webview_message(event)
        
        event.Skip.assert_called_once()
        dispatch.assert_called_once_with('next_video')
        call_later.assert_called_once_with(1500, frame._start_dynamic_timer)

def test_on_webview_message_ignores_if_disabled(frame):
    event = Mock()
    event.GetString.return_value = "auto_scroll_next"
    frame.auto_scroll_enabled = False
    
    with patch.object(frame, 'dispatch') as dispatch:
        frame._on_webview_message(event)
        
        event.Skip.assert_called_once()
        dispatch.assert_not_called()

def test_on_webview_message_ignores_other_messages(frame):
    event = Mock()
    event.GetString.return_value = "something_else"
    frame.auto_scroll_enabled = True
    
    with patch.object(frame, 'dispatch') as dispatch:
        frame._on_webview_message(event)
        
        event.Skip.assert_called_once()
        dispatch.assert_not_called()

def test_dispatch_intercepts_for_manual_scroll(frame):
    frame.auto_scroll_enabled = True

    with patch('wx.CallLater') as call_later, \
         patch('ui.app_frame.MainFrame.current', return_value=None):
        
        # Next video schedules restart
        frame.dispatch('next_video')
        call_later.assert_called_once_with(1500, frame._start_dynamic_timer)
        call_later.reset_mock()
        
        # Previous video schedules restart
        frame.dispatch('previous_video')
        call_later.assert_called_once_with(1500, frame._start_dynamic_timer)
