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
        self.expected_state = None
        self.confirming = False
        self.confirmation_worker = None
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
        self.load_timer = None

    def start(self):
        # CREATED may initialize synchronously; install the expected destination
        # and callback before creating the native control.
        self.client.target_url = self.profile_url
        self.client.after_load = self.loaded
        self.client._after_load_expected_url = self.profile_url
        self.client._after_load_unexpected = self.redirected
        self.timer = wx.CallLater(45000, self.failed,
                                  'Não foi possível confirmar o seguimento a tempo. Tente novamente.')
        if not self.view.Create(self.host, size=(1000, 800)):
            self.failed('Não foi possível abrir a consulta de seguimento.')
            return
        if not self.done:
            self.client.initialize()

    def loaded(self):
        if self.done or self.started:
            return
        # TikTok often replaces the first profile document with a second
        # navigation to the same URL shortly after it becomes interactive.
        # Starting the command in that gap cancels it with a misleading
        # “page changed” error. Wait until that replacement has settled.
        if self.load_timer:
            self.load_timer.Stop()
        generation = self.client.generation
        self.load_timer = wx.CallLater(1200, self._run_after_settled_load, generation)

    def _run_after_settled_load(self, generation):
        self.load_timer = None
        if self.done or self.started:
            return
        if self.client.generation != generation or not self.client.ready:
            # A first profile load is commonly replaced by another document at
            # the same URL. The original LOADED callback has already been
            # consumed, so poll the newest generation instead of waiting until
            # the overall timeout.
            self.loaded()
            return
        self.started = True
        self.view.RunScriptAsync(SILENT_PAGE)
        self.client.execute('profile_follow', {
            'toggle': self.toggle and not self.confirming, 'profile_url': self.profile_url,
        }, self.observed)

    def observed(self, result):
        if self.done:
            return
        state = result.get('state')
        if result.get('ok') is not True or not isinstance(state, bool):
            self.finish({'ok': False, 'error': result.get('error') or
                         'Não foi possível confirmar o estado de seguimento.'})
            return
        if self.confirming:
            if state != self.expected_state:
                self.finish({'ok': False, 'error':
                    'O TikTok não manteve a alteração. O seguimento não foi confirmado.'})
            else:
                self.finish(result)
            return
        if not self.toggle:
            self.finish(result)
            return
        # A changed button can be optimistic. Keep its document alive to let
        # the request finish, then independently read a newly loaded profile.
        # Never repeat the social click during confirmation.
        self.expected_state = state
        self.confirming = True
        wx.CallLater(2000, self.confirm)

    def confirm(self):
        if self.done:
            return
        # A separate WebView cannot mistake an old LOADED event or the
        # optimistic DOM for the freshly fetched profile. Keep the original
        # document alive until the independent read completes.
        try:
            self.confirmation_worker = BackgroundFollow(
                self.host.GetParent(), self.profile_url, False, self.observed,
            )
            self.confirmation_worker.start()
        except Exception:
            self.failed('Não foi possível abrir a conferência independente do perfil.')

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
        if self.confirmation_worker:
            self.confirmation_worker.close()
        if self.timer:
            self.timer.Stop()
        if self.load_timer:
            self.load_timer.Stop()
        self.client.close()
        # Destroying the document cancels any pending JavaScript or click.
        wx.CallAfter(self.host.Destroy)
