"""Liked/saved video lists: shortcuts, navigation flow, collection and batch download."""
from __future__ import annotations

import threading
from unittest.mock import Mock, patch

import pytest
import wx

from tiktok.search import LIBRARY_LIMIT, SearchResult, normalize_search_results
from ui.app_frame import LIBRARY_NAMES, MainFrame
from ui.download_controls import DownloadControlsMixin, already_downloaded
from ui.shortcuts import ACCELERATOR_SPECS, DEFAULT_SHORTCUTS, normalize_shortcut
from ui.webview_client import ACTIONS, PLATFORM_URLS


def mock_frame():
    frame = Mock()
    frame.auto_scroll_enabled = False
    frame._closing_app = False
    frame._active_name = 'TikTok'
    frame.clients = {'TikTok': Mock(pending=None)}
    frame.platform_data = {'TikTok': {}}
    return frame


def test_library_shortcuts_are_registered_and_unique():
    assert DEFAULT_SHORTCUTS['open_liked'] == 'Alt+Shift+L'
    assert DEFAULT_SHORTCUTS['open_favorites'] == 'Alt+Shift+F'
    assert DEFAULT_SHORTCUTS['download_list'] == 'Ctrl+Shift+L'
    assert len(set(DEFAULT_SHORTCUTS.values())) == len(DEFAULT_SHORTCUTS)
    specs = {action: (modifiers, key) for action, modifiers, key in ACCELERATOR_SPECS}
    assert specs['open_liked'] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord('L'))
    assert specs['open_favorites'] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord('F'))
    assert specs['download_list'] == (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('L'))
    # The existing like/save toggles keep their own keys.
    assert normalize_shortcut(DEFAULT_SHORTCUTS['toggle_like']) == 'Alt+L'
    assert normalize_shortcut(DEFAULT_SHORTCUTS['toggle_favorite']) == 'Alt+F'


@pytest.mark.parametrize('action,method,argument', [
    ('open_liked', 'open_library', 'liked'),
    ('open_favorites', 'open_library', 'favorites'),
])
def test_shortcut_invokes_library_opening(action, method, argument):
    frame = mock_frame()
    MainFrame._invoke_shortcut(frame, action)
    getattr(frame, method).assert_called_once_with(argument)


def test_download_list_shortcut_starts_batch_download():
    frame = mock_frame()
    MainFrame._invoke_shortcut(frame, 'download_list')
    frame.start_list_download.assert_called_once_with()


def test_open_library_loads_home_then_asks_for_own_profile():
    frame = mock_frame()
    MainFrame.open_library(frame, 'liked')
    frame.network.SetStringSelection.assert_called_once_with('TikTok')
    kwargs = frame.open_network.call_args.kwargs
    assert kwargs['url'] == PLATFORM_URLS['TikTok']
    kwargs['after_load']()
    frame.dispatch.assert_called_once_with('own_profile', 'liked')
    frame._reset_library_state.assert_called_once_with('TikTok')
    assert 'curtidos' in frame.status.call_args.args[0]


def test_open_library_waits_for_a_pending_command():
    frame = mock_frame()
    frame.clients['TikTok'].pending = {'action': 'next'}
    MainFrame.open_library(frame, 'favorites')
    frame.open_network.assert_not_called()
    frame.status.assert_called_once()


def test_open_library_ignores_unknown_kind():
    frame = mock_frame()
    MainFrame.open_library(frame, 'followers')
    frame.open_network.assert_not_called()


def test_own_profile_result_starts_the_background_worker():
    frame = mock_frame()
    MainFrame._result(frame, 'TikTok', 'own_profile', 'favorites',
                      {'ok': True, 'profile_url': 'https://www.tiktok.com/@ana'})
    frame._start_library_worker.assert_called_once_with('TikTok', 'favorites', 'https://www.tiktok.com/@ana')


def test_own_profile_without_login_reports_the_error_and_stops_loading():
    frame = mock_frame()
    MainFrame._result(frame, 'TikTok', 'own_profile', 'liked',
                      {'ok': False, 'error': 'Entre na sua conta do TikTok pela página (F6) para ver seus vídeos.'})
    frame._platform_error.assert_called_once()
    frame._start_library_worker.assert_not_called()


def make_results(count):
    return [{'url': f'https://www.tiktok.com/@a/video/{1000 + i}', 'author': '@a', 'description': f'v{i}'}
            for i in range(count)]


