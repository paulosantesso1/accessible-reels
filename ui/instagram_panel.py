from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

import wx

from instagram.search import validate_reel_url
from instagram.client import InstagramBrowserWorker
from tiktok.browser_extension import LocalBrowserWorker
from tiktok.client import WorkerEvent
from tiktok.video_controls import VideoControlError
from ui.comments_dialog import CommentsDialog
from ui.search_dialog import SearchDialog
from ui.shortcuts import set_shortcut

if TYPE_CHECKING:
    from ui.main_frame import MainFrame


class InstagramPanel(wx.Panel):
    """Controles e conexão do Instagram, independentes da sessão TikTok."""

    def __init__(self, parent: wx.Notebook, frame: MainFrame) -> None:
        super().__init__(parent)
        self.frame = frame
        self.worker: LocalBrowserWorker | None = None
        self.comments_dialog: CommentsDialog | None = None
        self.search_dialog: SearchDialog | None = None
        self._pending_events: list[WorkerEvent] = []
        self._disconnecting = False
        sizer = wx.BoxSizer(wx.VERTICAL)
        help_text = wx.StaticText(self, label=(
            "Escolha o Chromium integrado ou sua sessão no Chrome ou Brave com a extensão Accessible Reels."
        ))
        help_text.Wrap(540)
        sizer.Add(help_text, 0, wx.EXPAND | wx.ALL, 12)
        self.open_button = wx.Button(self, label="Conectar &Instagram")
        self.open_button.SetName("Conectar Instagram no Chrome ou Brave")
        set_shortcut(self.open_button)
        sizer.Add(self.open_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.browser_mode = wx.RadioBox(self, label="Navegador do Instagram", choices=[
            "Chromium integrado", "Chrome ou Brave com extensão"], majorDimension=1, style=wx.RA_SPECIFY_COLS)
        self.browser_mode.SetSelection(1)
        sizer.Add(self.browser_mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.minimized = wx.CheckBox(self, label="Abrir Instagram em &janela minimizada")
        self.minimized.SetName("Abrir Instagram em janela minimizada")
        set_shortcut(self.minimized)
        self.minimized.SetValue(False)
        sizer.Add(self.minimized, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.import_button = wx.Button(self, label="&Importar cookies do Instagram")
        self.import_button.SetName("Importar cookies do Instagram")
        set_shortcut(self.import_button)
        sizer.Add(self.import_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.status = wx.StaticText(self, label="Instagram: desconectado.")
        sizer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        for name, label in (("author_field", "Autor do Reel atual"), ("description_field", "Descrição do Reel atual")):
            sizer.Add(wx.StaticText(self, label=label + ":"), 0, wx.LEFT | wx.RIGHT, 12)
            style = wx.TE_READONLY | (wx.TE_MULTILINE if name == "description_field" else 0)
            field = wx.TextCtrl(self, style=style)
            field.SetName(f"Instagram: {label}, somente leitura")
            setattr(self, name, field)
            sizer.Add(field, 1 if name == "description_field" else 0, wx.EXPAND | wx.ALL, 12)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 1)
        for action, label in (
            ("search", "P&esquisar Reels"),
            ("next_video", "Próximo Reel"),
            ("previous_video", "Reel anterior"),
            ("toggle_playback", "Reproduzir ou &pausar"),
            ("read_author", "Ler &autor"),
            ("read_description", "Ler &descrição"),
            ("copy_link", "&Copiar link"),
            ("refresh_info", "Atualizar informações"),
            ("volume_up", "Aumentar volume em 5%"),
            ("volume_down", "Diminuir volume em 5%"),
            ("toggle_mute", "Ativar ou desativar mudo"),
            ("open_comments", "Comentários"),
            ("toggle_like", "Curtir ou descurtir"),
            ("toggle_favorite", "Salvar ou remover dos salvos"),
        ):
            button = wx.Button(self, label=label)
            button.SetName(label.replace("&", ""))
            set_shortcut(button, action=action)
            button.Bind(wx.EVT_BUTTON, lambda _event, selected=action: self.frame._dispatch_shortcut(selected))
            grid.Add(button, 0, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.disconnect_button = wx.Button(self, label="&Fechar conexão do Instagram")
        self.disconnect_button.SetName("Desconectar Instagram sem fechar a aba")
        set_shortcut(self.disconnect_button)
        sizer.Add(self.disconnect_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)
        self.open_button.Bind(wx.EVT_BUTTON, self._connect)
        self.disconnect_button.Bind(wx.EVT_BUTTON, self._disconnect)
        self.browser_mode.Bind(wx.EVT_RADIOBOX, self._on_browser_mode_changed)
        self.import_button.Bind(wx.EVT_BUTTON, self._on_import)
        self._on_browser_mode_changed()

    def _on_browser_mode_changed(self, _event=None) -> None:
        local = self.browser_mode.GetSelection() == 1
        self.minimized.Enable(local and self.worker is None)
        self.import_button.Enable(not local and not self._disconnecting)
        self.open_button.SetLabel("Conectar &Instagram" if local else "Abrir Insta&gram")
        self.open_button.SetName("Conectar Instagram no Chrome ou Brave" if local else "Abrir Instagram no Chromium integrado")
        set_shortcut(self.open_button)
        self.disconnect_button.SetLabel("&Fechar conexão do Instagram" if local else "&Fechar navegador do Instagram")
        self.disconnect_button.SetName("Desconectar Instagram sem fechar a aba" if local else "Fechar navegador do Instagram")
        set_shortcut(self.disconnect_button)

    def _on_import(self, _event) -> None:
        if self.browser_mode.GetSelection() != 0 or self._disconnecting:
            return
        with wx.FileDialog(self, "Importar cookies do Instagram", wildcard="Cookies JSON ou Netscape (*.json;*.txt)|*.json;*.txt|Todos os arquivos (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        self._announce("importando cookies...")
        self._get_worker(open_page=False).import_cookies(path)

    def _active(self) -> bool:
        return self.frame.platform_tabs.GetCurrentPage() is self

    def _announce(self, message: str) -> None:
        self.status.SetLabel(f"Instagram: {message}")
        self.status.SetName(f"Instagram: {message}")
        if self._active() and not self.frame._closing:
            self.frame._announce_accessible(f"Instagram: {message}")

    def _get_worker(self, *, open_page: bool = True) -> LocalBrowserWorker:
        if self.worker is None or not self.worker.is_alive():
            if self.browser_mode.GetSelection() == 1:
                self.worker = LocalBrowserWorker(
                    self._receive, platform="instagram", open_minimized=self.minimized.GetValue()
                )
            else:
                profile = Path(__file__).resolve().parents[1] / "data" / "instagram_profile"
                self.worker = InstagramBrowserWorker(profile, self._receive)
            self.worker.start()
            if open_page:
                self.worker.open_platform()
            self.minimized.Enable(False)
            self.browser_mode.Enable(False)
        return self.worker

    def _connect(self, _event: wx.CommandEvent) -> None:
        if self._disconnecting:
            return
        self._announce("conectando ao Chrome ou Brave..." if self.browser_mode.GetSelection() == 1 else "abrindo Chromium integrado...")
        if self.worker is not None and self.worker.is_alive():
            self.worker.open_platform()
        else:
            self._get_worker()

    def dispatch_shortcut(self, action: str, message: str) -> None:
        if self._disconnecting:
            self._announce("aguarde o encerramento da conexão.")
            return
        self._announce(message)
        if action == "search":
            self._show_search()
        else:
            getattr(self._get_worker(), action)()

    def _disconnect(self, _event: wx.CommandEvent) -> None:
        if self.worker is not None and self.worker.is_alive() and not self._disconnecting:
            self._disconnecting = True
            self.import_button.Enable(False)
            self._close_dialogs()
            self.worker.disconnect()
            self._announce("desconectando...")
        elif self.worker is None:
            self._announce("a conexão já está fechada.")

    def _receive(self, event: WorkerEvent) -> None:
        wx.CallAfter(self._handle_event, event)

    def _handle_event(self, event: WorkerEvent) -> None:
        if not self:
            return
        if event.kind == "stopped":
            self.worker = None
            self._disconnecting = False
            self.browser_mode.Enable(True)
            self._on_browser_mode_changed()
            self._pending_events.clear()
            self._announce(event.message)
            self.frame._finish_close()
            return
        if self.frame._closing or self._disconnecting:
            return
        if event.author is not None:
            self.author_field.SetValue(event.author)
        if event.description is not None:
            self.description_field.SetValue(event.description)
        if not self._active():
            self._pending_events.append(event)
            return
        if event.kind == "comments":
            self._show_comments(event.comments or ())
        elif event.kind == "copy_link":
            self._copy_link(event.link)
            return
        elif event.kind == "search_results" and self.search_dialog is not None:
            self.search_dialog.search_finished()
            self.search_dialog.update_results(event.search_results or ())
        elif event.kind == "error" and self.search_dialog is not None:
            self.search_dialog.search_finished()
        self._announce(event.message)

    def activate(self) -> None:
        pending, self._pending_events = self._pending_events, []
        for event in pending:
            self._handle_event(event)

    def _copy_link(self, value: str | None) -> None:
        try:
            link = validate_reel_url(value)
        except VideoControlError as exc:
            self._announce(str(exc))
            return
        if not wx.TheClipboard.Open():
            self._announce("Não foi possível acessar a área de transferência.")
            return
        copied = False
        try:
            copied = wx.TheClipboard.SetData(wx.TextDataObject(link))
            if copied:
                wx.TheClipboard.Flush()
        except Exception:
            pass
        finally:
            wx.TheClipboard.Close()
        self._announce("Link copiado." if copied else "Não foi possível copiar o link.")

    def _show_search(self) -> None:
        if self.search_dialog is None:
            self.search_dialog = SearchDialog(
                self.frame, self._search, self._open_result, self._search_closed,
                platform="Instagram",
            )
            self.search_dialog.Show()
        self.search_dialog.Raise()
        wx.CallAfter(self.search_dialog.focus_query)

    def _search(self, query: str) -> None:
        self._announce("pesquisando Reels e posts...")
        self._get_worker().search(query)

    def _open_result(self, url: str) -> None:
        self._get_worker().open_search_result(url)

    def _search_closed(self) -> None:
        self.search_dialog = None

    def _show_comments(self, comments: tuple[str, ...]) -> None:
        if self.comments_dialog is None:
            self.comments_dialog = CommentsDialog(
                self.frame, comments, self._post_comment, self._comments_closed,
                platform="Instagram",
            )
            self.comments_dialog.SetTitle("Instagram: comentários do Reel atual")
            self.comments_dialog.Show()
        else:
            self.comments_dialog.update_comments(comments)
        wx.CallAfter(self.comments_dialog.focus_comments)

    def _post_comment(self, text: str) -> None:
        if self.worker is None or not self.worker.is_alive():
            self._announce("reconecte e abra os comentários antes de publicar.")
            return
        self._announce("publicando comentário...")
        self.worker.post_comment(text)

    def _comments_closed(self) -> None:
        self.comments_dialog = None
        if self.worker is not None and self.worker.is_alive():
            self.worker.close_comments()

    def _close_dialogs(self) -> None:
        for dialog in (self.comments_dialog, self.search_dialog):
            if dialog is not None:
                dialog.Close()
