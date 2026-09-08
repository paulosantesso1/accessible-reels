from __future__ import annotations

import wx
from unittest.mock import Mock, patch
from pathlib import Path

from ui.app_frame import (
    MainFrame,
    comment_details_text,
    comment_list_label,
    keyboard_help_text,
    session_summary,
    video_details_text,
)
from ui.shortcuts import ACCELERATOR_SPECS, SEEK_ACCELERATOR_SPECS


class AcceleratorHarness:
    _configure_accelerators = MainFrame._configure_accelerators

    def __init__(self):
        self._accelerator_ids = {}
        self.handlers = {}
        self.actions = []
        self.page_focuses = 0
        self.control_focuses = 0
        self.opened_platforms = []
        self._configure_accelerators()

    def Bind(self, _event_type, handler, *, id):
        self.handlers[id] = handler

    def SetAcceleratorTable(self, table):
        self.table = table

    def dispatch(self, action):
        self.actions.append(action)

    def toggle_page_controls(self, _event=None):
        self.page_focuses += 1

    def _select_platform(self, _name):
        pass

    def _open_platform(self, name):
        self.opened_platforms.append(name)

    def open_network(self):
        pass

    def open_link(self):
        pass

    def trigger(self, action):
        self.handlers[self._accelerator_ids[action]](object())


def test_required_accelerators_are_preserved():
    shortcuts = {action: (modifiers, key) for action, modifiers, key in ACCELERATOR_SPECS}
    assert shortcuts["toggle_playback"] == (wx.ACCEL_ALT, ord("P"))
    assert shortcuts["next_video"] == (wx.ACCEL_ALT, wx.WXK_DOWN)
    assert shortcuts["previous_video"] == (wx.ACCEL_ALT, wx.WXK_UP)
    assert shortcuts["volume_up"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_UP)
    assert shortcuts["volume_down"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_DOWN)
    assert shortcuts["speed_down"] == (wx.ACCEL_SHIFT, ord(","))
    assert shortcuts["speed_up"] == (wx.ACCEL_SHIFT, ord("."))
    assert shortcuts["open_comments"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("C"))
    assert shortcuts["toggle_like"] == (wx.ACCEL_ALT, ord("L"))
    assert shortcuts["toggle_favorite"] == (wx.ACCEL_ALT, ord("F"))


def test_accelerators_dispatch_the_current_window_actions():
    harness = AcceleratorHarness()
    for action in ("toggle_playback", "next_video", "previous_video", "copy_link", "volume_up", "speed_up"):
        harness.trigger(action)
    assert harness.actions == ["toggle_playback", "next_video", "previous_video", "copy_link", "volume_up", "speed_up"]


def test_seek_accelerators_dispatch_their_actions():
    harness = AcceleratorHarness()
    harness.trigger("seek_back_15")
    harness.trigger("seek_forward_30")
    assert harness.actions == ["seek_back_15", "seek_forward_30"]


def test_f6_shortcut_toggles_between_page_and_controls():
    harness = AcceleratorHarness()
    harness.handlers[harness._accelerator_ids['toggle_page_controls']](object())
    assert harness.page_focuses == 1


def test_tab_cycle_stays_within_the_active_app_controls():
    detail, comments, comment_details = Mock(), Mock(), Mock()
    frame = type('Frame', (), {})()
    frame.details_field = detail
    frame.comments_list = comments
    frame.comment_details_field = comment_details
    frame.query_field = Mock()
    frame.results_list = Mock()
    frame.activities = Mock()
    frame.activities.GetSelection.return_value = 1
    frame._comment_focus_controls = lambda: MainFrame._comment_focus_controls(frame)
    frame._cycle_comment_focus = lambda source, backwards=False: MainFrame._cycle_comment_focus(frame, source, backwards)
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_TAB
    event.ControlDown.return_value = False
    event.AltDown.return_value = False
    event.ShiftDown.return_value = False
    event.GetEventObject.return_value = comments
    MainFrame._keep_tab_in_app(frame, event)
    comment_details.SetFocus.assert_called_once()
    event.Skip.assert_not_called()


def test_global_tab_hook_keeps_comment_navigation_out_of_the_webview():
    frame = type('Frame', (), {})()
    frame.activities = Mock()
    frame.activities.GetSelection.return_value = 1
    frame.focus_controls = Mock()
    frame._cycle_comment_focus = Mock()
    event = Mock()
    event.GetKeyCode.return_value = wx.WXK_TAB
    event.ControlDown.return_value = False
    event.AltDown.return_value = False
    event.ShiftDown.return_value = False
    webview = Mock()
    with patch('ui.app_frame.wx.Window.FindFocus', return_value=webview):
        MainFrame._plain_shortcuts(frame, event)
    frame._cycle_comment_focus.assert_called_once_with(webview, False)
    event.Skip.assert_not_called()


def test_session_summary_describes_open_platforms_without_claiming_login():
    assert session_summary(()) == 'TikTok: não aberto | Instagram: não aberto'
    assert session_summary(('TikTok',)) == 'TikTok: aberto | Instagram: não aberto'


def test_f1_help_lists_focus_and_player_shortcuts():
    help_text = keyboard_help_text()
    assert 'Shift+< / Shift+> - Diminuir ou aumentar a velocidade' in help_text
    assert 'Alt+S — Sair\nShift+< / Shift+>' in help_text
    assert 'F6 — Alternar entre a página' in help_text
    assert 'Alt+P — Reproduzir ou pausar' in help_text
    assert 'Ctrl+1 / Ctrl+2' in help_text
    assert 'Os atalhos de uma letra' not in help_text


def test_ctrl_number_shortcuts_open_the_requested_platform():
    harness = AcceleratorHarness()
    harness.handlers[harness._accelerator_ids['select_tiktok']](object())
    harness.handlers[harness._accelerator_ids['select_instagram']](object())
    assert harness.opened_platforms == ['TikTok', 'Instagram']


def test_video_details_keep_author_and_description_in_one_read_only_value():
    assert video_details_text('@ana', 'Um Reel acessível.') == 'Autor: @ana\n\nDescrição:\nUm Reel acessível.'
    assert 'Não identificado' in video_details_text('', '')


def test_comments_use_a_short_list_label_and_full_read_only_details():
    text = 'Um comentário bem longo ' * 8
    label = comment_list_label(2, 3, text)
    assert label.startswith('Comentário 2 de 3:')
    assert label.endswith('...')
    assert comment_details_text(2, 3, text) == f'Comentário 2 de 3\n\n{text.strip()}'



def test_platform_menu_action_selects_and_opens_the_requested_platform():
    frame = type('Frame', (), {})()
    frame._select_platform = Mock()
    frame.network = Mock()
    frame.network.GetStringSelection.return_value = 'Instagram'
    frame.open_network = Mock()
    MainFrame._open_platform(frame, 'Instagram')
    frame._select_platform.assert_called_once_with('Instagram')
    frame.open_network.assert_called_once_with()


def test_webview2_recovery_reports_reinstall_when_backend_fails():
    frame = Mock()
    with patch('ui.app_frame.html2.WebView.IsBackendAvailable', return_value=False), \
            patch('ui.app_frame.wx.MessageBox') as message:
        MainFrame.install_webview2_runtime(frame)
    assert 'Reinstale o Accessible Reels' in message.call_args.args[0]
