from unittest.mock import Mock, patch

import pytest

from ui.webview_client import WebViewClient


def make_client(platform='TikTok'):
    view = Mock()
    urls = {
        'TikTok': 'https://www.tiktok.com/',
        'Instagram': 'https://www.instagram.com/reels/',
        'YouTube': 'https://www.youtube.com/shorts/',
    }
    view.GetCurrentURL.return_value = urls[platform]
    return WebViewClient(view, platform, Mock(), Mock())


def test_unnamed_child_navigation_does_not_disable_controls():
    client = make_client()
    client.ready = True
    pending = {'callback': Mock(), 'timer': Mock()}
    client.pending = pending
    event = Mock()
    event.GetTarget.return_value = ''
    event.IsTargetMainFrame.return_value = False
    client._navigating(event)
    assert client.ready
    assert client.pending is pending
    assert client.generation == 0


def test_main_navigation_cancels_pending_command():
    client = make_client()
    callback = Mock()
    client.pending = {'callback': callback, 'timer': Mock()}
    event = Mock()
    event.IsTargetMainFrame.return_value = True
    client._navigating(event)
    assert client.generation == 1
    assert client.pending is None
    assert callback.call_args.args[0]['ok'] is False


def test_checked_navigation_cancels_callback_on_a_different_profile():
    client = make_client()
    loaded = Mock()
    unexpected = Mock()
    expected = 'https://www.tiktok.com/@ana'
    client.navigate(expected, loaded, expected_url=expected, on_unexpected=unexpected)
    event = Mock()
    event.IsTargetMainFrame.return_value = True
    event.GetURL.return_value = 'https://www.tiktok.com/@outra'

    with patch('ui.webview_client.wx.CallAfter', side_effect=lambda callback, *args: callback(*args)):
        client._navigating(event)

    loaded.assert_not_called()
    unexpected.assert_called_once_with('https://www.tiktok.com/@outra')
    assert client.after_load is None
    assert client._retry_url is None


@pytest.mark.parametrize(('platform', 'url'), [
    ('TikTok', 'https://www.tiktok.com/@ana/video/123'),
    ('Instagram', 'https://www.instagram.com/reel/ABC123/'),
    ('YouTube', 'https://www.youtube.com/shorts/AbCdEfGhI_j'),
])
def test_failed_result_navigation_retries_once_before_reporting_an_error(platform, url):
    client = make_client(platform)
    after_load = Mock()
    client.navigate(url, after_load)
    client.view.LoadURL.reset_mock()
    event = Mock()
    event.GetTarget.return_value = ''

    with patch('ui.webview_client.wx.CallLater', side_effect=lambda _delay, callback: callback()):
        client._error(event)

    client.view.LoadURL.assert_called_once_with(url)
    assert client.after_load is after_load
    client.on_error.assert_not_called()


def test_second_failed_result_navigation_reports_the_platform_error():
    client = make_client()
    client.navigate('https://www.tiktok.com/@ana/video/123')
    client._retry_attempted = True
    event = Mock()
    event.GetTarget.return_value = ''

    client._error(event)

    client.on_error.assert_called_once_with('A plataforma recusou carregar esta página. Tente outro resultado ou recarregue.')


def test_late_load_error_does_not_cancel_a_command_on_a_ready_page():
    client = make_client()
    client.view.GetCurrentURL.return_value = 'https://www.tiktok.com/@ana'
    client.ready = True
    callback = Mock()
    client.pending = {'callback': callback, 'timer': Mock(), 'token': 'token'}
    client._retry_url = 'https://www.tiktok.com/@ana'
    event = Mock()
    event.GetTarget.return_value = ''

    with patch('ui.webview_client.wx.CallLater') as call_later:
        client._error(event)

    assert client.pending is not None
    callback.assert_not_called()
    call_later.assert_not_called()
    client.on_error.assert_not_called()


def test_loaded_event_waits_for_the_checked_destination_url():
    client = make_client()
    expected = 'https://www.tiktok.com/@ana/video/123'
    callback = Mock()
    client.after_load = callback
    client._after_load_expected_url = expected
    client.view.GetCurrentURL.return_value = 'https://www.tiktok.com/@ana'

    with patch('ui.webview_client.webview_native.evaluate') as evaluate:
        client._loaded(Mock())
        evaluate.call_args.args[2](True, None)

    callback.assert_not_called()
    assert client.after_load is callback
    assert client.ready is False


def test_command_recovers_when_cached_ready_flag_is_false():
    client = make_client()
    callback = Mock()
    with patch('ui.webview_client.wx.CallLater'), patch('ui.webview_client.webview_native.evaluate') as evaluate:
        client.execute('toggle', None, callback)
        script = evaluate.call_args.args[1]
        assert '__accessibleIsReady' in script
        assert '__accessibleRun' in script
        evaluate.call_args.args[2]({'ok': True, 'paused': True}, None)
    callback.assert_called_once_with({'ok': True, 'paused': True})


def test_inactive_network_does_not_execute_commands():
    client = make_client()
    client.active = False
    with patch('ui.webview_client.webview_native.evaluate') as evaluate:
        client.execute('toggle', None, Mock())
        evaluate.assert_not_called()


@pytest.mark.parametrize('action', ('post_comment', 'reply_comment'))
def test_comment_writing_commands_are_not_accepted(action):
    client = make_client()
    with pytest.raises(ValueError, match='Comando desconhecido'):
        client.execute(action, None, Mock())
