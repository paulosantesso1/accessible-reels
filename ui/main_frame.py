from __future__ import annotations

from pathlib import Path
from typing import Callable

import wx

from tiktok.client import BrowserWorker, WorkerEvent
from ui.comments_dialog import CommentsDialog
from ui.nvda_announcer import (
    raise_uia_notification,
    speak_with_accessible_output,
    speak_with_nvda,
)


ACCELERATOR_SPECS = (
    ("next_video", wx.ACCEL_ALT, wx.WXK_DOWN),
    ("previous_video", wx.ACCEL_ALT, wx.WXK_UP),
    ("toggle_playback", wx.ACCEL_ALT, ord("P")),
    ("read_author", wx.ACCEL_ALT, ord("A")),
    ("read_description", wx.ACCEL_ALT, ord("D")),
    ("copy_link", wx.ACCEL_ALT, ord("C")),
    ("refresh_info", wx.ACCEL_NORMAL, wx.WXK_F5),
    ("exit", wx.ACCEL_ALT, ord("S")),
    ("volume_up", wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_UP),
    ("volume_down", wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_DOWN),
    ("toggle_mute", wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("M")),
    ("diagnostics", wx.ACCEL_ALT, wx.WXK_F12),
    ("open_comments", wx.ACCEL_NORMAL, ord("C")),
    ("toggle_like", wx.ACCEL_NORMAL, ord("L")),
    ("toggle_favorite", wx.ACCEL_NORMAL, ord("F")),
)


SHORTCUT_MESSAGES = {
    "next_video": "Comando recebido: próximo vídeo.",
    "previous_video": "Comando recebido: vídeo anterior.",
    "toggle_playback": "Comando recebido: pausar ou reproduzir.",
    "read_author": "Comando recebido: ler autor.",
    "read_description": "Comando recebido: ler descrição.",
    "copy_link": "Comando recebido: copiar link.",
    "refresh_info": "Comando recebido: atualizar informações.",
    "exit": "Comando recebido: sair.",
    "volume_up": "Comando recebido: aumentar volume.",
    "volume_down": "Comando recebido: diminuir volume.",
    "toggle_mute": "Comando recebido: alternar mudo.",
    "diagnostics": "Comando recebido: diagnóstico.",
    "open_comments": "Carregando comentários...",
    "toggle_like": "Alterando curtida...",
    "toggle_favorite": "Alterando favorito...",
}


