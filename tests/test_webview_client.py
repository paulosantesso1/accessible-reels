from unittest.mock import Mock, patch

import pytest

from ui.webview_client import WebViewClient


def make_client():
    view = Mock()
    view.GetCurrentURL.return_value = 'https://www.tiktok.com/'
    return WebViewClient(view, 'TikTok', Mock(), Mock())


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
