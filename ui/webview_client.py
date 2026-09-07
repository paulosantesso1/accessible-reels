"""Asynchronous commands scoped to one embedded page and one navigation."""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import wx
import wx.html2 as html2

from ui import webview_native
from ui.video_link import parse_video_link

PLATFORM_URLS = {'TikTok': 'https://www.tiktok.com/', 'Instagram': 'https://www.instagram.com/reels/'}
ACTIONS = {'next', 'previous', 'toggle', 'play', 'seek', 'author', 'description', 'copy_link',
           'refresh_info', 'volume_up', 'volume_down', 'speed_up', 'speed_down', 'toggle_mute', 'comments',
           'close_comments', 'toggle_like', 'toggle_favorite',
           'collect_search_results', 'diagnostics'}


def belongs_to_platform(url, platform):
    try:
        parsed = urlsplit(url)
        domain = 'tiktok.com' if platform == 'TikTok' else 'instagram.com'
        return (parsed.scheme == 'https' and parsed.hostname in (domain, 'www.' + domain)
                and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except ValueError:
        return False


def scripts_for(platform):
    root = Path(__file__).with_name('web_scripts')
    domain = 'tiktok.com' if platform == 'TikTok' else 'instagram.com'
    source = '\n'.join((root / name).read_text(encoding='utf-8') for name in
                       ('transport.js', 'audio_guard.js', platform.lower() + '.js'))
    return f"if (window === top && ['{domain}', 'www.{domain}'].includes(location.hostname)) {{\n{source}\n}}"


class WebViewClient:
    def __init__(self, view, platform, on_loaded, on_error):
        self.view, self.platform = view, platform
        self.on_loaded, self.on_error = on_loaded, on_error
        self.generation = 0
        self.pending = None
        self.alive = True
        self.ready = False
        self.active = True
        self.target_url = PLATFORM_URLS[platform]
        self.after_load = None
        view.Bind(wx.PyEventBinder(html2.wxEVT_WEBVIEW_CREATED, 1), self._created)
        view.Bind(html2.EVT_WEBVIEW_NAVIGATING, self._navigating)
        view.Bind(html2.EVT_WEBVIEW_LOADED, self._loaded)
        view.Bind(html2.EVT_WEBVIEW_ERROR, self._error)
        view.Bind(html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self._message)

    def initialize(self):
        """Install scripts after Create; some wx builds emit CREATED before Python binds."""
        if self.ready or getattr(self, '_initialized', False):
            return
        if not self.view.AddScriptMessageHandler('reelsHost') or not self.view.AddUserScript(scripts_for(self.platform)):
            self.on_error('Não foi possível preparar os controles da página.')
            return
        self._initialized = True
        self.view.LoadURL(self.target_url)

    def _created(self, event):
        self.initialize()

    def _navigating(self, event):
        # Iframes must not invalidate the command running in the top document.
        if not event.IsTargetMainFrame():
            event.Skip()
            return
        self.generation += 1
        self.ready = False
        self._cancel('A página mudou. Confira o vídeo antes de repetir a ação.')
        event.Skip()

    def _loaded(self, event):
        # wxWebViewEdge does not populate IsTargetMainFrame on LOADED events.
        # The evaluation below always checks the current top document.
        if not self.alive or not belongs_to_platform(self.view.GetCurrentURL(), self.platform):
            return
        generation = self.generation
        def checked(value, error):
            if not self.alive or generation != self.generation:
                return
            was_ready = self.ready
            self.ready = value is True and not error
            if self.ready:
                self.set_active(self.active)
                if not was_ready:
                    self.on_loaded()
                if self.after_load:
                    callback, self.after_load = self.after_load, None
                    wx.CallAfter(lambda: callback() if self.alive and generation == self.generation else None)
        webview_native.evaluate(self.view, self._prepare_script() +
                                "Boolean(window.__accessibleIsReady?.())", checked)

    def _prepare_script(self):
        # Login redirects can replace the document. Repair a missing bridge in
        # the current top document, without relying on a cached readiness flag.
        return ("if (!window.__accessibleIsReady?.()) {\n" + scripts_for(self.platform) +
                "\n}\n")

    def _error(self, event):
        if event.GetTarget() not in ('', '_self', '_top'):
            return
        self._cancel('Falha ao carregar a página. Tente recarregar.')
        self.on_error('Falha ao carregar a página. Tente recarregar.')

    def navigate(self, url, after_load=None):
        if not belongs_to_platform(url, self.platform):
            platform, url = parse_video_link(url)
            if platform != self.platform:
                raise ValueError('Destino não pertence à rede selecionada.')
        self.after_load = after_load
        self.view.LoadURL(url)

    def set_active(self, active):
        self.active = active
        if self.alive and self.ready:
            self.view.RunScriptAsync(f'window.__accessibleSetActive?.({json.dumps(active)});')

    def execute(self, action, argument, callback):
        if not self.alive or not self.active or not belongs_to_platform(self.view.GetCurrentURL(), self.platform):
            callback({'ok':False, 'error':'Abra a rede selecionada e aguarde a página carregar.'})
            return
        if self.pending:
            callback({'ok':False, 'ignored':True})
            return
        if action not in ACTIONS:
            raise ValueError('Comando desconhecido')
        token = uuid.uuid4().hex
        generation = self.generation
        self.pending = {'token':token, 'callback':callback, 'clicks':set(), 'action':action}
        self.pending['timer'] = wx.CallLater(20000, self._timeout, token)
        arguments = json.dumps([action, argument, token, self.platform.lower()], ensure_ascii=True)
        def completed(value, error):
            if not self.alive or generation != self.generation or not self.pending or self.pending['token'] != token:
                return
            self.ready = isinstance(value, dict) and not error
            self._finish(value if isinstance(value, dict) and not error else
                         {'ok':False, 'error':error or 'Resposta inválida da página.'})
        expression = (self._prepare_script() +
                      f'window.__accessibleRun(...{arguments})')
        webview_native.evaluate(self.view, expression, completed)

    def _finish(self, value):
        pending, self.pending = self.pending, None
        if pending:
            pending['timer'].Stop()
            pending['callback'](value)

    def _cancel(self, message):
        self._finish({'ok':False, 'error':message})

    def _timeout(self, token):
        if self.pending and self.pending['token'] == token:
            self.ready = False
            # Destroy the document's promise chain to prevent a late social action.
            self.view.LoadURL(self.view.GetCurrentURL())
            self._cancel('A rede não respondeu a tempo. A página foi recarregada; confira o estado antes de repetir.')

    def _message(self, event):
        if not self.alive or not self.active or not self.pending or not belongs_to_platform(event.GetURL(), self.platform):
            return
        try:
            value = json.loads(event.GetString())
            if value.get('type') != 'click' or value.get('token') != self.pending['token']:
                return
            identifier, x, y = value.get('id'), value.get('x'), value.get('y')
            if type(identifier) is not int or identifier in self.pending['clicks']:
                return
            width, height = self.view.GetClientSize()
            if any(type(n) not in (float, int) or not math.isfinite(n) for n in (x, y)) or not (0 <= x < width and 0 <= y < height):
                return
            if len(self.pending['clicks']) >= 4:
                return
        except (TypeError, ValueError, AttributeError):
            return
        self.pending['clicks'].add(identifier)
        token, generation = self.pending['token'], self.generation
        def valid():
            return (self.alive and self.active and generation == self.generation and
                    self.pending is not None and self.pending['token'] == token)
        def clicked(ok, error):
            if valid():
                response = json.dumps({'ok':ok, 'error':error}, ensure_ascii=True)
                self.view.RunScriptAsync(f'window.__accessibleClickDone?.({identifier}, {response});')
        webview_native.click(self.view, x, y, clicked, valid)

    def close(self):
        self.alive = False
        self.ready = False
        self.after_load = None
        if self.pending:
            self.pending['timer'].Stop()
            self.pending = None
