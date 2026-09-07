"""Experimental embedded browser; no extension or external browser window."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import wx
import wx.html2 as html2

from ui.nvda_announcer import speak_with_accessible_output


# RegisterHotKey takes Windows virtual-key codes, NOT wx.WXK_* codes.
VK_F6 = 0x75
FOCUS_PAGE_HOTKEY = 0x4150
FOCUS_CONTROLS_HOTKEY = 0x4151
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
            for hotkey, modifier, label in (
                (FOCUS_PAGE_HOTKEY, 0, "F6"),
                (FOCUS_CONTROLS_HOTKEY, wx.MOD_SHIFT, "Shift+F6"),
            ):
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
        self.play_button.SetFocus()
        self.status("Controles do aplicativo. Reproduzir ou pausar. Use Tab para os demais controles; F6 volta à página.")

    def focus_page(self, event=None):
        if not self.current():
            self.status('Escolha a rede e pressione Logar / abrir rede selecionada.')
            return
        view = self.current()
        if view is None:
            return
        self._pending_page_focus = view
        if view.IsBusy() or view.GetCurrentURL() in ("", "about:blank"):
            self.status("Carregando a rede selecionada. O foco entrará na página quando ela estiver pronta.")
            return
        self._enter_page(view)

    def _enter_page(self, view):
        if self._pending_page_focus is not view or self.current() is not view:
            return
        self._pending_page_focus = None
        view.SetFocus()
        # SetFocus alone can stop at the WebView2 host pane, outside RootWebArea.
        # Explicit DOM focus gives NVDA a real page element and tab position.
        view.RunScriptAsync(PAGE_FOCUS_SCRIPT)
        self.status(f"Página do {self.network.GetStringSelection()}. Shift+F6 retorna aos controles do aplicativo.")

