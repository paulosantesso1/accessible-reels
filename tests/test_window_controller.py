from __future__ import annotations

import os

import pytest

from tiktok.window_controller import (
    BrowserWindowController,
    SW_HIDE,
    SW_SHOW,
    Win32WindowBackend,
)


class FakeBackend:
    def __init__(self, descendants=None, windows=None, fail=False):
        self.descendants = set(descendants or [])
        self.windows = list(windows or [])
        self.fail = fail
        self.calls = []

    def descendants_of(self, root_pid):
        if self.fail:
            raise OSError("falha simulada")
        return set(self.descendants)

    def top_level_windows(self):
        return list(self.windows)

    def show_window(self, handle, command):
        self.calls.append((handle, command))


def test_failure_to_identify_window_does_nothing():
    backend = FakeBackend(fail=True)
    controller = BrowserWindowController(100, backend)
    assert controller.set_visible(False) is False
    assert backend.calls == []


def test_missing_playwright_pid_fails_safely():
    backend = FakeBackend(descendants={200}, windows=[(10, 200, True)])
    controller = BrowserWindowController(None, backend)
    assert controller.set_visible(False) is False
    assert backend.calls == []


def test_only_window_from_application_process_tree_is_hidden():
    # A janela 99 pode ter qualquer título (Chrome, Chromium ou TikTok): seu PID
    # não é descendente do driver e, portanto, nunca é tocado.
    backend = FakeBackend(
        descendants={100, 101, 102},
        windows=[(10, 102, True), (99, 9000, True)],
    )
    controller = BrowserWindowController(100, backend)
    assert controller.set_visible(False) is True
    assert backend.calls == [(10, SW_HIDE)]


def test_internal_window_that_was_already_hidden_is_never_shown_or_hidden():
    backend = FakeBackend(
        descendants={100, 101},
        windows=[(10, 101, True), (11, 101, False)],
    )
    controller = BrowserWindowController(100, backend)
    assert controller.set_visible(False) is True
    backend.windows = [(10, 101, False), (11, 101, False)]
    assert controller.set_visible(True) is True
    assert (11, SW_HIDE) not in backend.calls
    assert (11, SW_SHOW) not in backend.calls


def test_application_window_can_be_hidden_then_shown_again():
    backend = FakeBackend(descendants={100, 101}, windows=[(10, 101, True)])
    controller = BrowserWindowController(100, backend)
    assert controller.set_visible(False) is True
    backend.windows = [(10, 101, False)]
    assert controller.set_visible(True) is True
    assert backend.calls == [(10, SW_HIDE), (10, SW_SHOW)]


@pytest.mark.skipif(os.name != "nt", reason="API exclusiva do Windows")
def test_native_process_snapshot_can_validate_its_own_root():
    assert os.getpid() in Win32WindowBackend().descendants_of(os.getpid())
