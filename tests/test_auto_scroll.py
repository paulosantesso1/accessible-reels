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

        # Async: RunScript (synchronous) blocks the UI thread until WebView2
        # answers, which stalls the whole app -- including the global
        # media-key hotkeys -- while the renderer is suspended (window
        # unfocused/occluded).
        mock_client.RunScript.assert_not_called()
        mock_client.RunScriptAsync.assert_called_once()
        script = mock_client.RunScriptAsync.call_args[0][0]
        assert "document.querySelectorAll('video')" in script
        # 'timeupdate' is driven by the media pipeline itself, not a JS
        # timer, so detection keeps working while the window is backgrounded
        # -- unlike the setInterval polling this replaced, which Chromium
        # throttles (or stalls) once the app isn't focused, silently
        # stopping auto-scroll from continuing in the background.
        assert "setInterval(" not in script
        assert "'timeupdate'" in script
        # Re-pauses the video if the platform (e.g. TikTok's scroll rebound)
        # resumes it while the app is still settling on the next post --
        # otherwise it plays a sliver, loops to 0 and "repeats a second".
        assert "resumeGuard" in script
        assert "video.pause()" in script
        # ...but only while it's still the same clip: some platforms reuse
        # this element for the next post, and that legitimate playback must
        # not be paused by mistake.
        assert "currentSrc" in script

def test_on_webview_message_triggers_next_video(frame):
    view = Mock()
    event = Mock()
    event.GetString.return_value = "auto_scroll_next"
    event.GetEventObject.return_value = view
    frame.auto_scroll_enabled = True

    with patch.object(frame, 'dispatch') as dispatch, \
         patch.object(frame, 'current', return_value=view):
        frame._on_webview_message(event)

        event.Skip.assert_called_once()
        dispatch.assert_called_once_with('next_video')

def test_on_webview_message_ignores_background_platform(frame):
    # The handler is bound once on the frame and receives messages bubbled
    # from every embedded platform webview. A leftover auto-scroll interval
    # from a platform the user switched away from (or turned auto-scroll
    # off in) must not be able to advance whichever platform is active now.
    background_view = Mock()
    active_view = Mock()
    event = Mock()
    event.GetString.return_value = "auto_scroll_next"
    event.GetEventObject.return_value = background_view
    frame.auto_scroll_enabled = True

    with patch.object(frame, 'dispatch') as dispatch, \
         patch.object(frame, 'current', return_value=active_view):
        frame._on_webview_message(event)

        dispatch.assert_not_called()

def test_on_webview_message_ignores_if_disabled(frame):
    view = Mock()
    event = Mock()
    event.GetString.return_value = "auto_scroll_next"
    event.GetEventObject.return_value = view
    frame.auto_scroll_enabled = False

    with patch.object(frame, 'dispatch') as dispatch, \
         patch.object(frame, 'current', return_value=view):
        frame._on_webview_message(event)

        event.Skip.assert_called_once()
        dispatch.assert_not_called()

def test_on_webview_message_ignores_other_messages(frame):
    view = Mock()
    event = Mock()
    event.GetString.return_value = "something_else"
    event.GetEventObject.return_value = view
    frame.auto_scroll_enabled = True

    with patch.object(frame, 'dispatch') as dispatch, \
         patch.object(frame, 'current', return_value=view):
        frame._on_webview_message(event)

        event.Skip.assert_called_once()
        dispatch.assert_not_called()

def test_window_refocus_rearms_auto_scroll(frame):
    # The embedded page can be suspended while the window is unfocused, and
    # a <video> element the feed swapped in during that time can be missed
    # by the page's own MutationObserver, which is suspended right along
    # with it. Re-sweep for the video that's live now on refocus instead of
    # leaving auto-scroll stuck until the user manually retoggles it.
    event = Mock()
    event.GetActive.return_value = True

    with patch.object(frame, '_sync_system_hotkeys'), \
         patch.object(frame, '_start_dynamic_timer') as start_timer:
        frame._activation_changed(event)

        start_timer.assert_called_once()
        event.Skip.assert_called_once()

def test_window_losing_focus_does_not_rearm_auto_scroll(frame):
    event = Mock()
    event.GetActive.return_value = False

    with patch.object(frame, '_sync_system_hotkeys'), \
         patch.object(frame, '_start_dynamic_timer') as start_timer:
        frame._activation_changed(event)

        start_timer.assert_not_called()
        event.Skip.assert_called_once()

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