class MainFrame(wx.Frame):
    """Janela principal, composta apenas por controles nativos acessíveis."""

    def __init__(self) -> None:
        super().__init__(None, title="Accessible Reels", size=(620, 800))
        self._worker: BrowserWorker | None = None
        self._closing = False
        self._comments_dialog: CommentsDialog | None = None

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label="Accessible Reels")
        heading.SetName("Título: Accessible Reels")
        font = heading.GetFont()
        font.MakeBold()
        font.SetPointSize(font.GetPointSize() + 3)
        heading.SetFont(font)
        main_sizer.Add(heading, 0, wx.ALL, 12)

        self.status = wx.StaticText(panel, label="Status: pronto.")
        self.status.SetName("Status do aplicativo")
        main_sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.open_button = self._button(panel, "Abrir &TikTok", "Abrir TikTok")
        self.import_button = self._button(
            panel, "&Importar cookies", "Importar cookies de um arquivo JSON ou TXT"
        )
        main_sizer.Add(self.open_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        main_sizer.Add(self.import_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.show_browser_checkbox = wx.CheckBox(
            panel, label="Mostrar &janela do navegador"
        )
        self.show_browser_checkbox.SetName("Mostrar janela do navegador")
        self.show_browser_checkbox.SetValue(True)
        self.show_browser_checkbox.Enable(False)
        self.show_browser_checkbox.SetToolTip(
            "Ocultamento temporariamente desativado para preservar a reprodução"
        )
        main_sizer.Add(
            self.show_browser_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )

        author_label = wx.StaticText(panel, label="Autor do vídeo atual:")
        author_label.SetName("Rótulo do autor do vídeo atual")
        main_sizer.Add(author_label, 0, wx.LEFT | wx.RIGHT, 12)
        self.author_field = wx.TextCtrl(panel, style=wx.TE_READONLY)
        self.author_field.SetName("Autor do vídeo atual, somente leitura")
        self.author_field.SetHint("Autor ainda não atualizado")
        main_sizer.Add(self.author_field, 0, wx.EXPAND | wx.ALL, 12)

        description_label = wx.StaticText(panel, label="Descrição do vídeo atual:")
        description_label.SetName("Rótulo da descrição do vídeo atual")
        main_sizer.Add(description_label, 0, wx.LEFT | wx.RIGHT, 12)
        self.description_field = wx.TextCtrl(
            panel, style=wx.TE_READONLY | wx.TE_MULTILINE
        )
        self.description_field.SetName("Descrição do vídeo atual, somente leitura")
        self.description_field.SetHint("Descrição ainda não atualizada")
        main_sizer.Add(
            self.description_field, 1, wx.EXPAND | wx.ALL, 12
        )

        self.next_button = self._button(panel, "Próximo vídeo", "Próximo vídeo")
        self.previous_button = self._button(panel, "Vídeo anterior", "Vídeo anterior")
        self.toggle_button = self._button(
            panel, "Reproduzir ou &pausar", "Reproduzir ou pausar o vídeo atual"
        )
        self.author_button = self._button(panel, "Ler &autor", "Ler autor do vídeo atual")
        self.description_button = self._button(
            panel, "Ler &descrição", "Ler descrição do vídeo atual"
        )
        self.copy_button = self._button(panel, "&Copiar link", "Copiar link do vídeo atual")
        self.refresh_button = self._button(
            panel, "Atualizar informações", "Atualizar informações do vídeo atual"
        )
        self.volume_up_button = self._button(
            panel, "Aumentar volume", "Aumentar volume em dez por cento"
        )
        self.volume_down_button = self._button(
            panel, "Diminuir volume", "Diminuir volume em dez por cento"
        )
        self.mute_button = self._button(
            panel, "Ativar ou desativar mudo", "Ativar ou desativar mudo"
        )
        self.comments_button = self._button(
            panel, "&Comentários", "Abrir comentários do vídeo atual, atalho C"
        )
        self.like_button = self._button(
            panel, "Curtir ou descurtir", "Curtir ou descurtir o vídeo atual, atalho L"
        )
        self.favorite_button = self._button(
            panel,
            "Favoritar ou desfavoritar",
            "Favoritar ou desfavoritar o vídeo atual, atalho F",
        )

        video_sizer = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=8)
        video_sizer.AddGrowableCol(0, 1)
        video_sizer.AddGrowableCol(1, 1)
        for button in (
            self.next_button,
            self.previous_button,
            self.toggle_button,
            self.author_button,
            self.description_button,
            self.copy_button,
            self.refresh_button,
            self.volume_up_button,
            self.volume_down_button,
            self.mute_button,
            self.comments_button,
            self.like_button,
            self.favorite_button,
        ):
            video_sizer.Add(button, 0, wx.EXPAND)
        main_sizer.Add(video_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.close_browser_button = self._button(
            panel, "&Fechar navegador", "Fechar navegador"
        )
        self.exit_button = self._button(
            panel, "&Sair", "Sair do Accessible Reels"
        )
        main_sizer.Add(
            self.close_browser_button,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        main_sizer.Add(
            self.exit_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12
        )
        panel.SetSizer(main_sizer)

        self.open_button.Bind(wx.EVT_BUTTON, self._on_open)
        self.import_button.Bind(wx.EVT_BUTTON, self._on_import)
        self.next_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command("next_video", "carregando próximo vídeo..."),
        )
        self.previous_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "previous_video", "carregando vídeo anterior..."
            ),
        )
        self.toggle_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "toggle_playback", "alterando reprodução..."
            ),
        )
        self.author_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command("read_author", "obtendo autor..."),
        )
        self.description_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "read_description", "obtendo descrição..."
            ),
        )
        self.copy_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command("copy_link", "obtendo link..."),
        )
        self.refresh_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "refresh_info", "atualizando informações..."
            ),
        )
        self.volume_up_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "volume_up", "aumentando volume..."
            ),
        )
        self.volume_down_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "volume_down", "diminuindo volume..."
            ),
        )
        self.mute_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "toggle_mute", "alterando som..."
            ),
        )
        self.comments_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "open_comments", "Carregando comentários..."
            ),
        )
        self.like_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "toggle_like", "Alterando curtida..."
            ),
        )
        self.favorite_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command(
                "toggle_favorite", "Alterando favorito..."
            ),
        )
        self.close_browser_button.Bind(wx.EVT_BUTTON, self._on_close_browser)
        self.exit_button.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self._configure_accelerators()

        self.Centre()
        wx.CallAfter(self.open_button.SetFocus)

    @staticmethod
    def _button(parent: wx.Window, label: str, name: str) -> wx.Button:
        button = wx.Button(parent, label=label)
        button.SetName(name)
        return button

    def _configure_accelerators(self) -> None:
        self._accelerator_ids = {
            action: int(wx.NewIdRef()) for action, _modifiers, _key in ACCELERATOR_SPECS
        }
        self.SetAcceleratorTable(
            wx.AcceleratorTable(
                [
                    (modifiers, key, self._accelerator_ids[action])
                    for action, modifiers, key in ACCELERATOR_SPECS
                ]
            )
        )
        for action, _modifiers, _key in ACCELERATOR_SPECS:
            self.Bind(
                wx.EVT_MENU,
                lambda _event, selected=action: self._dispatch_shortcut(selected),
                id=self._accelerator_ids[action],
            )

    def _dispatch_shortcut(self, action: str) -> None:
        message = SHORTCUT_MESSAGES[action]
        if action == "exit":
            self._set_status(message)
            self.Close()
            return
        if action == "diagnostics":
            self._set_status(message)
            self._get_worker().diagnostics()
            return
        self._run_video_command(action, message)

    def _set_status(self, message: str) -> None:
        self.status.SetLabel(f"Status: {message}")
        self.status.SetName(f"Status do aplicativo: {message}")
        wx.Accessible.NotifyEvent(
            wx.ACC_EVENT_OBJECT_NAMECHANGE, self.status, wx.OBJID_CLIENT, 0
        )

    def _announce_accessible(self, message: str) -> None:
        """Anuncia pelo NVDA sem mover o foco para o status ou para os campos."""
        self._set_status(message)
        announced = speak_with_accessible_output(message)
        if not announced:
            announced = speak_with_nvda(message)
        if not announced:
            announced = raise_uia_notification(self.status, message)
        if not announced:
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_SYSTEM_ALERT, self.status, wx.OBJID_CLIENT, 0
            )

    def _receive_worker_event(self, event: WorkerEvent) -> None:
        wx.CallAfter(self._handle_worker_event, event)

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        if not self:
            return
        if event.author is not None:
            self.author_field.SetValue(event.author)
        if event.description is not None:
            self.description_field.SetValue(event.description)
        if event.browser_visible is not None:
            self.show_browser_checkbox.SetValue(event.browser_visible)
        if event.kind == "copy_link":
            self._copy_to_clipboard(event.link)
        elif event.kind == "comments":
            self._show_comments(event.comments or ())
            self._set_status(event.message)
        elif event.kind in {"announcement", "error"}:
            self._announce_accessible(event.message)
        else:
            self._set_status(event.message)
        if event.kind not in {"comments", "stopped"}:
            self._restore_wx_focus()
        if event.kind == "stopped":
            self._worker = None
            self.show_browser_checkbox.SetValue(True)
            if self._closing:
                self.Destroy()

    def _restore_wx_focus(self) -> None:
        focused = wx.Window.FindFocus()
        if (
            focused is not None
            and self._comments_dialog is not None
            and wx.GetTopLevelParent(focused) is self._comments_dialog
        ):
            self._comments_dialog.Raise()
            wx.CallAfter(focused.SetFocus)
            return
        self.Raise()
        if focused is not None and wx.GetTopLevelParent(focused) is self:
            wx.CallAfter(focused.SetFocus)
        else:
            wx.CallAfter(self.open_button.SetFocus)

    def _show_comments(self, comments: tuple[str, ...]) -> None:
        if self._comments_dialog is not None:
            self._comments_dialog.update_comments(comments)
            wx.CallAfter(self._comments_dialog.focus_comments)
            return
        self._comments_dialog = CommentsDialog(
            self,
            comments,
            self._post_comment,
            self._comments_closed,
        )
        self._comments_dialog.Show()
        wx.CallAfter(self._comments_dialog.focus_comments)

    def _post_comment(self, text: str) -> None:
        self._set_status("Publicando comentário...")
        self._get_worker().post_comment(text)

    def _comments_closed(self) -> None:
        self._comments_dialog = None
        if self._worker is not None and self._worker.is_alive():
            self._worker.close_comments()

    def _copy_to_clipboard(self, link: str | None) -> None:
        if not link or "/video/" not in link:
            self._announce_accessible(
                "Não foi possível identificar o link do vídeo atual"
            )
            return
        if not wx.TheClipboard.Open():
            self._announce_accessible(
                "Não foi possível acessar a área de transferência."
            )
            return
        copied = False
        try:
            copied = wx.TheClipboard.SetData(wx.TextDataObject(link))
            if copied:
                wx.TheClipboard.Flush()
        except Exception:
            copied = False
        finally:
            wx.TheClipboard.Close()
        self._announce_accessible(
            "Link copiado."
            if copied
            else "Não foi possível copiar o link para a área de transferência."
        )

    def _get_worker(self) -> BrowserWorker:
        if self._worker is None or not self._worker.is_alive():
            profile = Path(__file__).resolve().parents[1] / "data" / "browser_profile"
            self._worker = BrowserWorker(profile, self._receive_worker_event)
            self._worker.start()
        return self._worker

    def _run_video_command(self, method_name: str, pending_message: str) -> None:
        self._set_status(pending_message)
        method: Callable[[], None] = getattr(self._get_worker(), method_name)
        method()

    def _on_open(self, _event: wx.CommandEvent) -> None:
        self._set_status("abrindo o Chromium e o TikTok...")
        self._get_worker().open_tiktok()

    def _on_import(self, _event: wx.CommandEvent) -> None:
        dialog = wx.FileDialog(
            self,
            message="Selecione o arquivo JSON ou TXT de cookies",
            wildcard=(
                "Arquivos de cookies (*.json;*.txt)|*.json;*.txt|"
                "Arquivos JSON (*.json)|*.json|"
                "Arquivos de texto (*.txt)|*.txt|"
                "Todos os arquivos (*.*)|*.*"
            ),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                self._set_status("importação cancelada.")
                return
            cookie_path = Path(dialog.GetPath())
        finally:
            dialog.Destroy()

        self._set_status("validando e importando cookies...")
        self._get_worker().import_cookies(cookie_path)

    def _on_close_browser(self, _event: wx.CommandEvent) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._set_status("o navegador já está fechado.")
            return
        self._set_status("fechando o navegador...")
        self._worker.shutdown()

    def _on_close_window(self, event: wx.CloseEvent) -> None:
        if self._closing:
            event.Veto()
            return
        self._closing = True
        self.Enable(False)
        if self._worker is not None and self._worker.is_alive():
            event.Veto()
            self._set_status("encerrando o navegador e o aplicativo...")
            self._worker.shutdown()
        else:
            event.Skip()
