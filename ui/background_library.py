"""Silent, hidden profile page that lists liked or saved videos while the app is in use."""
import time

import wx
import wx.html2 as html2

from ui.background_follow import SILENT_PAGE
from ui.webview_client import WebViewClient

TOTAL_TIMEOUT_MS = 300000
STEP_PAUSE_MS = 300


class BackgroundLibrary:
    """Reads a profile tab in short steps and reports every growth of the list.

    It shares the player's WebView2 session through a separate hidden view, so
    the visible player can open videos while the rest of the list keeps loading.
    """

    def __init__(self, parent, kind, profile_url, on_update, on_error, platform='TikTok'):
        self.kind = kind
        self.platform = platform
        self.created = time.monotonic()
        self.profile_url = profile_url
        self.on_update = on_update
        self.on_error = on_error
        self.done = False
        self.started = False
        self.timer = None
        self.load_timer = None
        self.host = wx.Panel(parent, size=(1000, 800))
        self.host.Hide()
        self.view = html2.WebView.New(backend=html2.WebViewBackendEdge)
        self.client = WebViewClient(
            self.view, platform, lambda: None, self.failed,
            prelude=SILENT_PAGE, before_load=lambda: self.view.SetCanFocus(False),
        )

    def start(self):
        self.client.target_url = self.profile_url
        self.client.after_load = self.loaded
        self.client._after_load_expected_url = self.profile_url
        self.client._after_load_unexpected = self.redirected
        self.timer = wx.CallLater(TOTAL_TIMEOUT_MS, self.failed, 'O carregamento demorou demais.')
        if not self.view.Create(self.host, size=(1000, 800)):
            self.failed('Não foi possível abrir a página do perfil.')
            return
        if not self.done:
            self.client.initialize()

    def loaded(self):
        if self.done or self.started:
            return
        # TikTok often replaces the first profile document with a second one at
        # the same URL; start only after that replacement has settled.
        if self.load_timer:
            self.load_timer.Stop()
        generation = self.client.generation
        self.load_timer = wx.CallLater(1200, self._start_after_settled_load, generation)

    def _start_after_settled_load(self, generation):
        self.load_timer = None
        if self.done or self.started:
            return
        if self.client.generation != generation or not self.client.ready:
            self.loaded()
            return
        self.started = True
        self.view.RunScriptAsync(SILENT_PAGE)
        self._step()

    def _step(self):
        if self.done:
            return
        self.client.execute('library_step', self.kind, self._stepped)

    def _stepped(self, result):
        if self.done:
            return
        if result.get('ok') is not True:
            self.failed(result.get('error') or 'A página não respondeu.')
            return
        finished = bool(result.get('done'))
        self.on_update(self, result.get('results') or [], finished)
        if finished:
            self.close()
        else:
            wx.CallLater(STEP_PAUSE_MS, self._step)

    def redirected(self, url):
        self.failed('O TikTok redirecionou a página. Verifique o login (F6) e tente de novo.')

    def failed(self, message):
        if self.done:
            return
        self.close()
        self.on_error(self, message)

    def close(self):
        if self.done:
            return
        self.done = True
        if self.timer:
            self.timer.Stop()
        if self.load_timer:
            self.load_timer.Stop()
        self.client.close()
        # Destroying the document cancels any pending script.
        wx.CallAfter(self.host.Destroy)
