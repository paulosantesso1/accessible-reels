"""Accessible background downloads for the active embedded video."""
import os
import threading
import re
import tempfile
from pathlib import Path

import wx

from video_download import download_video, load_download_folder, save_download_folder
from ui.browser_download import BrowserDownload


class DownloadControlsMixin:
    def choose_download_file(self, name, result):
        description = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', str(result.get('description') or '')).strip(' .')
        suggestion = f'{name} - {description[:100]}' if description else f'{name} - vídeo'
        with wx.FileDialog(self, 'Salvar vídeo como', defaultDir=str(self._download_folder or ''),
                           defaultFile=suggestion + '.mp4', wildcard='Vídeo MP4 (*.mp4)|*.mp4',
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

    def start_video_download(self, event=None):
        if self._download_busy:
            self.status('Já existe um download em andamento. Aguarde a conclusão.')
            return
        name = self._active_name
        if not self.current():
            self.status('Abra uma plataforma e selecione um vídeo para baixar.')
            return
        client = self.clients[name]
        if client.pending:
            self.status('Aguarde a operação atual e pressione Ctrl+B novamente.')
            return
        self._download_busy = True
        self.status('Identificando o vídeo para download...')
        if self.activities.GetSelection() == 2:
            index = self.results_list.GetSelection()
            if 0 <= index < len(self._results):
                self._download_resolved(name, {'ok': True, 'link': self._results[index].url})
                return
        client.execute('download_link', None, lambda result: self._download_resolved(name, result))

    def _download_resolved(self, name, result):
        if self._closing_app:
            return
        if not result.get('ok'):
            self._download_busy = False
            self.status(result.get('error') or 'Não foi possível identificar o vídeo ativo.')
            return
        target = self.choose_download_file(name, result)
        if target is None:
            self._download_busy = False
            self.status('Download cancelado.')
            return
        self.status('Iniciando download do vídeo...')
        result = {**result, '_save_path': target}
        folder = target.parent
        if result.get('media_url'):
            def completed(path, error):
                if self._closing_app:
                    return
                if path:
                    self._download_finished(path, None)
                else:
                    self.status('A transferência pela sessão falhou. Tentando o downloader alternativo...')
                    self._start_download_worker(name, result, folder)
            self._browser_download = BrowserDownload(self.clients[name], result['media_url'], folder,
                                                     self._download_progress, completed, destination=target)
            self._browser_download.start()
            return
        self._start_download_worker(name, result, folder)

    def _start_download_worker(self, name, result, folder):
        threading.Thread(target=self._download_worker,
                         args=(name, result.get('link'), result.get('media_url'), folder, result['_save_path']),
                         daemon=True).start()

    def _download_worker(self, name, link, media, folder, destination):
        path, error = None, None
        try:
            # Preserve an existing file until the new download has completed.
            with tempfile.TemporaryDirectory(prefix='reels-', dir=folder) as temporary:
                downloaded = download_video(link, name, temporary, self._download_notify, direct_url=media)
                downloaded.replace(destination)
                path = Path(destination)
        except Exception as exception:
            from app_logging import sanitize
            error = sanitize(str(exception))[:500]
        if not self._closing_app:
            wx.CallAfter(self._download_finished, path, error)

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
