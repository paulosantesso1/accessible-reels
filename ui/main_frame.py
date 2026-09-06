from __future__ import annotations

from pathlib import Path
from typing import Callable

import wx

from tiktok.client import BrowserWorker, WorkerEvent
from tiktok.browser_extension import LocalBrowserWorker
from ui.comments_dialog import CommentsDialog
from ui.search_dialog import SearchDialog
from ui.instagram_panel import InstagramPanel
from ui.shortcuts import ACCELERATOR_SPECS, set_shortcut
from ui.nvda_announcer import (
    raise_uia_notification,
    speak_with_accessible_output,
    speak_with_nvda,
)


SHORTCUT_MESSAGES = {
    "next_video": "Comando recebido: próximo vídeo.",
    "previous_video": "Comando recebido: vídeo anterior.",
    "toggle_playback": "Comando recebido: pausar ou reproduzir.",
    "read_author": "Comando recebido: ler autor.",
    "read_description": "Comando recebido: ler descrição.",
    "copy_link": "Comando recebido: copiar link.",
    "refresh_info": "Comando recebido: atualizar informações.",
    "search": "Abrindo pesquisa de vídeos.",
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
        self._worker: BrowserWorker | LocalBrowserWorker | None = None
        self._closing = False
        self._comments_dialog: CommentsDialog | None = None
        self._search_dialog: SearchDialog | None = None
        self._pending_tiktok_events: list[WorkerEvent] = []

        container = wx.Panel(self)
        outer_sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(container, label="Accessible Reels")
        heading.SetName("Título: Accessible Reels")
        font = heading.GetFont()
        font.MakeBold()
        font.SetPointSize(font.GetPointSize() + 3)
        heading.SetFont(font)
        outer_sizer.Add(heading, 0, wx.ALL, 12)

        self.status = wx.StaticText(container, label="Status: pronto.")
        self.status.SetName("Status do aplicativo")
        outer_sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.platform_tabs = wx.Notebook(container)
        self.platform_tabs.SetName("Plataformas")
        self.platform_tabs.SetHelpText("Setas ou Ctrl+Tab alternam as guias; Tab acessa os controles.")
        set_shortcut(self.platform_tabs, shortcut="Ctrl+Tab")
        panel = wx.Panel(self.platform_tabs)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.platform_tabs.AddPage(panel, "TikTok", select=True)
        self.instagram_panel = InstagramPanel(self.platform_tabs, self)
        self.platform_tabs.AddPage(self.instagram_panel, "Instagram")
        outer_sizer.Add(self.platform_tabs, 1, wx.EXPAND | wx.ALL, 12)

        self.open_button = self._button(panel, "Abrir &TikTok", "Abrir TikTok")
        self.browser_mode = wx.RadioBox(
            panel,
            label="Modo do navegador",
            choices=(
                "Chromium integrado",
                "Chrome ou Brave com extensão",
            ),
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        self.browser_mode.SetName("Modo do navegador")
        self.browser_mode.SetSelection(0)
        self.local_minimized_checkbox = wx.CheckBox(
            panel, label="Abrir TikTok em &janela minimizada exclusiva"
        )
        self.local_minimized_checkbox.SetName(
            "Abrir TikTok em janela minimizada exclusiva"
        )
        set_shortcut(self.local_minimized_checkbox)
        self.local_minimized_checkbox.SetValue(True)
        self.local_minimized_checkbox.Enable(False)
        self.import_button = self._button(
            panel, "&Importar cookies", "Importar cookies de um arquivo JSON ou TXT"
        )
        main_sizer.Add(
            self.browser_mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12
        )
        main_sizer.Add(
            self.local_minimized_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        main_sizer.Add(self.open_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        main_sizer.Add(self.import_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.show_browser_checkbox = wx.CheckBox(
            panel, label="Mostrar janela do navegador"
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
        self.search_button = self._button(
            panel, "P&esquisar vídeos", "Pesquisar vídeos"
        )
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
            panel, "Comentários", "Abrir comentários do vídeo atual"
        )
        self.like_button = self._button(
            panel, "Curtir ou descurtir", "Curtir ou descurtir"
        )
        self.favorite_button = self._button(
            panel,
            "Favoritar ou desfavoritar",
            "Favoritar ou desfavoritar",
        )

        video_sizer = wx.FlexGridSizer(rows=0, cols=2, vgap=8, hgap=8)
        video_sizer.AddGrowableCol(0, 1)
        video_sizer.AddGrowableCol(1, 1)
        for button, action in (
            (self.search_button, "search"),
            (self.next_button, "next_video"),
            (self.previous_button, "previous_video"),
            (self.toggle_button, "toggle_playback"),
            (self.author_button, "read_author"),
            (self.description_button, "read_description"),
            (self.copy_button, "copy_link"),
            (self.refresh_button, "refresh_info"),
            (self.volume_up_button, "volume_up"),
            (self.volume_down_button, "volume_down"),
            (self.mute_button, "toggle_mute"),
            (self.comments_button, "open_comments"),
            (self.like_button, "toggle_like"),
            (self.favorite_button, "toggle_favorite"),
        ):
            set_shortcut(button, action=action)
            video_sizer.Add(button, 0, wx.EXPAND)
        main_sizer.Add(video_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        self.close_browser_button = self._button(
            panel, "&Fechar navegador", "Fechar navegador"
        )
        self.exit_button = self._button(
            container, "&Sair", "Sair do Accessible Reels"
        )
        main_sizer.Add(
            self.close_browser_button,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            12,
        )
        outer_sizer.Add(
            self.exit_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12
        )
        panel.SetSizer(main_sizer)
        container.SetSizer(outer_sizer)

        self.open_button.Bind(wx.EVT_BUTTON, self._on_open)
        self.browser_mode.Bind(wx.EVT_RADIOBOX, self._on_browser_mode_changed)
        self.import_button.Bind(wx.EVT_BUTTON, self._on_import)
        self.next_button.Bind(
            wx.EVT_BUTTON,
            lambda _event: self._run_video_command("next_video", "carregando próximo vídeo..."),
        )
        self.search_button.Bind(wx.EVT_BUTTON, lambda _event: self._show_search())
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
        self.Bind(wx.EVT_CHAR_HOOK, self._on_tab_navigation)
        self.platform_tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_platform_changed)
        self._configure_accelerators()

        self.Centre()
        wx.CallAfter(self.platform_tabs.SetFocus)

    def _on_tab_navigation(self, event: wx.KeyEvent) -> None:
        focused = wx.Window.FindFocus()
        if focused is None or wx.GetTopLevelParent(focused) is not self:
            event.Skip()
            return
        key = event.GetKeyCode()
        if (
            key == wx.WXK_TAB
            and not event.AltDown()
            and event.ControlDown()
        ):
            step = -1 if event.ShiftDown() else 1
            selection = (self.platform_tabs.GetSelection() + step) % self.platform_tabs.GetPageCount()
            self.platform_tabs.SetSelection(selection)
            self.platform_tabs.SetFocus()
            return
        if (
            focused is self.platform_tabs
            and key in (wx.WXK_TAB, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
            and not event.HasAnyModifiers()
        ):
            self._focus_platform_content()
            return
        event.Skip()

    def _focus_platform_content(self) -> None:
        if self.platform_tabs.GetSelection() == 0:
            self.open_button.SetFocus()
        else:
            self.instagram_panel.open_button.SetFocus()

    def _on_platform_changed(self, event: wx.BookCtrlEvent) -> None:
        event.Skip()
        # Let native notebook selection/focus finish before delivering responses.
        wx.CallAfter(self._deliver_platform_events)

    def _deliver_platform_events(self) -> None:
        if not self or self._closing:
            return
        if self.platform_tabs.GetSelection() == 1:
            self.instagram_panel.activate()
        else:
            pending, self._pending_tiktok_events = self._pending_tiktok_events, []
            for event in pending:
                self._handle_worker_event(event)

    @staticmethod
    def _button(parent: wx.Window, label: str, name: str) -> wx.Button:
        button = wx.Button(parent, label=label)
        button.SetName(name)
        set_shortcut(button)
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
        if self.platform_tabs.GetSelection() != 0:
            self.instagram_panel.dispatch_shortcut(action, message)
            return
        if action == "diagnostics":
            self._set_status(message)
            self._get_worker().diagnostics()
            return
        if action == "search":
            self._set_status(message)
            self._show_search()
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
        if event.kind == "stopped":
            self._worker = None
            self.browser_mode.Enable(True)
            self._on_browser_mode_changed(None)
            self.show_browser_checkbox.SetValue(True)
            self._pending_tiktok_events.clear()
            if not self._closing and self.platform_tabs.GetSelection() == 0:
                self._set_status(event.message)
            self._finish_close()
            return
        if self._closing:
            return
        if event.author is not None:
            self.author_field.SetValue(event.author)
        if event.description is not None:
            self.description_field.SetValue(event.description)
        if event.browser_visible is not None:
            self.show_browser_checkbox.SetValue(event.browser_visible)
        if self.platform_tabs.GetSelection() != 0:
            self._pending_tiktok_events.append(event)
            return
        if event.kind == "copy_link":
            self._copy_to_clipboard(event.link)
        elif event.kind == "comments":
            self._show_comments(event.comments or ())
            self._set_status(event.message)
        elif event.kind == "search_results":
            if self._search_dialog is not None:
                self._search_dialog.search_finished()
                self._search_dialog.update_results(event.search_results or ())
            self._announce_accessible(event.message)
        elif event.kind in {"announcement", "error"}:
            if self._search_dialog is not None:
                self._search_dialog.search_finished()
            self._announce_accessible(event.message)
        else:
            self._set_status(event.message)
        if event.kind not in {"comments", "stopped"}:
            self._restore_wx_focus()

    def _restore_wx_focus(self) -> None:
        focused = wx.Window.FindFocus()
        if focused is not None:
            for dialog in (self._comments_dialog, self._search_dialog):
                if dialog is not None and wx.GetTopLevelParent(focused) is dialog:
                    dialog.Raise()
                    wx.CallAfter(focused.SetFocus)
                    return
        self.Raise()
        if focused is not None and wx.GetTopLevelParent(focused) is self:
            wx.CallAfter(focused.SetFocus)
        else:
            wx.CallAfter(self._focus_platform_content)

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

    def _show_search(self) -> None:
        if self._search_dialog is not None:
            wx.CallAfter(self._search_dialog.focus_query)
            return
        self._search_dialog = SearchDialog(
            self,
            self._search_videos,
            self._open_search_result,
            self._search_closed,
        )
        self._search_dialog.Show()
        wx.CallAfter(self._search_dialog.focus_query)

    def _search_videos(self, query: str) -> None:
        self._set_status(f"pesquisando por {query}...")
        self._get_worker().search(query)

    def _open_search_result(self, url: str) -> None:
        self._set_status("abrindo vídeo selecionado...")
        self._get_worker().open_search_result(url)

    def _search_closed(self) -> None:
        self._search_dialog = None

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

    def _get_worker(self) -> BrowserWorker | LocalBrowserWorker:
        if self._worker is None or not self._worker.is_alive():
            if self.browser_mode.GetSelection() == 1:
                self._worker = LocalBrowserWorker(
                    self._receive_worker_event,
                    open_minimized=self.local_minimized_checkbox.GetValue(),
                )
            else:
                profile = Path(__file__).resolve().parents[1] / "data" / "browser_profile"
                self._worker = BrowserWorker(profile, self._receive_worker_event)
            self._worker.start()
            self.browser_mode.Enable(False)
            self.local_minimized_checkbox.Enable(False)
        return self._worker

    def _run_video_command(self, method_name: str, pending_message: str) -> None:
        self._set_status(pending_message)
        method: Callable[[], None] = getattr(self._get_worker(), method_name)
        method()

    def _on_open(self, _event: wx.CommandEvent) -> None:
        self._set_status(
            "conectando à aba autenticada do TikTok..."
            if self.browser_mode.GetSelection() == 1
            else "abrindo o Chromium e o TikTok..."
        )
        self._get_worker().open_tiktok()

    def _on_browser_mode_changed(self, _event: wx.CommandEvent | None) -> None:
        local = self.browser_mode.GetSelection() == 1
        self.import_button.Enable(not local)
        self.local_minimized_checkbox.Enable(local and self._worker is None)
        self.open_button.SetLabel(
            "Conectar ao &TikTok" if local else "Abrir &TikTok"
        )
        self.open_button.SetName(
            "Conectar à aba autenticada do TikTok" if local else "Abrir TikTok"
        )
        self.close_browser_button.SetLabel(
            "&Fechar conexão do navegador" if local else "&Fechar navegador"
        )
        self.close_browser_button.SetName(
            "Desconectar navegador local" if local else "Fechar navegador"
        )

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
        if isinstance(self._worker, LocalBrowserWorker):
            self._worker.disconnect()
        else:
            self._worker.shutdown()

    def _on_close_window(self, event: wx.CloseEvent) -> None:
        if self._closing:
            event.Veto()
            return
        self._closing = True
        self.Enable(False)
        workers = [worker for worker in (self._worker, self.instagram_panel.worker)
                   if worker is not None and worker.is_alive()]
        if workers:
            event.Veto()
            self._set_status("encerrando as conexões e o aplicativo...")
            if self._worker not in workers:
                self._worker = None
            if self.instagram_panel.worker not in workers:
                self.instagram_panel.worker = None
            for worker in workers:
                worker.shutdown()
        else:
            event.Skip()

    def _finish_close(self) -> None:
        if self._closing and self._worker is None and self.instagram_panel.worker is None:
            self.Destroy()
