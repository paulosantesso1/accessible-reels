"""A disposable, silent profile page sharing the player's WebView2 session."""
import wx
import wx.html2 as html2

from ui.webview_client import WebViewClient


SILENT_PAGE = """(() => {
  const silence = element => { element.muted = true; element.pause(); };
  document.addEventListener('play', event => {
    if (event.target instanceof HTMLMediaElement) silence(event.target);
  }, true);
  new MutationObserver(() => document.querySelectorAll('video,audio').forEach(silence))
    .observe(document, {childList:true, subtree:true});
})();
"""


class BackgroundFollow:
    def __init__(self, parent, profile_url, toggle, completed):
        self.completed = completed
        self.done = False
        self.started = False
        self.profile_url = profile_url
        self.toggle = toggle
        self.host = wx.Panel(parent, size=(1000, 800))
        self.host.Hide()
        self.view = html2.WebView.New(backend=html2.WebViewBackendEdge)
        self.client = WebViewClient(
            self.view, 'TikTok', lambda: None, self.failed,
            prelude=SILENT_PAGE, before_load=lambda: self.view.SetCanFocus(False),
        )
        self.timer = None

    def start(self):
        # CREATED may initialize synchronously; install the expected destination
        # and callback before creating the native control.
        self.client.target_url = self.profile_url
        self.client.after_load = self.loaded
        self.client._after_load_expected_url = self.profile_url
        self.client._after_load_unexpected = self.redirected
        self.timer = wx.CallLater(30000, self.failed,
                                  'Não foi possível confirmar o seguimento a tempo. Tente novamente.')
        if not self.view.Create(self.host, size=(1000, 800)):
            self.failed('Não foi possível abrir a consulta de seguimento.')
            return
        if not self.done:
            self.client.initialize()

    def loaded(self):
        if self.done or self.started:
            return
        self.started = True
        self.view.RunScriptAsync(SILENT_PAGE)
        self.client.execute('profile_follow', {
            'toggle': self.toggle, 'profile_url': self.profile_url,
        }, self.finish)

    def redirected(self, url):
        self.failed('O TikTok redirecionou a consulta. Verifique o login na página com F6 e tente novamente.')

    def failed(self, message):
        self.finish({'ok': False, 'error': 'Não foi possível confirmar o seguimento. ' + message})

    def finish(self, result):
        if self.done:
            return
        self.close()
        self.completed(result)

    def close(self):
        if self.done:
            return
        self.done = True
        if self.timer:
            self.timer.Stop()
        self.client.close()
        # Destroying the document cancels any pending JavaScript or click.
        wx.CallAfter(self.host.Destroy)
