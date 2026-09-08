"""Experimental embedded browser; no extension or external browser window."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import wx
import wx.html2 as html2

from ui.nvda_announcer import speak_with_accessible_output
from app_logging import get_logger

logger = get_logger()


# RegisterHotKey takes Windows virtual-key codes, NOT wx.WXK_* codes.
VK_F6 = 0x75
FOCUS_PAGE_HOTKEY = 0x4150
PAGE_FOCUS_SCRIPT = """(() => {
    const visible = el => el.getClientRects().length &&
        getComputedStyle(el).visibility !== 'hidden' && !el.closest('[inert]');
    let target = document.activeElement;
    if (!target || target === document.body || target === document.documentElement || !visible(target)) {
        const scope = document.querySelector('[role="dialog"],dialog[open]') || document;
        target = [...scope.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')]
            .find(el => !el.disabled && el.tabIndex >= 0 && visible(el));
    }
    if (!target) {
        target = document.body;
        if (!target) return;
        if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
    }
    target.focus({preventScroll: true});
})()"""


class EmbeddedFocusMixin:
    def _activation_changed(self, event):
        if event.GetActive():
            for hotkey, modifier, label in ((FOCUS_PAGE_HOTKEY, 0, "F6"),):
                if hotkey not in self._registered_hotkeys:
                    if self.RegisterHotKey(hotkey, modifier, VK_F6):
                        self._registered_hotkeys.add(hotkey)
                    else:
                        self.status(f"Não foi possível reservar {label}. Outro programa pode estar usando esse atalho.")
        else:
            self._release_hotkey()
        event.Skip()

    def _release_hotkey(self):
        for hotkey in self._registered_hotkeys:
            self.UnregisterHotKey(hotkey)
        self._registered_hotkeys.clear()

    def focus_controls(self, event=None):
        self._pending_page_focus = None
        view = self.current()
        if view is not None:
            view.SetCanFocus(False)
        target = getattr(self, 'player_focus_target', None) or self.play_button
        target.SetFocus()
        self.status("Player do aplicativo. Use F1 para os atalhos; F6 volta à página.")

    def focus_page(self, event=None):
        if not self.current():
            self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram.')
            return
        view = self.current()
        if view is None:
            return
        view.SetCanFocus(True)
        self._pending_page_focus = view
        # IsBusy includes subresources and may stay true on an interactive login
        # page. Only wait while there is no platform document to focus.
        logger.info('Page focus requested: platform=%s busy=%s',
                    self.network.GetStringSelection(), view.IsBusy())
        if view.GetCurrentURL() in ("", "about:blank"):
            self.status("Carregando a rede selecionada. O foco entrará na página quando ela estiver pronta.")
            return
        self._enter_page(view)

    def _page_document_loaded(self, event):
        view = event.GetEventObject()
        # Login documents must be reachable even when the video bridge isn't ready.
        if (self._pending_page_focus is view and self.current() is view
                and view.GetCurrentURL() not in ('', 'about:blank')):
            wx.CallAfter(self._enter_page, view)
        event.Skip()

    def toggle_page_controls(self, event=None):
        view = self.current()
        if self._pending_page_focus is not None or (view is not None and wx.Window.FindFocus() is view):
            self.focus_controls()
            return
        self.focus_page()

    def _enter_page(self, view):
        if self._pending_page_focus is not view or self.current() is not view:
            return
        self._pending_page_focus = None
        view.SetFocus()
        # SetFocus alone can stop at the WebView2 host pane, outside RootWebArea.
        # Explicit DOM focus gives NVDA a real page element and tab position.
        view.RunScriptAsync(PAGE_FOCUS_SCRIPT)
        logger.info('Page focus entered: platform=%s', self.network.GetStringSelection())
        self.status(f"Página do {self.network.GetStringSelection()}. F6 retorna aos controles do aplicativo.")

