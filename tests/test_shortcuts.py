from __future__ import annotations

import wx

from ui.app_frame import MainFrame
from ui.shortcuts import ACCELERATOR_SPECS, SEEK_ACCELERATOR_SPECS


class AcceleratorHarness:
    _configure_accelerators = MainFrame._configure_accelerators

    def __init__(self):
        self._accelerator_ids = {}
        self.handlers = {}
        self.actions = []
        self.page_focuses = 0
        self.control_focuses = 0
        self._configure_accelerators()

    def Bind(self, _event_type, handler, *, id):
        self.handlers[id] = handler

    def SetAcceleratorTable(self, table):
        self.table = table

    def dispatch(self, action):
        self.actions.append(action)

    def focus_page(self, _event=None):
        self.page_focuses += 1

    def focus_controls(self, _event=None):
        self.control_focuses += 1

    def trigger(self, action):
        self.handlers[self._accelerator_ids[action]](object())


def test_required_accelerators_are_preserved():
    shortcuts = {action: (modifiers, key) for action, modifiers, key in ACCELERATOR_SPECS}
    assert shortcuts["toggle_playback"] == (wx.ACCEL_ALT, ord("P"))
    assert shortcuts["next_video"] == (wx.ACCEL_ALT, wx.WXK_DOWN)
    assert shortcuts["previous_video"] == (wx.ACCEL_ALT, wx.WXK_UP)
    assert shortcuts["volume_up"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_UP)
    assert shortcuts["volume_down"] == (wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_DOWN)


def test_accelerators_dispatch_the_current_window_actions():
    harness = AcceleratorHarness()
    for action in ("toggle_playback", "next_video", "previous_video", "copy_link", "volume_up"):
        harness.trigger(action)
    assert harness.actions == ["toggle_playback", "next_video", "previous_video", "copy_link", "volume_up"]


def test_seek_accelerators_dispatch_their_actions():
    harness = AcceleratorHarness()
    harness.trigger("seek_back_15")
    harness.trigger("seek_forward_30")
    assert harness.actions == ["seek_back_15", "seek_forward_30"]


def test_f6_shortcuts_keep_page_and_controls_focus_distinct():
    harness = AcceleratorHarness()
    f6_handlers = list(harness.handlers.values())[-2:]
    f6_handlers[0](object())
    f6_handlers[1](object())
    assert (harness.page_focuses, harness.control_focuses) == (1, 1)
