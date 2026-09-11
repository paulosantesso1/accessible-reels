from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import wx

from tiktok.search import SearchResult
from ui.app_frame import MainFrame
from ui.webview_client import PLATFORM_URLS, WebViewClient


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram'])
def test_search_collection_is_not_dropped_by_automatic_refresh(platform):
    frame = Mock()
    frame._active_name = platform
    frame._closing_app = False
    frame._pending_page_focus = None
    view = Mock()
    view.GetCurrentURL.return_value = PLATFORM_URLS[platform]
    frame.current.return_value = view
    client = WebViewClient(view, platform, lambda: MainFrame.loaded(frame, platform), Mock())
    frame.clients = {platform: client}
    client.after_load = lambda: MainFrame.dispatch(frame, 'collect_search_results')
    def evaluate(view, script, callback):
        if script.endswith('Boolean(window.__accessibleIsReady?.())'):
            callback(True, None)
        else:
            callback({'ok': True, 'results': []}, None)
    with patch('ui.webview_client.webview_native.evaluate', side_effect=evaluate), \
         patch('ui.webview_client.wx.CallAfter', side_effect=lambda fn: fn()), \
         patch('ui.webview_client.wx.CallLater'), patch('ui.app_frame.wx.Window.FindFocus', return_value=None):
        client._loaded(Mock())
    frame.dispatch.assert_not_called()  # No refresh_info stealing the command slot.
    frame._result.assert_called_once_with(platform, 'collect_search_results', None, {'ok': True, 'results': []})


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram'])
def test_result_player_list_and_feed_round_trip(platform):
    results = (SearchResult('https://www.tiktok.com/@a/video/1', '@a', 'First'),
               SearchResult('https://www.tiktok.com/@b/video/2', '@b', 'Second')) if platform == 'TikTok' else (
               SearchResult('https://www.instagram.com/reel/A/', 'A', 'First'),
               SearchResult('https://www.instagram.com/reel/B/', 'B', 'Second'))
    frame = Mock()
    frame._active_name = platform
    frame._results = results
    frame.platform_data = {platform: {'results': results}}
    client = Mock(pending=None)
    frame.clients = {platform: client}
    frame.results_list.GetSelection.return_value = 1
    MainFrame.open_result(frame)
    assert frame.platform_data[platform]['result_index'] == 1
    assert client.navigate.call_args.args[0] == results[1].url
    frame.activities.SetSelection.assert_called_with(0)
    client.navigate.call_args.args[1]()
    frame.dispatch.assert_called_with('play')
    MainFrame.return_to_results(frame)
    client.set_active.assert_called_with(False)
    frame.activities.SetSelection.assert_called_with(2)
    frame.results_list.SetFocus.assert_called_once()
    MainFrame.home(frame)
    client.set_active.assert_called_with(True)
    client.navigate.assert_called_with(PLATFORM_URLS[platform])
    frame.activities.SetSelection.assert_called_with(0)
    assert frame.platform_data[platform]['result_index'] == 1


def test_player_updates_do_not_reset_selected_search_result():
    results = (SearchResult('a', 'a', 'a'), SearchResult('b', 'b', 'b'))
    frame = Mock()
    frame._active_name = 'TikTok'
    frame._results = results
    frame.platform_data = {'TikTok': {'results': results, 'result_index': 1}}
    MainFrame._restore_fields(frame)
    frame.results_list.Set.assert_not_called()
    frame.results_list.SetSelection.assert_called_once_with(1)


def test_return_to_feed_invalidates_a_pending_command_and_late_response():
    view = Mock()
    view.GetCurrentURL.return_value = PLATFORM_URLS['TikTok']
    client = WebViewClient(view, 'TikTok', Mock(), Mock())
    callback = Mock()
    with patch('ui.webview_client.wx.CallLater'), patch('ui.webview_client.webview_native.evaluate') as evaluate:
        client.execute('collect_search_results', None, callback)
        complete = evaluate.call_args.args[2]
        client.navigate(PLATFORM_URLS['TikTok'])
        assert client.pending is None
        assert not client.ready
        complete({'ok': True, 'results': [{'url': 'stale'}]}, None)
    callback.assert_called_once()
    assert callback.call_args.args[0]['ok'] is False
    view.LoadURL.assert_called_once_with(PLATFORM_URLS['TikTok'])


def test_list_mode_navigation_intercepts_next_and_previous_video():
    frame = Mock()
    frame._active_name = 'TikTok'
    frame._results = ['first', 'second', 'third']
    frame.platform_data = {'TikTok': {'is_list_mode': True, 'result_index': 1}}
    client = Mock(pending=False)
    frame.clients = {'TikTok': client}
    frame.results_list.GetSelection.return_value = 1
    
    # Test next_video
    MainFrame.dispatch(frame, 'next_video')
    frame.results_list.SetSelection.assert_called_once_with(2)
    frame.open_result.assert_called_once()
    client.execute.assert_not_called()
    
    # Reset mocks
    frame.results_list.SetSelection.reset_mock()
    frame.open_result.reset_mock()
    frame.results_list.GetSelection.return_value = 1
    
    # Test previous_video
    MainFrame.dispatch(frame, 'previous_video')
    frame.results_list.SetSelection.assert_called_once_with(0)
    frame.open_result.assert_called_once()
    client.execute.assert_not_called()


def test_escape_returns_to_feed_from_search_tab():
    frame = Mock()
    frame.activities.GetSelection.return_value = 2
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_ESCAPE
    
    MainFrame._plain_shortcuts(frame, event)
    frame._search_beep_timer.Stop.assert_called_once()
    frame.home.assert_called_once()


def test_open_profile_navigates_and_triggers_collection():
    frame = Mock()
    frame._active_name = 'TikTok'
    frame.platform_data = {'TikTok': {'profile_url': 'https://www.tiktok.com/@user'}}
    client = Mock(pending=False)
    frame.clients = {'TikTok': client}
    frame.current.return_value = True
    
    MainFrame.dispatch(frame, 'open_profile')
    client.navigate.assert_called_once()
    assert client.navigate.call_args.args[0] == 'https://www.tiktok.com/@user'
    frame._search_beep_timer.Start.assert_called_once_with(1000)

