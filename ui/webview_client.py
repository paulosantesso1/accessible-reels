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
from app_logging import get_logger

PLATFORM_URLS = {'TikTok': 'https://www.tiktok.com/', 'Instagram': 'https://www.instagram.com/reels/', 'YouTube': 'https://www.youtube.com/shorts/'}
ACTIONS = {'next', 'previous', 'toggle', 'play', 'seek', 'author', 'description', 'copy_link',
           'refresh_info', 'volume_up', 'volume_down', 'speed_up', 'speed_down', 'toggle_mute', 'comments',
           'close_comments', 'toggle_like', 'toggle_favorite', 'toggle_follow', 'not_interested',
           'profile_follow', 'collect_search_results', 'download_link', 'diagnostics', 'own_profile', 'library_step',
           'toggle_live_chat', 'post_comment'}
# Longest comment any supported network accepts; anything longer is refused before typing.
MAX_COMMENT_LENGTH = 10000
logger = get_logger()
# Commands the app starts by itself right after a page loads. If the platform
# immediately re-navigates to the same page, they are simply run again on the
# new document instead of being reported to the user as a failure.
AUTOMATIC_ACTIONS = {'next', 'previous', 'toggle', 'play', 'seek', 'author', 'description', 'copy_link',
           'refresh_info', 'volume_up', 'volume_down', 'speed_up', 'speed_down', 'toggle_mute', 'comments',
           'close_comments', 'toggle_like', 'toggle_favorite', 'toggle_follow', 'not_interested',
           'profile_follow', 'collect_search_results', 'download_link', 'diagnostics', 'own_profile', 'library_step',
           'toggle_live_chat', 'post_comment'}
