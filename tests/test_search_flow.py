from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import wx

from tiktok.search import SearchResult
from ui.app_frame import MainFrame, instagram_fallback_queries, merge_search_results
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
    assert frame.platform_data[platform]['refresh_after_play'] is True
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


def test_list_video_refreshes_its_own_details_after_playback_starts():
    frame = Mock()
    frame._active_name = 'TikTok'
    frame.platform_data = {'TikTok': {'refresh_after_play': True}}

    MainFrame._result(frame, 'TikTok', 'play', None, {'ok': True, 'paused': False})

    assert 'refresh_after_play' not in frame.platform_data['TikTok']
    frame.dispatch.assert_called_once_with('refresh_info')


def test_player_updates_do_not_reset_selected_search_result():
    results = (SearchResult('a', 'a', 'a'), SearchResult('b', 'b', 'b'))
    frame = Mock()
    frame._active_name = 'TikTok'
    frame._results = results
    frame.platform_data = {'TikTok': {'results': results, 'result_index': 1}}
    MainFrame._restore_fields(frame)
    frame.results_list.Set.assert_not_called()
    frame.results_list.SetSelection.assert_called_once_with(1)


def test_more_search_results_are_appended_without_reordering_existing_items():
    first = SearchResult('https://www.tiktok.com/@a/video/1', '@a', 'Primeiro')
    second = SearchResult('https://www.tiktok.com/@b/video/2', '@b', 'Segundo')
    third = SearchResult('https://www.tiktok.com/@c/video/3', '@c', 'Terceiro')

    assert merge_search_results((first, second), (second, third)) == (first, second, third)


def test_load_more_returns_to_saved_query_and_collects_an_additional_batch():
    first = SearchResult('https://www.tiktok.com/@a/video/1', '@a', 'Primeiro')
    frame = Mock()
    frame._active_name = 'TikTok'
    frame.platform_data = {'TikTok': {
        'results': (first,), 'is_list_mode': True,
        'search_url': 'https://www.tiktok.com/search/video?q=gatos',
    }}
    client = Mock(pending=None)
    frame.clients = {'TikTok': client}

    MainFrame.load_more_results(frame)

    assert frame.platform_data['TikTok']['results'] == (first,)
    assert frame.platform_data['TikTok']['is_list_mode'] is False
    assert client.navigate.call_args.args[0] == 'https://www.tiktok.com/search/video?q=gatos'
    client.navigate.call_args.args[1]()
    frame.dispatch.assert_called_once_with('collect_search_results', {'mode': 'more'})
    frame._set_search_loading.assert_called_once_with(True)


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
    frame._set_search_loading.assert_called_once_with(False)
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
    client.navigate.call_args.args[1]()
    frame.dispatch.assert_called_once_with('collect_search_results', 'profile')
    frame._set_search_loading.assert_called_once_with(True)
    assert frame.platform_data['TikTok']['opening_profile'] is True


def test_profile_collection_opens_pinned_or_newest_video_as_the_first_list_item():
    first = SearchResult('https://www.tiktok.com/@user/video/1', '@user', 'Fixado')
    second = SearchResult('https://www.tiktok.com/@user/video/2', '@user', 'Mais novo depois do fixado')
    frame = Mock()
    frame._active_name = 'TikTok'
    frame._results = (first, second)
    frame.platform_data = {'TikTok': {'opening_profile': True, 'results': ()}}
    frame.clients = {'TikTok': Mock()}

    MainFrame._result(frame, 'TikTok', 'collect_search_results', None, {
        'ok': True,
        'results': [
            {'url': first.url, 'author': first.author, 'description': first.description},
            {'url': second.url, 'author': second.author, 'description': second.description},
        ],
    })

    assert frame.platform_data['TikTok']['results'] == (first, second)
    assert frame.platform_data['TikTok']['result_index'] == 0
    assert frame.platform_data['TikTok']['is_list_mode'] is True
    assert 'opening_profile' not in frame.platform_data['TikTok']
    frame.results_list.SetSelection.assert_called_once_with(0)
    frame.open_result.assert_called_once()


def test_instagram_fallback_queries_prefer_shorter_meaningful_terms():
    assert instagram_fallback_queries('Zé trovão e marruá essa é linda demais') == (
        'Zé trovão', 'Zé trovão marruá', 'linda demais',
    )


def test_instagram_fallback_navigates_to_the_next_shorter_query():
    frame = Mock()
    frame._active_name = 'Instagram'
    frame.platform_data = {'Instagram': {}}
    frame.clients = {'Instagram': Mock()}
    data = {'instagram_search_fallbacks': ['Zé trovão']}

    assert MainFrame._try_instagram_search_fallback(frame, data) is True
    assert data['instagram_search_fallbacks'] == []
    assert frame.clients['Instagram'].navigate.call_args.args[0].endswith('q=Z%C3%A9+trov%C3%A3o')
    frame.status.assert_called_once_with('Não houve resultado para a frase inteira. Tentando no Instagram: Zé trovão.')


def test_youtube_search_uses_the_shorts_only_filter():
    frame = Mock()
    frame._active_name = 'YouTube'
    frame.query_field.GetValue.return_value = 'curiosidade histórica'
    frame.current.return_value = True
    frame.clients = {'YouTube': Mock(pending=None)}
    frame.platform_data = {'YouTube': {}}

    MainFrame.search(frame)

    url = frame.clients['YouTube'].navigate.call_args.args[0]
    assert url == 'https://www.youtube.com/results?search_query=curiosidade+hist%C3%B3rica&sp=EgIYAQ%253D%253D'

