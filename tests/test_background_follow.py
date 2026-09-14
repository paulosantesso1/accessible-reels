from unittest.mock import Mock, patch

from ui.background_follow import BackgroundFollow


def worker():
    task = BackgroundFollow.__new__(BackgroundFollow)
    task.done = False
    task.started = False
    task.profile_url = 'https://www.tiktok.com/@ana'
    task.toggle = True
    task.client = Mock()
    task.view = Mock()
    task.host = Mock()
    task.timer = Mock()
    task.completed = Mock()
    return task


def test_duplicate_loaded_events_do_not_toggle_twice():
    task = worker()
    task.loaded()
    task.loaded()
    task.client.execute.assert_called_once_with('profile_follow', {
        'toggle': True, 'profile_url': 'https://www.tiktok.com/@ana',
    }, task.finish)


def test_completion_closes_auxiliary_document_and_announces_once():
    task = worker()
    with patch('ui.background_follow.wx.CallAfter', side_effect=lambda fn: fn()):
        task.finish({'ok': True, 'state': True})
        task.failed('Late navigation error')
    task.timer.Stop.assert_called_once()
    task.client.close.assert_called_once()
    task.host.Destroy.assert_called_once()
    task.completed.assert_called_once_with({'ok': True, 'state': True})


def test_shutdown_cancels_late_result_without_announcing():
    task = worker()
    with patch('ui.background_follow.wx.CallAfter', side_effect=lambda fn: fn()):
        task.close()
        task.finish({'ok': True, 'state': True})
    task.completed.assert_not_called()
