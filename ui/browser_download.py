"""Stream media through the existing WebView session, without yt-dlp."""
import base64
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import wx

from ui.webview_native import evaluate
from video_download import media_url
from app_logging import get_logger

# Assinaturas de container de vídeo conhecidas.
# O browser_download atua como contingência e pode receber WebM (YouTube),
# MP4 com ftyp, ou MP4 onde moov precede ftyp (Instagram/TikTok).
_MP4_FTYP = b'ftyp'                   # bytes 4-8 de MP4 padrão
_WEBM_EBML = b'\x1a\x45\xdf\xa3'     # início de WebM/MKV (EBML)
_MP4_MOOV  = b'moov'                  # MP4 sem ftyp inicial
_RIFF      = b'RIFF'                  # AVI legacy


def _detect_media_signature(path: Path) -> str | None:
    """Retorna a extensão recomendada para o arquivo ou None se não reconhecido."""
    try:
        with path.open('rb') as f:
            header = f.read(16)
        # WebM/MKV: começa com sequência EBML
        if header[:4] == _WEBM_EBML:
            return '.webm'
        # MP4 padrão: bytes 4-8 == 'ftyp'
        if len(header) >= 8 and header[4:8] == _MP4_FTYP:
            return '.mp4'
        # MP4 sem ftyp: bytes 4-8 == 'moov' (moov-first layout)
        if len(header) >= 8 and header[4:8] == _MP4_MOOV:
            return '.mp4'
        # AVI
        if header[:4] == _RIFF:
            return '.avi'
    except OSError:
        pass
    return None


class BrowserDownload:
    def __init__(self, client, url, folder, progress, complete, *, destination=None):
        self.client, self.url = client, url
        self.folder, self.progress, self.complete = Path(folder), progress, complete
        self.destination = Path(destination) if destination is not None else None
        self.generation = client.generation
        self.key = '__reelsDownload_' + uuid.uuid4().hex
        self.file = self.partial = self.timer = None
        self.done, self.size, self.last_percent = False, 0, -10

    def start(self):
        get_logger().info('Browser download source: platform=%s host=%s accepted=%s',
                          self.client.platform, urlsplit(self.url).hostname, bool(media_url(self.url, self.client.platform)))
        if not media_url(self.url, self.client.platform):
            self.finish(None, 'Endereço de mídia indisponível.')
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(prefix='reels-', suffix='.part', dir=self.folder)
            self.partial = Path(path)
            self.file = os.fdopen(fd, 'wb')
        except OSError:
            self.finish(None, 'Não foi possível criar o arquivo de download.')
            return
        self.run(f'''(async () => {{
          const controller = new AbortController();
          window.{self.key} = {{controller}};
          const response = await fetch({json.dumps(self.url)}, {{credentials: 'include', signal: controller.signal}});
          if (response.status !== 200 || !response.body) throw new Error('Resposta de mídia inválida');
          const type = response.headers.get('content-type') || '';
          if (/text|json|mpegurl/i.test(type)) throw new Error('A resposta não é um arquivo de vídeo');
          const state = window.{self.key};
          state.reader = response.body.getReader();
          return {{ready: true, total: Number(response.headers.get('content-length')) || 0}};
        }})()''', self.started)

    def run(self, script, callback):
        if self.done:
            return
        if not self.client.alive or self.client.generation != self.generation:
            self.finish(None, 'A página mudou durante o download.')
            return
        self.timer = wx.CallLater(30000, self.finish, None, 'O download pela sessão demorou a responder.')
        def received(value, error):
            if self.done:
                return
            self.timer.Stop()
            if not self.client.alive or self.client.generation != self.generation:
                self.finish(None, 'A página mudou durante o download.')
            elif error:
                self.finish(None, 'A sessão não conseguiu transferir o arquivo do vídeo.')
            else:
                callback(value)
        evaluate(self.client.view, script, received)

    def started(self, value):
        self.total = value.get('total', 0) if isinstance(value, dict) else 0
        self.next()

    def next(self):
        self.run(f'''(async () => {{
          const state = window.{self.key};
          const value = await state.reader.read();
          if (value.done) return {{done: true}};
          let binary = '';
          for (let i = 0; i < value.value.length; i += 8192)
            binary += String.fromCharCode(...value.value.subarray(i, i + 8192));
          return {{data: btoa(binary)}};
        }})()''', self.chunk)

    def chunk(self, value):
        try:
            if not isinstance(value, dict):
                raise ValueError()
            if value.get('done'):
                # BUG-07: Aceita o arquivo quando o servidor não enviou
                # Content-Length (self.total == 0 = tamanho desconhecido).
                # Só rejeita se Content-Length foi fornecido E o tamanho
                # baixado diferir em mais de 1 KB (tolerância para compressão).
                size_ok = (
                    not self.size == 0  # arquivo vazio é sempre inválido
                    and (
                        self.total == 0  # tamanho desconhecido: confiar no ReadableStream
                        or abs(self.total - self.size) <= 1024
                    )
                )
                if not size_ok:
                    raise ValueError('Tamanho do arquivo inconsistente.')
                self.file.close()
                self.file = None
                # BUG-06: Detectar formato real em vez de exigir apenas ftyp.
                ext = _detect_media_signature(self.partial)
                if ext is None:
                    raise ValueError('Assinatura de container de mídia não reconhecida.')
                # Usa extensão detectada; fallback para .mp4 se destination já definido.
                if self.destination is not None:
                    target = self.destination
                else:
                    target = self.folder / (self.partial.stem + ext)
                self.partial.replace(target)
                self.partial = None
                self.finish(target, None)
                return
            data = base64.b64decode(value['data'], validate=True)
            self.size += len(data)
            if self.size > 512 * 1024 * 1024:
                raise ValueError()
            self.file.write(data)
            percent = int(self.size * 100 / self.total) if self.total else 0
            if percent >= self.last_percent + 10:
                self.last_percent = percent
                self.progress(f'Baixando pela sessão: {min(percent, 99)}%.' if self.total else 'Recebendo vídeo pela sessão...')
            self.next()
        except (OSError, ValueError, KeyError, TypeError):
            self.finish(None, 'O arquivo recebido está incompleto ou não é um MP4 válido.')

    def finish(self, path, error):
        if self.done:
            return
        self.done = True
        get_logger().info('Browser download finished: success=%s bytes=%s reason=%s', bool(path), self.size, error)
        if self.timer:
            self.timer.Stop()
        if self.file:
            self.file.close()
        if self.partial:
            try:
                self.partial.unlink(missing_ok=True)
            except OSError:
                pass
        if self.client.alive and self.client.generation == self.generation:
            evaluate(self.client.view, f'window.{self.key}?.controller.abort(); delete window.{self.key};', lambda *_: None)
        self.complete(path, error)