def library_frame(active=True):
    frame = mock_frame()
    frame._results = ()
    frame._active_name = 'TikTok' if active else 'Instagram'
    worker = object()
    frame._library_worker = worker
    frame.platform_data = {'TikTok': {}}
    frame._show_library_results.side_effect = lambda results, replace: setattr(frame, '_results', results)
    return frame, worker


def update(frame, worker, count, finished=False, kind='liked', name='TikTok', results=None):
    MainFrame._library_update(frame, worker, name, kind, results or make_results(count), finished)


def test_library_results_accept_more_than_fifty_items():
    assert len(normalize_search_results(make_results(120))) == 50
    assert len(normalize_search_results(make_results(120), LIBRARY_LIMIT)) == 120


def test_list_waits_for_the_first_fifty_before_opening():
    frame, worker = library_frame()
    update(frame, worker, 30)
    frame.results_list.SetFocus.assert_not_called()
    assert 'results' not in frame.platform_data['TikTok']
    frame.SetStatusText.assert_called()


def test_list_opens_with_fifty_and_keeps_loading_in_the_background():
    frame, worker = library_frame()
    update(frame, worker, 50)
    data = frame.platform_data['TikTok']
    assert len(data['results']) == 50 and data['library'] == 'liked'
    frame.results_list.SetFocus.assert_called_once()
    frame._set_search_loading.assert_called_with(False)
    message = frame.status.call_args.args[0]
    assert '50 vídeos curtidos prontos' in message and 'segundo plano' in message
    assert 'Alt+L descurte' in message
    assert frame._library_worker is worker


def test_later_batches_are_appended_silently_and_completion_is_announced():
    frame, worker = library_frame()
    update(frame, worker, 50)
    frame.status.reset_mock()
    update(frame, worker, 120)
    assert len(frame.platform_data['TikTok']['results']) == 120
    assert frame._show_library_results.call_args.args[1] is False
    frame.status.assert_not_called()
    frame.results_list.SetFocus.assert_called_once()
    update(frame, worker, 130, finished=True)
    message = frame.status.call_args.args[0]
    assert 'Lista completa: 130 vídeos curtidos' in message
    assert frame._library_worker is None


def test_small_list_opens_complete_without_waiting():
    frame, worker = library_frame()
    update(frame, worker, 3, finished=True, kind='favorites')
    message = frame.status.call_args.args[0]
    assert '3 vídeos favoritos' in message and 'Alt+F remove dos favoritos' in message
    assert 'Ctrl+Shift+L' in message
    assert frame._library_worker is None


def test_empty_library_explains_privacy():
    frame, worker = library_frame()
    update(frame, worker, 0, finished=True)
    message = frame.status.call_args.args[0]
    assert 'Nenhum vídeo curtido' in message and 'privada' in message


def test_stale_worker_updates_are_ignored():
    frame, _worker = library_frame()
    update(frame, object(), 80)
    frame.status.assert_not_called()
    assert 'results' not in frame.platform_data['TikTok']


def test_update_while_another_platform_is_shown_keeps_the_list_hidden():
    frame, worker = library_frame(active=False)
    update(frame, worker, 60)
    assert len(frame.platform_data['TikTok']['results']) == 60
    frame._show_library_results.assert_not_called()


def test_error_after_the_list_opened_keeps_what_was_loaded():
    frame, worker = library_frame()
    update(frame, worker, 70)
    MainFrame._library_error(frame, worker, 'TikTok', 'liked', 'A página não respondeu.')
    message = frame.status.call_args.args[0]
    assert 'restante da lista' in message and '70 vídeos disponíveis' in message
    frame._platform_error.assert_not_called()


def test_error_before_the_list_opened_is_reported_as_a_platform_error():
    frame, worker = library_frame()
    MainFrame._library_error(frame, worker, 'TikTok', 'liked', 'Entre na sua conta.')
    frame._platform_error.assert_called_once_with('TikTok', 'Entre na sua conta.')


def test_a_new_search_cancels_the_library_and_clears_its_marker():
    frame = mock_frame()
    frame.platform_data['TikTok']['library'] = 'liked'
    frame._results = ()
    MainFrame._result(frame, 'TikTok', 'collect_search_results', None, {'ok': True, 'results': make_results(2)})
    frame._cancel_library.assert_called_once()
    assert 'library' not in frame.platform_data['TikTok']


