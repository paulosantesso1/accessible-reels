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
        # The platform loops the video itself right as it nears the end
        # instead of firing a real 'ended'; asking to advance in the
        # middle of that caught next/previous mid-transition and it
        # handled that unreliably, especially in the background. Give it
        # a moment to settle first.
        assert "setTimeout(() => window.chrome.webview.postMessage('auto_scroll_next')" in script
        # Advances while the video is still playing, the same state a
        # manual next/previous always runs against. An earlier version
        # paused the video and fought the platform resuming it, which put
        # next/previous in a state it handled far less reliably.
        assert "video.pause()" not in script

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

def test_iconize_schedules_offscreen_replacement(frame):
    # WebView2 is a child window and does not reliably get notified when
    # the top-level window is minimized/restored (a documented WebView2
    # limitation), which left it unable to reliably process commands --
    # including next/previous, and auto-scroll by extension -- until the
    # window was brought back. Moving off-screen instead keeps it a
    # normal, restored (never iconized) window from WebView2's
    # perspective, so nothing suspends its renderer.
    event = Mock()
    event.IsIconized.return_value = True

    with patch('wx.CallAfter') as call_after:
        frame._on_iconize(event)

    call_after.assert_called_once_with(frame._replace_minimize_with_offscreen)
    event.Skip.assert_called_once()

def test_restoring_from_iconize_does_not_schedule_offscreen_replacement(frame):
    event = Mock()
    event.IsIconized.return_value = False

    with patch('wx.CallAfter') as call_after:
        frame._on_iconize(event)

    call_after.assert_not_called()
    event.Skip.assert_called_once()

def test_replace_minimize_with_offscreen_moves_window_and_remembers_position(frame):
    frame._restore_position = None

    with patch.object(frame, 'IsIconized', return_value=True), \
         patch.object(frame, 'GetPosition', return_value=wx.Point(50, 60)), \
         patch.object(frame, 'Iconize') as iconize, \
         patch.object(frame, 'SetPosition') as set_position:
        frame._replace_minimize_with_offscreen()

    iconize.assert_called_once_with(False)
    set_position.assert_called_once_with(wx.Point(-32000, -32000))
    assert frame._restore_position == wx.Point(50, 60)

def test_replace_minimize_with_offscreen_is_noop_once_restored(frame):
    with patch.object(frame, 'IsIconized', return_value=False), \
         patch.object(frame, 'SetPosition') as set_position:
        frame._replace_minimize_with_offscreen()

    set_position.assert_not_called()

def test_restore_offscreen_position_puts_window_back(frame):
    frame._restore_position = wx.Point(10, 20)

    with patch.object(frame, 'SetPosition') as set_position:
        frame._restore_offscreen_position()

    set_position.assert_called_once_with(wx.Point(10, 20))
    assert frame._restore_position is None

def test_restore_offscreen_position_is_noop_when_not_offscreen(frame):
    frame._restore_position = None

    with patch.object(frame, 'SetPosition') as set_position:
        frame._restore_offscreen_position()

    set_position.assert_not_called()

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
