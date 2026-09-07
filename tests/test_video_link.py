from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tiktok.video_controls import VideoControlError
from ui.app_frame import MainFrame
from ui.video_link import parse_video_link
from ui.webview_client import WebViewClient


@pytest.mark.parametrize('value, platform, url', [
    (' https://www.tiktok.com/@ana/video/123?share=1 ', 'TikTok', 'https://www.tiktok.com/@ana/video/123'),
    ('instagram.com/reels/ABC_123/?igsh=x', 'Instagram', 'https://www.instagram.com/reel/ABC_123/'),
    ('https://vm.tiktok.com/ABC123/', 'TikTok', 'https://vm.tiktok.com/ABC123/'),
    ('https://vt.tiktok.com/ABC123/?x=1', 'TikTok', 'https://vt.tiktok.com/ABC123/'),
    ('https://www.tiktok.com/t/ABC123/', 'TikTok', 'https://www.tiktok.com/t/ABC123/'),
])
def test_recognizes_video_links(value, platform, url):
    assert parse_video_link(value) == (platform, url)


@pytest.mark.parametrize('value', ['', 'javascript:alert(1)', 'https://example.com/reel/ABC/',
    'https://instagram.com.evil.test/reel/ABC/', 'https://user@instagram.com/reel/ABC/',
    'https://instagram.com:444/reel/ABC/', 'https://instagram.com/ana/',
    'https://vm.tiktok.com/', 'https://instagram.com\\@evil.test/reel/ABC/'])
def test_rejects_invalid_links(value):
    with pytest.raises(VideoControlError):
        parse_video_link(value)


def test_open_link_selects_network_and_plays_after_load():
    frame = Mock()
    frame.clients = {}
    frame._active_name = 'Instagram'
    frame._closing_app = False
    MainFrame.open_video_link(frame, 'https://instagram.com/reel/ABC/')
    frame.network.SetStringSelection.assert_called_once_with('Instagram')
    kwargs = frame.open_network.call_args.kwargs
    assert kwargs['url'] == 'https://www.instagram.com/reel/ABC/'
    frame.dispatch.assert_not_called()
    kwargs['after_load']()
    frame.dispatch.assert_called_once_with('play')


def test_open_link_preserves_pending_action():
    frame = Mock()
    frame.clients = {'TikTok': Mock(pending={'token': 'pending'})}
    MainFrame.open_video_link(frame, 'https://instagram.com/reel/ABC/')
    frame.open_network.assert_not_called()
    frame.network.SetStringSelection.assert_not_called()


def test_short_link_navigates_existing_view_without_replacing_session():
    view = Mock()
    client = WebViewClient(view, 'TikTok', Mock(), Mock())
    callback = Mock()
    client.navigate('https://vm.tiktok.com/ABC123/', callback)
    view.LoadURL.assert_called_once_with('https://vm.tiktok.com/ABC123/')
    assert client.after_load is callback
    assert client.view is view


def test_delayed_play_is_skipped_after_switching_network():
    frame = Mock()
    frame.clients = {}
    frame._active_name = 'TikTok'
    frame._closing_app = False
    MainFrame.open_video_link(frame, 'https://instagram.com/reel/ABC/')
    frame.open_network.call_args.kwargs['after_load']()
    frame.dispatch.assert_not_called()


def test_first_loaded_video_refreshes_its_details_automatically():
    current = Mock()
    frame = SimpleNamespace(_active_name='TikTok', _closing_app=False,
                            _pending_page_focus=None, current=Mock(return_value=current),
                            status=Mock(), dispatch=Mock())
    MainFrame.loaded(frame, 'TikTok')
    frame.dispatch.assert_called_once_with('refresh_info')
    assert 'carregado' in frame.status.call_args.args[0]


def test_automatic_detail_refresh_does_not_announce_author_or_description():
    frame = SimpleNamespace(platform_data={'TikTok': {}}, _active_name='TikTok',
                            comment_input=Mock(), _restore_fields=Mock(), status=Mock())
    MainFrame._result(frame, 'TikTok', 'refresh_info', None,
                      {'ok': True, 'author': '@ana', 'description': 'Descrição automática.'})
    frame.status.assert_not_called()


@pytest.mark.parametrize('action', ['next_video', 'previous_video'])
def test_video_navigation_does_not_announce_automatic_details(action):
    frame = SimpleNamespace(platform_data={'TikTok': {}}, _active_name='TikTok',
                            comment_input=Mock(), _restore_fields=Mock(), status=Mock())
    MainFrame._result(frame, 'TikTok', action, None,
                      {'ok': True, 'author': '@ana', 'description': 'Descrição automática.'})
    frame.status.assert_not_called()