def test_show_library_results_appends_only_new_items_without_resetting_the_list():
    frame = mock_frame()
    old = tuple(SearchResult(**item) for item in make_results(3))
    new = tuple(SearchResult(**item) for item in make_results(5))
    frame._results = old
    MainFrame._show_library_results(frame, new, False)
    assert [call.args[0] for call in frame.results_list.Append.call_args_list] == [item.label for item in new[3:]]
    frame.results_list.Set.assert_not_called()
    assert frame._results == new


def test_show_library_results_replaces_the_list_when_it_is_new():
    frame = mock_frame()
    frame._results = ()
    new = tuple(SearchResult(**item) for item in make_results(2))
    MainFrame._show_library_results(frame, new, True)
    frame.results_list.Set.assert_called_once_with([item.label for item in new])
    frame.results_list.SetSelection.assert_called_once_with(0)


def test_starting_a_worker_silences_the_home_feed_and_replaces_the_previous_worker():
    frame = mock_frame()
    frame._library_worker = None
    with patch('ui.background_library.BackgroundLibrary') as worker_class:
        MainFrame._start_library_worker(frame, 'TikTok', 'liked', 'https://www.tiktok.com/@ana')
    frame.clients['TikTok'].set_active.assert_called_with(False)
    worker_class.return_value.start.assert_called_once()
    assert frame._library_worker is worker_class.return_value
    assert worker_class.call_args.args[1:3] == ('liked', 'https://www.tiktok.com/@ana')


def test_library_names_cover_both_tabs():
    assert LIBRARY_NAMES == {'liked': 'curtidos', 'favorites': 'favoritos'}
    assert {'own_profile', 'library_step'} <= ACTIONS


def test_background_library_steps_until_the_page_reports_done():
    from ui.background_library import BackgroundLibrary
    worker = BackgroundLibrary.__new__(BackgroundLibrary)
    worker.kind, worker.done = 'liked', False
    worker.updates, worker.closed = [], False
    worker.on_update = lambda w, results, finished: worker.updates.append((len(results), finished))
    worker.on_error = Mock()
    worker.close = lambda: setattr(worker, 'closed', True)
    with patch('ui.background_library.wx.CallLater') as call_later:
        worker._stepped({'ok': True, 'results': [1, 2], 'done': False})
        assert call_later.called and not worker.closed
        worker._stepped({'ok': True, 'results': [1, 2, 3], 'done': True})
    assert worker.updates == [(2, False), (3, True)]
    assert worker.closed


def test_background_library_reports_page_errors():
    from ui.background_library import BackgroundLibrary
    worker = BackgroundLibrary.__new__(BackgroundLibrary)
    worker.kind, worker.done = 'liked', False
    worker.on_error = Mock()
    worker.timer = worker.load_timer = None
    worker.client = Mock()
    worker.host = Mock()
    with patch('ui.background_library.wx.CallAfter'):
        worker._stepped({'ok': False, 'error': 'Não encontrei a aba Curtidos'})
    worker.on_error.assert_called_once()
    assert 'Curtidos' in worker.on_error.call_args.args[1]


def test_already_downloaded_matches_the_video_id_in_the_file_name(tmp_path):
    (tmp_path / 'TikTok - titulo [7693578549004881170].mp4').write_bytes(b'x')
    (tmp_path / 'notas [7693578549004881171].txt').write_bytes(b'x')
    assert already_downloaded(tmp_path, 'https://www.tiktok.com/@a/video/7693578549004881170')
    assert not already_downloaded(tmp_path, 'https://www.tiktok.com/@a/video/7693578549004881171')
    assert not already_downloaded(tmp_path / 'missing', 'https://www.tiktok.com/@a/video/1')


class BatchHarness(DownloadControlsMixin):
    def __init__(self, results):
        self._closing_app = False
        self._results = results
        self._active_name = 'TikTok'
        self._download_busy = False
        self._list_download = None
        self._download_folder = None
        self.messages = []
        self.current = lambda: True

    def status(self, message):
        self.messages.append(message)

    def _download_notify(self, _message):
        pass


