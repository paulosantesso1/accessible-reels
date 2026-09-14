from unittest.mock import Mock, patch

from ui.background_follow import BackgroundFollow


def worker():
    task = BackgroundFollow.__new__(BackgroundFollow)
    task.done = False
    task.started = False
    task.confirming = False
    task.expected_state = None
    task.confirmation_worker = None
    task.profile_url = 'https://www.tiktok.com/@ana'
    task.toggle = True
    task.client = Mock()
    task.view = Mock()
    task.host = Mock()
    task.timer = Mock()
    task.load_timer = None
    task.completed = Mock()
    return task


def test_duplicate_loaded_events_do_not_toggle_twice():
    task = worker()
    with patch('ui.background_follow.wx.CallLater') as later:
        task.loaded()
        task.loaded()
        later.call_args.args[1](later.call_args.args[2])
    task.client.execute.assert_called_once_with('profile_follow', {
        'toggle': True, 'profile_url': 'https://www.tiktok.com/@ana',
    }, task.observed)


def test_profile_command_waits_for_the_last_navigation_to_settle():
    task = worker()
    task.client.generation = 3
    task.client.ready = True
    with patch('ui.background_follow.wx.CallLater') as later:
        task.loaded()
        task.client.generation = 4
        later.call_args.args[1](later.call_args.args[2])

    task.client.execute.assert_not_called()
    assert later.call_count == 2


def test_optimistic_change_is_rechecked_without_a_second_click():
    task = worker()
    with patch('ui.background_follow.wx.CallLater') as later:
        task.observed({'ok': True, 'state': True})
    task.completed.assert_not_called()
    task.client.close.assert_not_called()
    with patch('ui.background_follow.BackgroundFollow') as independent:
        later.call_args.args[1]()
    assert independent.call_args.args[1:3] == (task.profile_url, False)
    independent.return_value.start.assert_called_once()
    task.client.navigate.assert_not_called()
    task.client.execute.assert_not_called()
    with patch('ui.background_follow.wx.CallAfter', side_effect=lambda fn: fn()):
        task.observed({'ok': True, 'state': False})
    assert task.completed.call_args.args[0]['ok'] is False


def test_persisted_change_is_announced_only_after_reload():
    task = worker()
    with patch('ui.background_follow.wx.CallLater'):
        task.observed({'ok': True, 'state': False})
    task.completed.assert_not_called()
    with patch('ui.background_follow.wx.CallAfter', side_effect=lambda fn: fn()):
        task.observed({'ok': True, 'state': False})
    task.completed.assert_called_once_with({'ok': True, 'state': False})


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
