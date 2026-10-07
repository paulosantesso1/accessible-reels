"""Accessible background downloads for the active embedded video."""
import os
import threading
import re
import tempfile
import time
from pathlib import Path

import wx

from audio_extract import AudioExtractError, extract_m4a
from app_logging import get_logger, sanitize
from video_download import MEDIA_SUFFIXES, download_video, load_download_folder, save_download_folder
from ui.browser_download import BrowserDownload


logger = get_logger()
LIST_DOWNLOAD_PAUSE = 1.5  # seconds between videos, to avoid looking like a flood of requests


def already_downloaded(folder, url):
    """True when a media file named after this video's id is already in the folder."""
    identifier = str(url).rstrip('/').split('/')[-1].split('?')[0]
    if not identifier:
        return False
    try:
        return any(path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES and f'[{identifier}]' in path.name
                   for path in Path(folder).iterdir())
    except OSError:
        return False


class DownloadControlsMixin:
    def choose_download_file(self, name, result, audio=False):
        description = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', str(result.get('description') or '')).strip(' .')
        suggestion = f'{name} - {description[:100]}' if description else f'{name} - {"áudio" if audio else "vídeo"}'
        with wx.FileDialog(self, 'Salvar áudio como' if audio else 'Salvar vídeo como',
                           defaultDir=str(self._download_folder or ''),
                           defaultFile=suggestion + ('.m4a' if audio else '.mp4'),
                           wildcard=('Áudio M4A, Opus ou WebM (*.m4a;*.opus;*.webm)|*.m4a;*.opus;*.webm' if audio else
                                     'Vídeos MP4 ou WebM (*.mp4;*.webm)|*.mp4;*.webm'),
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            target = Path(dialog.GetPath())
        try:
            self._download_folder = save_download_folder(target.parent)
        except OSError:
            # The chosen destination still works even if preferences cannot be saved.
            self._download_folder = target.parent
        return target

    def initialize_downloads(self):
        self._download_busy = False
        self._list_download = None
        self._download_folder = load_download_folder()

    def choose_download_folder(self, event=None):
        with wx.DirDialog(self, 'Escolha onde salvar o vídeo',
                          defaultPath=str(self._download_folder or '')) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return False
            try:
                self._download_folder = save_download_folder(dialog.GetPath())
            except OSError:
                self.status('Não foi possível salvar essa pasta. Escolha outra pasta de downloads.')
                return False
        self.status(f'Pasta de downloads: {self._download_folder}')
        return True

    def open_download_folder(self, event=None):
        if not self._download_folder and not self.choose_download_folder():
            return
        try:
            os.startfile(self._download_folder)
        except OSError:
            self.status('Não foi possível abrir a pasta de downloads.')

    def start_list_download(self, event=None):
        """Download every video of the list on screen, one at a time, into a chosen folder."""
        running = self._list_download
        if running:
            with wx.MessageDialog(self, 'Cancelar o download em lote? O vídeo atual termina antes de parar.',
                                  'Download em lote', wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) as dialog:
                if dialog.ShowModal() == wx.ID_YES:
                    running['cancel'].set()
                    self.status('Cancelando o download em lote...')
            return
        if getattr(self, '_library_worker', None):
            self.status('A lista ainda está carregando em segundo plano. Aguarde o aviso de lista completa '
                        'para baixar todos os vídeos.')
            return
        items = tuple(self._results)
        if not items or not self.current():
            self.status('Não há uma lista de vídeos para baixar. Faça uma pesquisa ou abra seus curtidos (Alt+Shift+L).')
            return
        if self._download_busy:
            self.status('Já existe um download em andamento. Aguarde a conclusão.')
            return
        name = self._active_name
        with wx.DirDialog(self, f'Escolha a pasta para salvar os {len(items)} vídeos da lista',
                          defaultPath=str(self._download_folder or '')) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                self.status('Download em lote cancelado.')
                return
            folder = Path(dialog.GetPath())
        try:
            self._download_folder = save_download_folder(folder)
        except OSError:
            self._download_folder = folder
        self._download_busy = True
        job = {'cancel': threading.Event()}
        self._list_download = job
        self.status(f'Baixando {len(items)} vídeos para {folder}. Use o mesmo atalho para cancelar.')
        threading.Thread(target=self._list_download_worker, args=(name, items, folder, job), daemon=True).start()

    def _list_download_worker(self, name, items, folder, job):
        done = skipped = failed = 0
        total = len(items)
        for index, item in enumerate(items, 1):
            if job['cancel'].is_set() or self._closing_app:
                break
            if index == 1 or index % 5 == 0:
                wx.CallAfter(self._list_download_announce, f'Baixando vídeo {index} de {total}.')
            else:
                self._download_notify(f'Baixando vídeo {index} de {total}...')
            if already_downloaded(folder, item.url):
                skipped += 1
                continue
            try:
                download_video(item.url, name, folder, lambda message: None)
                done += 1
            except Exception as exception:
                failed += 1
                logger.warning('List download item failed: %s', sanitize(str(exception))[:200])
            if index < total:
                job['cancel'].wait(LIST_DOWNLOAD_PAUSE)
        wx.CallAfter(self._list_download_finished, job, done, skipped, failed, total, folder)

    def _list_download_announce(self, message):
        if self._list_download:
            self.status(message)

    def _list_download_finished(self, job, done, skipped, failed, total, folder):
        self._list_download = None
        self._download_busy = False
        if self._closing_app:
            return
        parts = [f'{done} baixados']
        if skipped:
            parts.append(f'{skipped} já existiam')
        if failed:
            parts.append(f'{failed} com falha')
        cancelled = job['cancel'].is_set()
        self.status(('Download em lote cancelado: ' if cancelled else 'Download em lote concluído: ')
                    + ', '.join(parts) + f' de {total}. Pasta: {folder}.')

    def start_audio_download(self, event=None):
        self.start_video_download(audio=True)

    def start_video_download(self, event=None, audio=False):
        if self._download_busy:
            self.status('Já existe um download em andamento. Aguarde a conclusão.')
            return
        name = self._active_name
        if not self.current():
            self.status('Abra uma plataforma e selecione um vídeo para baixar.')
            return
        client = self.clients[name]
        if client.pending:
            self.status('Aguarde a operação atual e tente o download novamente.')
            return
        self._download_busy = True
        self.status('Identificando o vídeo para baixar o áudio...' if audio else 'Identificando o vídeo para download...')
        if self.activities.GetSelection() == 2:
            index = self.results_list.GetSelection()
            if 0 <= index < len(self._results):
                self._download_resolved(name, {'ok': True, 'link': self._results[index].url}, audio)
                return
        client.execute('download_link', None, lambda result: self._download_resolved(name, result, audio))

    def _download_resolved(self, name, result, audio=False):
        if self._closing_app:
            return
        if not result.get('ok'):
            self._download_busy = False
            self.status(result.get('error') or 'Não foi possível identificar o vídeo ativo.')
            return
        target = self.choose_download_file(name, result, audio)
        if target is None:
            self._download_busy = False
            self.status('Download cancelado.')
            return
        self.status('Iniciando download do áudio...' if audio else 'Iniciando download do vídeo...')
        result = {**result, '_save_path': target}
        folder = target.parent
        # A YouTube page stream may hold video only, so audio always goes through the downloader.
        if result.get('media_url') and not (audio and name == 'YouTube'):
            def completed(path, error):
                if self._closing_app:
                    if path:
                        try:
                            Path(path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    return
                if path and audio:
                    self._extract_audio_then_finalize(path, target, name, result, folder)
                elif path:
                    self._finalize_download(path, target)
                else:
                    self.status('A transferência pela sessão falhou. Tentando o downloader alternativo...')
                    self._start_download_worker(name, result, folder, audio)
            self._browser_download = BrowserDownload(
                self.clients[name], result['media_url'], folder,
                self._download_progress, completed
            )
            self._browser_download.start()
            return
        self._start_download_worker(name, result, folder, audio)

    def _extract_audio_then_finalize(self, video_path, target, name, result, folder):
        """Copy the audio track out of a downloaded video file, off the interface thread."""
        def work():
            audio_path = Path(video_path).with_suffix('.m4a')
            try:
                self._download_notify('Extraindo o áudio...')
                extract_m4a(video_path, audio_path)
            except AudioExtractError:
                Path(video_path).unlink(missing_ok=True)
                if not self._closing_app:
                    wx.CallAfter(self.status, 'Não foi possível extrair o áudio. Tentando o downloader alternativo...')
                    wx.CallAfter(self._start_download_worker, name, result, folder, True)
                return
            Path(video_path).unlink(missing_ok=True)
            if self._closing_app:
                audio_path.unlink(missing_ok=True)
                return
            wx.CallAfter(self._finalize_download, audio_path, target)
        threading.Thread(target=work, daemon=True).start()

    def _start_download_worker(self, name, result, folder, audio=False):
        threading.Thread(target=self._download_worker,
                         args=(name, result.get('link'), result.get('media_url'), folder,
                               result['_save_path'], audio),
                         daemon=True).start()

    def _download_worker(self, name, link, media, folder, destination, audio=False):
        temporary = None
        try:
            # Preserve an existing file until the new download has completed.
            temporary = tempfile.TemporaryDirectory(prefix='reels-', dir=folder)
            downloaded = download_video(
                link, name, temporary.name, self._download_notify, direct_url=media, audio=audio
            )
        except Exception as exception:
            from app_logging import sanitize
            error = sanitize(str(exception))[:500]
            if temporary:
                temporary.cleanup()
            if not self._closing_app:
                wx.CallAfter(self._download_finished, None, error)
            return
        if self._closing_app:
            temporary.cleanup()
            return
        wx.CallAfter(
            DownloadControlsMixin._finalize_download,
            self, downloaded, destination, temporary.cleanup,
        )

    def _finalize_download(self, downloaded, destination, cleanup=None):
        path, error = None, None
        downloaded = Path(downloaded)
        destination = Path(destination)
        target = destination.with_suffix(downloaded.suffix)
        try:
            # FileDialog confirmed only the exact name selected by the user.
            # A different container needs its own confirmation before replacing
            # a same-named file with the actual extension.
            if target != destination and target.exists():
                with wx.MessageDialog(
                    self,
                    f'O arquivo "{target.name}" já existe. Deseja substituí-lo?',
                    'Confirmar substituição',
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                ) as dialog:
                    if dialog.ShowModal() != wx.ID_YES:
                        error = 'Download cancelado; o arquivo existente foi preservado.'
                        return
            downloaded.replace(target)
            path = target
        except OSError as exception:
            from app_logging import sanitize
            error = sanitize(str(exception))[:500]
        finally:
            if cleanup:
                try:
                    cleanup()
                except OSError:
                    pass
            elif downloaded.exists():
                try:
                    downloaded.unlink()
                except OSError:
                    pass
            self._download_finished(path, error)

    def _download_notify(self, message):
        if not self._closing_app:
            wx.CallAfter(self._download_progress, message)

    def _download_progress(self, message):
        if not self._closing_app:
            # Percentages remain visible without interrupting screen-reader speech.
            self.SetStatusText(message)

    def _download_finished(self, path, error):
        self._download_busy = False
        if not self._closing_app:
            self.status(error or f'Download concluído: {path.name}. Salvo em {path.parent}.')