def test_batch_download_skips_existing_counts_failures_and_reports(tmp_path):
    items = tuple(SearchResult(**item) for item in make_results(4))
    (tmp_path / 'TikTok - x [1001].mp4').write_bytes(b'x')
    harness = BatchHarness(items)
    calls = []

    def fake_download(url, platform, folder, progress):
        calls.append(url)
        if url.endswith('1002'):
            raise RuntimeError('privado')
        return tmp_path / 'novo.mp4'

    job = {'cancel': threading.Event()}
    finished = []
    harness._list_download_finished = lambda *args: finished.append(args)
    with patch('ui.download_controls.download_video', fake_download), \
            patch('ui.download_controls.LIST_DOWNLOAD_PAUSE', 0), \
            patch('ui.download_controls.wx.CallAfter', lambda function, *args: function(*args)):
        harness._list_download_worker('TikTok', items, tmp_path, job)
    assert [url[-4:] for url in calls] == ['1000', '1002', '1003']
    _job, done, skipped, failed, total, _folder = finished[0]
    assert (done, skipped, failed, total) == (2, 1, 1, 4)


def test_batch_download_stops_when_cancelled(tmp_path):
    items = tuple(SearchResult(**item) for item in make_results(5))
    harness = BatchHarness(items)
    job = {'cancel': threading.Event()}
    finished = []
    harness._list_download_finished = lambda *args: finished.append(args)
    calls = []

    def fake_download(url, platform, folder, progress):
        calls.append(url)
        job['cancel'].set()
        return tmp_path / 'novo.mp4'

    with patch('ui.download_controls.download_video', fake_download), \
            patch('ui.download_controls.LIST_DOWNLOAD_PAUSE', 0), \
            patch('ui.download_controls.wx.CallAfter', lambda function, *args: function(*args)):
        harness._list_download_worker('TikTok', items, tmp_path, job)
    assert len(calls) == 1
    assert finished[0][1] == 1


def test_batch_download_requires_a_list():
    harness = BatchHarness(())
    harness.start_list_download()
    assert 'lista de vídeos' in harness.messages[-1]
    assert harness._list_download is None


def test_batch_download_refuses_while_another_download_runs():
    harness = BatchHarness(tuple(SearchResult(**item) for item in make_results(2)))
    harness._download_busy = True
    harness.start_list_download()
    assert 'andamento' in harness.messages[-1]


def test_finishing_a_batch_releases_the_download_lock_and_summarises(tmp_path):
    harness = BatchHarness(())
    harness._download_busy = True
    job = {'cancel': threading.Event()}
    harness._list_download = job
    harness._list_download_finished(job, 3, 1, 2, 6, tmp_path)
    assert harness._download_busy is False and harness._list_download is None
    message = harness.messages[-1]
    assert '3 baixados' in message and '1 já existiam' in message and '2 com falha' in message
    assert 'concluído' in message


def test_batch_download_waits_for_the_list_to_finish_loading():
    harness = BatchHarness(tuple(SearchResult(**item) for item in make_results(2)))
    harness._library_worker = object()
    harness.start_list_download()
    assert 'carregando em segundo plano' in harness.messages[-1]
    assert harness._list_download is None


def shorts(count):
    return [{'url': f'https://www.youtube.com/shorts/abcdefghi{i:02d}', 'author': '', 'description': f'short {i}'}
            for i in range(count)]


def test_alt_shift_l_on_youtube_lists_the_liked_shorts():
    frame = mock_frame()
    frame._active_name = 'YouTube'
    MainFrame.open_library(frame, 'liked')
    frame._open_youtube_library.assert_called_once_with('liked')
    frame.open_network.assert_not_called()


def test_instagram_has_no_liked_or_saved_list():
    frame = mock_frame()
    frame._active_name = 'Instagram'
    MainFrame.open_library(frame, 'liked')
    frame.open_network.assert_not_called()
    frame._open_youtube_library.assert_not_called()
    assert 'Instagram' in frame.status.call_args.args[0]


def test_youtube_has_no_saved_list():
    frame = mock_frame()
    MainFrame._open_youtube_library(frame, 'favorites')
    frame.open_network.assert_not_called()
    assert 'só existe a lista de curtidos' in frame.status.call_args.args[0]


def test_youtube_library_loads_the_playlist_silently_then_starts_the_worker():
    frame = mock_frame()
    frame._active_name = 'YouTube'
    frame.clients = {'YouTube': Mock(pending=None)}
    frame.platform_data = {'YouTube': {}}
    MainFrame._open_youtube_library(frame, 'liked')
    frame.network.SetStringSelection.assert_called_once_with('YouTube')
    kwargs = frame.open_network.call_args.kwargs
    assert kwargs['url'] == 'https://www.youtube.com/playlist?list=LL'
    kwargs['after_load']()
    frame._start_library_worker.assert_called_once_with('YouTube', 'liked', 'https://www.youtube.com/playlist?list=LL')
    frame._reset_library_state.assert_called_once_with('YouTube')