# Longest comment any supported network accepts; anything longer is refused before typing.
MAX_COMMENT_LENGTH = 10000
        # A platform can transiently reject a direct video URL immediately
        # after search. Retry that one explicit result navigation once,
        # retaining its callback and result list on every supported network.
        if self._retry_url and not self._retry_attempted:
            self._retry_attempted = True
            url, after_load = self._retry_url, self._retry_after_load
            expected_url, unexpected = self._retry_expected_url, self._retry_unexpected
            retry_generation = self.generation
            logger.warning('WebView load error: platform=%s; retrying result navigation once', self.platform)
            def retry():
                if (self.alive and self.generation == retry_generation
                        and self._retry_url == url and not self.ready):
                    self.generation += 1
                    self.ready = False
                    self._cancel('Navegação repetida após falha temporária.')
                    self.after_load = after_load
                    self._after_load_expected_url = expected_url
                    self._after_load_unexpected = unexpected
                    self.view.LoadURL(url)
            wx.CallLater(1200, retry)
            return

        # Clear failed-navigation state before notifying callers, which can
        # synchronously start a recovery navigation with its own callback.
        pending, self.pending = self.pending, None
        self.after_load = None
        self._after_load_expected_url = None
        self._after_load_unexpected = None
        self._retry_url = None
        self._retry_after_load = None
        self._retry_expected_url = None
        self._retry_unexpected = None
        logger.warning('WebView load error: platform=%s target=%s', self.platform, target)
        if pending:
            pending['timer'].Stop()
            pending['callback']({'ok': False, 'error': 'Falha ao carregar a página. Tente recarregar.'})
            return

        self.on_error('A plataforma recusou carregar esta página. Tente outro resultado ou recarregue.')

    def navigate(self, url, after_load=None, *, expected_url=None, on_unexpected=None):
        if not belongs_to_platform(url, self.platform):
            platform, url = parse_video_link(url)
            if platform != self.platform:
                raise ValueError('Destino não pertence à rede selecionada.')
        # Invalidate old callbacks immediately, before the native navigation event.
        self.generation += 1
        self.ready = False
        self._cancel('Navegação solicitada; o comando anterior foi encerrado.')
        self.target_url = url
        self.after_load = after_load
        self._after_load_expected_url = expected_url
        self._after_load_unexpected = on_unexpected
        self._retry_url = url
        self._retry_after_load = after_load
        self._retry_expected_url = expected_url
        self._retry_unexpected = on_unexpected
        self._retry_attempted = False
        self._last_after_load = None
        self._rearms = 0
        self._stop_abort_watch()
        self.view.LoadURL(url)

    def set_active(self, active):
        self.active = active
        if self.alive and self.ready:
            self.view.RunScriptAsync(f'window.__accessibleSetActive?.({json.dumps(active)});')

    def execute(self, action, argument, callback):
        if self.alive and not self.active and belongs_to_platform(self.view.GetCurrentURL(), self.platform):
            # The list of results is on screen; no video is open yet.
            callback({'ok':False, 'error':'Nenhum vídeo aberto. Abra um da lista com Enter ou use Ctrl+Home para o feed.'})
            return
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
        if action == 'post_comment' and isinstance(argument, dict) and isinstance(argument.get('text'), str):
            # The page may ask to type only this exact text, once.
            self.pending['approved_text'] = argument['text']
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
            logger.warning('WebView command timed out: platform=%s action=%s', self.platform, self.pending['action'])
            self.ready = False
            # Destroy the document's promise chain to prevent a late social action.
            self.view.LoadURL(self.view.GetCurrentURL())
            self._cancel('A rede não respondeu a tempo. A página foi recarregada; confira o estado antes de repetir.')

    def _message(self, event):
        event.Skip()
        if not self.alive or not self.active or not self.pending or not belongs_to_platform(event.GetURL(), self.platform):
            return

        try:
            value = json.loads(event.GetString())
            message_type = value.get('type')
            if message_type not in ('click', 'key') or value.get('token') != self.pending['token']:
                return
            identifier = value.get('id')
            if type(identifier) is not int or identifier in self.pending['clicks']:
                return
            if message_type == 'click':
                x, y = value.get('x'), value.get('y')
                width, height = self.view.GetClientSize()
                if any(type(n) not in (float, int) or not math.isfinite(n) for n in (x, y)) or not (0 <= x < width and 0 <= y < height):
                    return
            else:
                # Only the "next"/"previous" fallback dispatches real key
                # presses, and only these two: keep the channel narrow.
                key = value.get('key')
                if key not in ('ArrowDown', 'ArrowUp') or self.pending['action'] not in ('next', 'previous'):
                    return
            if len(self.pending['clicks']) >= 4:
                return

        except (TypeError, ValueError, AttributeError):
            return

        if self.pending['action'] == 'toggle_follow' and isinstance(value.get('follow_diagnostic'), dict):
            diagnostic = value['follow_diagnostic']
            logger.info(
                'TikTok follow click diagnostic: target=%s hit=%s inside_target=%s path=%s',
                diagnostic.get('target'), diagnostic.get('hit'),
                diagnostic.get('hit_inside_target'), diagnostic.get('path'),
            )
        self.pending['clicks'].add(identifier)
        token, generation = self.pending['token'], self.generation
        def valid():
            return (self.alive and self.active and generation == self.generation and
                    self.pending is not None and self.pending['token'] == token)
        def done(ok, error):
            if valid():
                response = json.dumps({'ok':ok, 'error':error}, ensure_ascii=True)
                self.view.RunScriptAsync(f'window.__accessibleClickDone?.({identifier}, {response});')
        if message_type == 'click':
            webview_native.click(self.view, value.get('x'), value.get('y'), done, valid)
        else:
            webview_native.key_press(self.view, value.get('key'), done, valid)

    def _type_text(self, value):
        """Type the approved comment text, at most once per command."""
        identifier, text = value.get('id'), value.get('text')
        if type(identifier) is not int:
            return

        token, generation = self.pending['token'], self.generation
        def valid():
            return (self.alive and self.active and generation == self.generation and
                    self.pending is not None and self.pending['token'] == token)
        def typed(ok, error):
            if valid():
                response = json.dumps({'ok':ok, 'error':error}, ensure_ascii=True)
                self.view.RunScriptAsync(f'window.__accessibleClickDone?.({identifier}, {response});')
        approved = self.pending.get('approved_text')
        # Refusals are answered at once so the person hears why, instead of a timeout.
        if self.pending.get('typed'):
            logger.warning('Refused repeated page text input: platform=%s', self.platform)
            typed(False, 'O comentário já foi digitado uma vez. Nada mais foi digitado.')
            return

        if (approved is None or not isinstance(text, str) or text != approved or not text
                or len(text) > MAX_COMMENT_LENGTH):
            logger.warning('Refused page text input: platform=%s action=%s', self.platform, self.pending['action'])
            typed(False, 'A página pediu para digitar um texto diferente do confirmado. Nada foi digitado.')
            return

        self.pending['typed'] = True
        webview_native.insert_text(self.view, text, typed, valid)

    def close(self):
        self.alive = False
        self.ready = False
        self._stop_abort_watch()
        self.after_load = None
        self._after_load_expected_url = None
        self._after_load_unexpected = None
        if self.pending:
            self.pending['timer'].Stop()
            self.pending = None