def test_youtube_list_opens_with_fifty_shorts_and_announces_the_rest_in_background():
    frame, worker = library_frame()
    frame._active_name = 'YouTube'
    frame.platform_data = {'YouTube': {}}
    frame.clients = {'YouTube': Mock()}
    update(frame, worker, 50, name='YouTube', results=shorts(50))
    assert len(frame.platform_data['YouTube']['results']) == 50
    assert frame.platform_data['YouTube']['library'] == 'liked'
    frame.clients['YouTube'].set_active.assert_called_with(False)
    assert '50 vídeos curtidos prontos' in frame.status.call_args.args[0]


def test_youtube_results_keep_only_shorts_links():
    from youtube.search import normalize_youtube_results
    mixed = shorts(3) + [{'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'description': 'long video'}]
    assert len(normalize_youtube_results(mixed)) == 3
    assert len(normalize_youtube_results(shorts(60), 500)) == 60
    assert len(normalize_youtube_results(shorts(60))) == 50


def test_background_library_uses_the_requested_platform():
    from ui.background_library import BackgroundLibrary
    with patch('ui.background_library.wx.Panel'), patch('ui.background_library.html2.WebView.New'), \
            patch('ui.background_library.WebViewClient') as client_class:
        BackgroundLibrary(Mock(), 'liked', 'https://www.youtube.com/playlist?list=LL', Mock(), Mock(), platform='YouTube')
    assert client_class.call_args.args[1] == 'YouTube'


def test_list_opens_with_fewer_than_fifty_after_the_wait_when_the_library_is_sparse():
    import time as clock
    frame, worker = library_frame()
    frame._active_name = 'YouTube'
    frame.platform_data = {'YouTube': {}}
    frame.clients = {'YouTube': Mock()}
    worker = Mock(created=clock.monotonic() - 60)
    frame._library_worker = worker
    update(frame, worker, 11, name='YouTube', results=shorts(11))
    assert len(frame.platform_data['YouTube']['results']) == 11
    assert '11 vídeos curtidos prontos' in frame.status.call_args.args[0]


def test_list_keeps_waiting_before_the_wait_is_over_even_with_some_results():
    import time as clock
    frame, _ = library_frame()
    worker = Mock(created=clock.monotonic())
    frame._library_worker = worker
    update(frame, worker, 11)
    frame.results_list.SetFocus.assert_not_called()


def test_list_never_opens_empty_before_the_library_finishes():
    import time as clock
    frame, _ = library_frame()
    worker = Mock(created=clock.monotonic() - 60)
    frame._library_worker = worker
    update(frame, worker, 0)
    frame.results_list.SetFocus.assert_not_called()


def list_frame(selection, count=5):
    frame = mock_frame()
    frame.current.return_value = True
    frame.clients = {'TikTok': Mock(pending=None, active=False)}
    frame.platform_data = {'TikTok': {'is_list_mode': False}}
    frame._results = tuple(SearchResult(**item) for item in make_results(count))
    frame.results_list.GetSelection.return_value = selection
    return frame


def test_alt_down_with_the_list_on_screen_opens_the_next_item():
    frame = list_frame(selection=1)
    MainFrame.dispatch(frame, 'next_video')
    frame.results_list.SetSelection.assert_called_once_with(2)
    frame.open_result.assert_called_once()


def test_alt_down_with_nothing_selected_opens_the_first_item():
    frame = list_frame(selection=wx.NOT_FOUND)
    MainFrame.dispatch(frame, 'next_video')
    frame.results_list.SetSelection.assert_called_once_with(0)


def test_alt_up_at_the_top_of_the_list_says_so_instead_of_failing():
    frame = list_frame(selection=0)
    MainFrame.dispatch(frame, 'previous_video')
    frame.open_result.assert_not_called()
    assert 'Início da lista' in frame.status.call_args.args[0]


def test_command_on_the_list_screen_explains_what_to_do():
    from ui.webview_client import WebViewClient as Client
    view = Mock()
    view.GetCurrentURL.return_value = 'https://www.tiktok.com/'
    client = Client(view, 'TikTok', Mock(), Mock())
    client.active = False
    callback = Mock()
    client.execute('read_author', None, callback)
    assert 'Nenhum vídeo aberto' in callback.call_args.args[0]['error']
