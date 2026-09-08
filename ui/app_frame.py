"""Accessible controls and embedded social pages in one application window."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import wx
import wx.html2 as html2

from app_logging import get_logger, log_directory
from webview_runtime import backend_version
from ui.webview_focus import EmbeddedFocusMixin, FOCUS_PAGE_HOTKEY
from ui.webview_client import WebViewClient, PLATFORM_URLS
from ui.video_link import parse_video_link
from ui.shortcuts import ACCELERATOR_SPECS, SEEK_ACCELERATOR_SPECS, SEEK_SECONDS
from ui.nvda_announcer import speak_with_accessible_output, speak_with_nvda, raise_uia_notification
from tiktok.search import search_url, normalize_search_results, validate_search_result_url
from instagram.search import normalize_reel_results, validate_reel_url
from tiktok.video_controls import VideoControlError
from updater import UpdateError, can_self_update, check_for_update, download_update, launch_installer

COMMANDS = {'next_video':'next', 'previous_video':'previous', 'toggle_playback':'toggle',
            'read_author':'author', 'read_description':'description', 'open_comments':'comments'}
logger = get_logger()


def _copy_text_to_clipboard(text):
    """Store rendered Unicode text so it survives this process closing on Windows."""
    if sys.platform != 'win32':
        if not wx.TheClipboard.Open():
            return False
        try:
            return wx.TheClipboard.SetData(wx.TextDataObject(text))
        finally:
            wx.TheClipboard.Close()

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    if not user32.OpenClipboard(None):
        return False
    handle = None
    try:
        encoded = (text + '\0').encode('utf-16-le')
        handle = kernel32.GlobalAlloc(0x0002, len(encoded))
        if not handle:
            return False
        address = kernel32.GlobalLock(handle)
        if not address:
            return False
        ctypes.memmove(address, encoded, len(encoded))
        kernel32.GlobalUnlock(handle)
        if not user32.EmptyClipboard():
            return False
        if not user32.SetClipboardData(13, handle):
            return False
        handle = None
        return True
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


def session_summary(opened_platforms):
    """Describe the local session state without claiming a remote login succeeded."""
    opened = set(opened_platforms)
    return ' | '.join(
        f'{name}: ' + ('aberto' if name in opened else 'não aberto')
        for name in ('TikTok', 'Instagram')
    )


def video_details_text(author, description):
    author = str(author or '').strip() or 'Não identificado'
    description = str(description or '').strip() or 'Sem descrição disponível.'
    return f'Autor: {author}\n\nDescrição:\n{description}'


def comment_list_label(index, count, text):
    """Return a short, useful name for one item in the native comments list."""
    compact = ' '.join(str(text or '').split())
    if len(compact) > 90:
        compact = compact[:87].rstrip() + '...'
    return f'Comentário {index} de {count}: {compact or "Sem texto disponível."}'


def comment_details_text(index, count, text):
    """Expose the full selected comment in its own read-only field."""
    return f'Comentário {index} de {count}\n\n{str(text or "").strip() or "Sem texto disponível."}'


def keyboard_help_text():
    speed_help = 'Shift+< / Shift+> - Diminuir ou aumentar a velocidade\n'
    return (
        'Ajuda rápida de atalhos\n\n'
        'F6 — Alternar entre a página da plataforma e os controles\n'
        'Ctrl+1 / Ctrl+2 — Abrir TikTok / Instagram\n'
        'Ctrl+O — Abrir um link de vídeo\n'
        'Alt+Seta para cima / baixo — Vídeo anterior / próximo\n'
        'Alt+P — Reproduzir ou pausar\n'
        'Alt+Seta para esquerda / direita — Voltar ou avançar 30 segundos\n'
        'Alt+Shift+Seta para esquerda / direita — Voltar ou avançar 15 segundos\n'
        'Alt+Shift+Seta para cima / baixo — Aumentar ou diminuir o volume\n'
        'Alt+Shift+M — Ativar ou desativar o mudo\n'
        'F5 — Atualizar autor e descrição\n'
        'Alt+A / Alt+D — Ler autor / descrição\n'
        'Alt+C — Copiar link\n'
        'Alt+Shift+C — Comentários\n'
        'Alt+L — Curtir ou descurtir\n'
        'Alt+F — Salvar ou remover dos salvos\n'
        'L — Curtir ou descurtir\n'
        'F — Salvar ou remover dos salvos\n'
        'Alt+E — Pesquisar vídeos\n'
        'Alt+S — Sair\n'
        + speed_help
    )


def webview_profile_path(*, local_app_data=None, frozen=None, source_root=None):
    """Return one stable WebView2 profile and migrate the former source profile."""
    local_root = Path(local_app_data or os.environ.get('LOCALAPPDATA') or Path.home())
    profile = local_root / 'Accessible Reels' / 'webview_profile'
    is_frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    project_root = Path(__file__).resolve().parents[1] if source_root is None else Path(source_root)
    legacy = project_root / 'data' / 'webview_profile'
    if not is_frozen and not profile.exists() and legacy.exists():
        try:
            profile.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legacy, profile)
        except OSError:
            # Preserving the known logged-in profile is better than silently
            # starting an empty session when migration is temporarily blocked.
            return legacy
    profile.mkdir(parents=True, exist_ok=True)
    return profile


class MainFrame(EmbeddedFocusMixin, wx.Frame):
    def __init__(self, *, auto_open=False):
        super().__init__(None, title='Accessible Reels', size=(1180, 850))
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(webview_profile_path())
        self.views, self.clients, self.platform_data = {}, {}, {}
        self._active_name = 'TikTok'
        self._pending_page_focus = None
        self._closing_app = False
        self._update_checking = False
        self._registered_hotkeys = set()
        self._accelerator_ids = {}
        self._results = ()
        self.CreateStatusBar()
        self._build_menu_bar()
        self.panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.network = wx.RadioBox(self.panel, choices=['TikTok', 'Instagram'])
        self.network.Hide()
        session_row = wx.BoxSizer(wx.VERTICAL)
        self.platform_field = wx.StaticText(self.panel, label='')
        self.platform_field.SetName('Plataforma ativa')
        session_row.Add(self.platform_field, 0, wx.EXPAND | wx.BOTTOM, 3)
        layout.Add(session_row, 0, wx.EXPAND | wx.ALL, 8)
        self.session_field = wx.StaticText(self.panel, label='')
        self.session_field.SetName('Plataformas abertas nesta sessão')
        layout.Add(self.session_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.status_field = wx.StaticText(self.panel, label='Pronto.')
        self.status_field.SetName('Status do aplicativo')
        layout.Add(self.status_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        # Simplebook keeps secondary screens available without permanent tabs.
        self.activities = wx.Simplebook(self.panel, size=(350, -1))
        self.activities.SetMinSize((330, -1))
        self.activities.SetName('Painel atual: player, comentários ou pesquisa')
        row.Add(self.activities, 0, wx.EXPAND | wx.ALL, 5)
        self.content = wx.BoxSizer(wx.VERTICAL)
        self.hint = wx.StaticText(self.panel, label='Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram. A sessão salva será reutilizada quando disponível.')
        self.content.Add(self.hint, 0, wx.ALL, 8)
        row.Add(self.content, 1, wx.EXPAND | wx.ALL, 5)
        layout.Add(row, 1, wx.EXPAND)
        self.panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        self._build_video_controls()
        self._build_comments()
        self._build_search()
        self._configure_accelerators()
        self.Bind(wx.EVT_HOTKEY, self.toggle_page_controls, id=FOCUS_PAGE_HOTKEY)
        self.Bind(wx.EVT_ACTIVATE, self._activation_changed)
        self.Bind(wx.EVT_CLOSE, self._closing)
        self.Bind(wx.EVT_CHAR_HOOK, self._plain_shortcuts)
        self._refresh_session_controls()
        self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram. F1 mostra os atalhos.')
        self.details_field.SetFocus()
        if can_self_update():
            wx.CallLater(2000, self._check_for_updates)
        if auto_open:
            wx.CallAfter(self.open_network)

    def _build_menu_bar(self):
        bar = wx.MenuBar()
        platform = wx.Menu()
        self._append_menu_item(platform, 'Abrir ou mostrar TikTok', lambda event: self._open_platform('TikTok'))
        self._append_menu_item(platform, 'Abrir ou mostrar Instagram', lambda event: self._open_platform('Instagram'))
        platform.AppendSeparator()
        self._append_menu_item(platform, 'Abrir link...', self.open_link, 'Ctrl+O')
        self._append_menu_item(platform, 'Voltar ao feed', self.home)
        self._append_menu_item(platform, 'Recarregar página', self.reload)
        bar.Append(platform, '&Plataforma')

        player = wx.Menu()
        for label, action in [
            ('Vídeo anterior', 'previous_video'), ('Reproduzir ou pausar', 'toggle_playback'),
            ('Próximo vídeo', 'next_video'), ('Atualizar detalhes', 'refresh_info'),
            ('Voltar 30 segundos', 'seek_back_30'), ('Avançar 30 segundos', 'seek_forward_30'),
            ('Diminuir volume', 'volume_down'), ('Aumentar volume', 'volume_up'),
            ('Diminuir velocidade', 'speed_down'), ('Aumentar velocidade', 'speed_up'),
            ('Ativar ou desativar mudo', 'toggle_mute'),
        ]:
            self._append_menu_item(player, label, lambda event, a=action: self.dispatch(a))
        bar.Append(player, '&Player')

        actions = wx.Menu()
        for label, action in [
            ('Curtir ou descurtir', 'toggle_like'), ('Salvar ou remover dos salvos', 'toggle_favorite'),
            ('Copiar link', 'copy_link'), ('Comentários', 'open_comments'), ('Pesquisar vídeos', 'search'),
        ]:
            self._append_menu_item(actions, label, lambda event, a=action: self.dispatch(a))
        bar.Append(actions, '&Ações')

        help_menu = wx.Menu()
        self._append_menu_item(help_menu, 'Ajuda rápida de atalhos', self.show_keyboard_help, 'F1')
        self._append_menu_item(help_menu, 'Verificar atualizações', self.on_check_for_updates)
        self._append_menu_item(help_menu, 'Abrir pasta de logs para suporte', self.open_log_folder)
        help_menu.AppendSeparator()
        self._append_menu_item(help_menu, 'Verificar runtime incluído...', self.install_webview2_runtime)

        help_menu.AppendSeparator()
        self._append_menu_item(help_menu, 'Sair', lambda event: self.Close(), 'Alt+S')
        bar.Append(help_menu, 'A&juda')
        self.SetMenuBar(bar)

    def open_log_folder(self, event=None):
        """Open the local, user-controlled diagnostic files for sharing."""
        folder = log_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == 'win32':
                os.startfile(str(folder))
            else:
                wx.LaunchDefaultBrowser(folder.as_uri())
        except OSError:
            self.status('Não foi possível abrir a pasta de logs.')
            logger.exception('Could not open support log folder')
            return
        self.status('Pasta de logs aberta. Envie o arquivo accessible-reels.log ao suporte.')

    def _append_menu_item(self, menu, label, handler, shortcut=''):
        item = menu.Append(wx.ID_ANY, label + (f'\t{shortcut}' if shortcut else ''))
        self.Bind(wx.EVT_MENU, handler, item)
        return item

    def _select_platform(self, name):
        self.network.SetStringSelection(name)
        self.select_network()

    def _open_platform(self, name):
        self._select_platform(name)
        if self.network.GetStringSelection() == name:
            self.open_network()

    def _build_video_controls(self):
        page = wx.Panel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label='Player'), 0, wx.ALL, 8)
        sizer.Add(wx.StaticText(page, label='Detalhes do vídeo'), 0, wx.LEFT | wx.TOP, 8)
        self.details_field = wx.TextCtrl(page, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 230))
        self.details_field.SetName('Autor e descrição do vídeo atual, somente leitura')
        self.details_field.Bind(wx.EVT_KEY_DOWN, self._keep_tab_in_app)
        self.player_focus_target = self.details_field
        sizer.Add(self.details_field, 0, wx.EXPAND | wx.ALL, 8)
        hint = wx.StaticText(page, label='Use os atalhos para controlar a reprodução. F1 mostra todos; F6 entra na página; F10 navega pelos menus.')
        hint.SetName('Dica de navegação')
        hint.Wrap(300)
        sizer.Add(hint, 0, wx.EXPAND | wx.ALL, 8)
        sizer.AddStretchSpacer()
        page.SetSizer(sizer)
        self.activities.AddPage(page, 'Player')

    def on_check_for_updates(self, event=None):
        self._check_for_updates(manual=True)

    def _check_for_updates(self, manual=False):
        if self._update_checking:
            if manual:
                self.status('A verificação de atualizações já está em andamento.')
            return
        self._update_checking = True
        threading.Thread(target=self._update_worker, args=(manual,), daemon=True).start()

    def _update_worker(self, manual):
        try:
            info = check_for_update()
        except UpdateError as error:
            wx.CallAfter(self._finish_update_check, manual, None, str(error))
            return
        wx.CallAfter(self._finish_update_check, manual, info, '')

    def _finish_update_check(self, manual, info, error):
        self._update_checking = False
        if error:
            if manual:
                wx.MessageBox(error, 'Atualizações', wx.OK | wx.ICON_ERROR, self)
            return
        if not info:
            if manual:
                wx.MessageBox('Você já está na versão mais recente.', 'Atualizações', wx.OK | wx.ICON_INFORMATION, self)
            return
        if not can_self_update():
            if manual:
                wx.MessageBox('Há uma nova versão no GitHub. A instalação automática está disponível no aplicativo instalado para Windows.',
                              'Atualizações', wx.OK | wx.ICON_INFORMATION, self)
            return
        message = f'Versão {info.latest_version} disponível.\n\n{info.notes}\n\nDeseja baixar e instalar agora?'
        if wx.MessageBox(message, 'Atualizações', wx.YES_NO | wx.ICON_INFORMATION, self) == wx.YES:
            threading.Thread(target=self._download_update_worker, args=(info,), daemon=True).start()

    def _download_update_worker(self, info):
        try:
            wx.CallAfter(self.status, 'Baixando e validando a atualização...')
            installer = download_update(info)
            wx.CallAfter(self._launch_update, installer)
        except UpdateError as error:
            wx.CallAfter(wx.MessageBox, str(error), 'Atualizações', wx.OK | wx.ICON_ERROR, self)

    def _launch_update(self, installer):
        try:
            launch_installer(installer)
        except UpdateError as error:
            wx.MessageBox(str(error), 'Atualizações', wx.OK | wx.ICON_ERROR, self)
            return
        self.Close()

    def install_webview2_runtime(self, event=None):
        if html2.WebView.IsBackendAvailable(html2.WebViewBackendEdge):
            wx.MessageBox('O Microsoft Edge WebView2 Runtime já está disponível neste computador.',
                          'WebView2 Runtime', wx.OK | wx.ICON_INFORMATION, self)
            return
        logger.error('WebView2 backend unavailable: wx=%s folder=%s',
                     wx.version(), os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'))
        wx.MessageBox('Não foi possível carregar o runtime. Reinstale o Accessible Reels '
                      'usando o instalador completo e envie os logs se o problema persistir.',
                      'WebView2 Runtime', wx.OK | wx.ICON_ERROR, self)


    def _build_comments(self):
        page = wx.Panel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label='Comentários do vídeo atual:'), 0, wx.ALL, 5)
        self.comments_list = wx.ListBox(page, style=wx.LB_SINGLE)
        self.comments_list.SetName('Lista de comentários do vídeo atual')
        self.comments_list.Bind(wx.EVT_LISTBOX, self._comment_selected)
        self.comments_list.Bind(wx.EVT_KEY_DOWN, self._keep_tab_in_app)
        sizer.Add(self.comments_list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(page, label='Detalhes do comentário selecionado:'), 0, wx.LEFT | wx.TOP, 5)
        self.comment_details_field = wx.TextCtrl(
            page, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 125)
        )
        self.comment_details_field.SetName('Detalhes do comentário selecionado, somente leitura')
        self.comment_details_field.Bind(wx.EVT_KEY_DOWN, self._keep_tab_in_app)
        sizer.Add(self.comment_details_field, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(page, label='Os comentários estão disponíveis somente para leitura. Esc volta ao player.'), 0, wx.ALL, 5)
        page.SetSizer(sizer)
        self.activities.AddPage(page, 'Comentários')

    def _render_comments(self):
        comments = self.platform_data.get(self._active_name, {}).get('comments', [])
        selected = self._selected_comment()
        selected_id = selected.get('id') if selected else None
        self._comment_items = tuple(
            comment if isinstance(comment, dict) else {'id': str(index), 'text': str(comment)}
            for index, comment in enumerate(comments, start=1)
        )
        self.comments_list.Set([
            comment_list_label(index, len(self._comment_items), item.get('text', ''))
            for index, item in enumerate(self._comment_items, start=1)
        ])
        selected_index = next(
            (index for index, item in enumerate(self._comment_items) if item.get('id') == selected_id),
            0,
        )
        if self._comment_items:
            self.comments_list.SetSelection(selected_index)
        self._show_selected_comment()

    def _selected_comment(self):
        index = self.comments_list.GetSelection()
        items = getattr(self, '_comment_items', ())
        return items[index] if 0 <= index < len(items) else None

    def _comment_selected(self, event=None):
        self._show_selected_comment()
        if event:
            event.Skip()

    def _show_selected_comment(self):
        item = self._selected_comment()
        if not item:
            self.comment_details_field.ChangeValue('Nenhum comentário selecionado.')
            self.comment_details_field.SetName('Detalhes do comentário selecionado, somente leitura, nenhum comentário selecionado')
            return
        index = self.comments_list.GetSelection() + 1
        count = len(self._comment_items)
        text = item.get('text', '')
        self.comment_details_field.ChangeValue(comment_details_text(index, count, text))
        self.comment_details_field.SetName(f'Detalhes do comentário {index} de {count}, somente leitura')

    def _build_search(self):
        page = wx.Panel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label='Pesquisar vídeos:'), 0, wx.ALL, 5)
        self.query_field = wx.TextCtrl(page, style=wx.TE_PROCESS_ENTER)
        self.query_field.SetName('Termo da pesquisa')
        self.query_field.Bind(wx.EVT_TEXT_ENTER, self.search)
        self.query_field.Bind(wx.EVT_KEY_DOWN, self._keep_tab_in_app)
        sizer.Add(self.query_field, 0, wx.EXPAND | wx.ALL, 5)
        self.results_list = wx.ListBox(page)
        self.results_list.SetName('Resultados da pesquisa')
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self.open_result)
        self.results_list.Bind(wx.EVT_KEY_DOWN, self._results_key_down)
        self.results_list.Bind(wx.EVT_KEY_DOWN, self._keep_tab_in_app)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(page, label='Enter abre o resultado. Esc volta ao player.'), 0, wx.ALL, 5)
        page.SetSizer(sizer)
        self.activities.AddPage(page, 'Pesquisa')

    def _configure_accelerators(self):
        entries = []
        for action, modifiers, key in ACCELERATOR_SPECS + SEEK_ACCELERATOR_SPECS:
            identifier = wx.NewIdRef()
            self._accelerator_ids[action] = identifier
            self.Bind(wx.EVT_MENU, lambda e, a=action: self.dispatch(a), id=identifier)
            entries.append((modifiers, key, identifier))
        for action, modifiers, callback in [('toggle_page_controls', wx.ACCEL_NORMAL, self.toggle_page_controls)]:
            identifier = wx.NewIdRef()
            self._accelerator_ids[action] = identifier
            self.Bind(wx.EVT_MENU, callback, id=identifier)
            entries.append((modifiers, wx.WXK_F6, identifier))
        identifier = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, getattr(self, 'show_keyboard_help', lambda event: None), id=identifier)
        entries.append((wx.ACCEL_NORMAL, wx.WXK_F1, identifier))
        for action, key, handler in [
            ('select_tiktok', ord('1'), lambda event: self._open_platform('TikTok')),
            ('select_instagram', ord('2'), lambda event: self._open_platform('Instagram')),
            ('open_selected_platform', wx.WXK_RETURN, lambda event: self.open_network()),
            ('open_link', ord('O'), lambda event: self.open_link()),
        ]:
            identifier = wx.NewIdRef()
            self._accelerator_ids[action] = identifier
            self.Bind(wx.EVT_MENU, handler, id=identifier)
            entries.append((wx.ACCEL_CTRL, key, identifier))
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def show_keyboard_help(self, event=None):
        dialog = wx.Dialog(self, title='Ajuda rápida de atalhos', style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        dialog.SetMinSize((520, 380))
        root = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(dialog, label='Ajuda rápida de atalhos')
        field = wx.TextCtrl(dialog, value=keyboard_help_text(), style=wx.TE_MULTILINE | wx.TE_READONLY)
        field.SetName('Ajuda rápida de atalhos')
        close = wx.Button(dialog, wx.ID_OK, 'Fechar')
        root.Add(label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(field, 1, wx.EXPAND | wx.ALL, 10)
        root.Add(close, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        dialog.SetSizerAndFit(root)
        dialog.SetSize((560, 500))
        field.SetFocus()
        dialog.ShowModal()
        dialog.Destroy()

    def _refresh_session_controls(self):
        opened = self.views.keys()
        name = self.network.GetStringSelection()
        self.platform_field.SetLabel(f'Plataforma ativa: {name}. Ctrl+1 abre TikTok; Ctrl+2 abre Instagram; F10 menus.')
        self.session_field.SetLabel(session_summary(opened))

    def _plain_shortcuts(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and self.activities.GetSelection() != 0:
            self.focus_controls()
            return
        if (event.GetKeyCode() == wx.WXK_TAB and self.activities.GetSelection() == 1
                and not event.ControlDown() and not event.AltDown()):
            self._cycle_comment_focus(wx.Window.FindFocus(), event.ShiftDown())
            return
        focused = wx.Window.FindFocus()
        if (event.HasAnyModifiers() or isinstance(focused, wx.TextCtrl) and focused.IsEditable()
                or focused is self.current()):
            event.Skip()
            return
        event.Skip()

    def _keep_tab_in_app(self, event):
        if (event.GetKeyCode() != wx.WXK_TAB or event.ControlDown() or event.AltDown()):
            event.Skip()
            return
        if self.activities.GetSelection() == 1:
            self._cycle_comment_focus(event.GetEventObject(), event.ShiftDown())
            return
        controls = (
            (self.details_field,),
            (),
            (self.query_field, self.results_list),
        )[self.activities.GetSelection()]
        source = event.GetEventObject()
        try:
            index = controls.index(source)
        except ValueError:
            event.Skip()
            return
        offset = -1 if event.ShiftDown() else 1
        controls[(index + offset) % len(controls)].SetFocus()

    def _comment_focus_controls(self):
        return self.comments_list, self.comment_details_field

    def _cycle_comment_focus(self, source, backwards=False):
        controls = self._comment_focus_controls()
        try:
            index = controls.index(source)
        except ValueError:
            controls[-1 if backwards else 0].SetFocus()
            return
        offset = -1 if backwards else 1
        controls[(index + offset) % len(controls)].SetFocus()

    def _results_key_down(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.open_result()
            return
        event.Skip()

    def status(self, message):
        if self._closing_app:
            return
        message = str(message)[:3000]
        self.SetStatusText(message)
        self.status_field.SetLabel(message[:240])
        self.status_field.Wrap(max(400, self.panel.GetClientSize().width - 20))
        if not speak_with_accessible_output(message) and not speak_with_nvda(message):
            raise_uia_notification(self.status_field, message)
        self.panel.Layout()

    def current(self):
        return self.views.get(self.network.GetStringSelection())

    def focus_controls(self, event=None):
        self.activities.SetSelection(0)
        super().focus_controls(event)

    def select_network(self, event=None):
        name = self.network.GetStringSelection()
        old = self.clients.get(self._active_name)
        if old and old.pending:
            self.network.SetStringSelection(self._active_name)
            self.status('Aguarde a conclusão da ação antes de trocar de rede.')
            return
        self._pending_page_focus = None
        self._active_name = name
        for platform, view in self.views.items():
            self.clients[platform].set_active(platform == name)
            view.Show(platform == name)
        self.hint.Show(self.current() is None)
        self._restore_fields()
        self._refresh_session_controls()
        self.panel.Layout()
        self.status(f'{name} selecionado. Use Ctrl+1 para TikTok ou Ctrl+2 para Instagram.' if not self.current()
                    else f'{name} aberto. Use os controles ou F6 para entrar na página.')

    def open_network(self, event=None, *, url=None, after_load=None):
        if self._closing_app:
            return
        name = self.network.GetStringSelection()
        old = self.clients.get(self._active_name)
        if old and old.pending and name != self._active_name:
            self.network.SetSelection(0 if self._active_name == 'TikTok' else 1)
            self.status('Aguarde a conclusão da ação antes de trocar de rede.')
            return
        if not html2.WebView.IsBackendAvailable(html2.WebViewBackendEdge):
            logger.error('WebView2 backend unavailable: wx=%s folder=%s', wx.version(), os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'))
            self.status('Não foi possível carregar o runtime. Consulte Alt+J, Verificar runtime incluído.')
            return
        logger.info('WebView2 backend ready: version=%s folder=%s',
                    backend_version(),
                    os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'system'))
        self._pending_page_focus = None
        self._active_name = name
        for platform, view in self.views.items():
            self.clients[platform].set_active(platform == name)
            view.Hide()
        self.hint.Hide()
        if name not in self.views:
            view = html2.WebView.New(backend=html2.WebViewBackendEdge)
            self.views[name] = view
            self.platform_data[name] = {}
            client = WebViewClient(view, name, lambda n=name: self.loaded(n), lambda message, n=name: self._platform_error(n, message))
            if url:
                client.target_url = url
                client.after_load = after_load
            self.clients[name] = client
            view.Bind(html2.EVT_WEBVIEW_NEWWINDOW, self.new_window)
            view.Bind(html2.EVT_WEBVIEW_LOADED, self._page_document_loaded)
            if not view.Create(self.panel):
                logger.error('WebView2 Create failed: platform=%s', name)
                self.status('Não foi possível criar a página incorporada.')
                client.close()
                del self.views[name], self.clients[name], self.platform_data[name]
                return
            view.SetCanFocus(False)
            client.initialize()
            self.content.Add(view, 1, wx.EXPAND)
        elif url:
            self.clients[name].navigate(url, after_load)
        self.current().Show()
        self._restore_fields()
        self._refresh_session_controls()
        self.panel.Layout()
        self.status(f'{name} na janela do aplicativo. Use os controles ou F6 para acessar a página.')

    def open_link(self, event=None):
        with wx.TextEntryDialog(self, 'Cole a URL de um vídeo do TikTok ou de um Reel do Instagram:',
                                'Abrir link a partir de uma URL') as dialog:
            dialog.FindWindow(wx.ID_OK).SetLabel('Abrir vídeo')
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.open_video_link(dialog.GetValue())

    def open_video_link(self, value):
        try:
            name, url = parse_video_link(value)
        except VideoControlError as error:
            self.status(str(error))
            return
        if any(client.pending for client in self.clients.values()):
            self.status('Aguarde o comando anterior.')
            return
        self.network.SetStringSelection(name)
        self.open_network(url=url, after_load=lambda: self.dispatch('play')
                          if self._active_name == name and not self._closing_app else None)
        self.focus_controls()

    def _restore_fields(self):
        data = self.platform_data.get(self._active_name, {})
        self.details_field.ChangeValue(video_details_text(data.get('author'), data.get('description')))
        self._render_comments()
        self._results = data.get('results', ())
        self.results_list.Set([item.label for item in self._results])
        if self._results:
            self.results_list.SetSelection(0)

    def _platform_error(self, platform, message):
        logger.warning('Platform error: platform=%s message=%s', platform, message)
        if platform == self._active_name:
            self.status(message)

    def loaded(self, platform):
        if platform != self._active_name or self._closing_app:
            return
        if self._pending_page_focus is self.current():
            wx.CallAfter(self._enter_page, self.current())
        else:
            self.status(f'{platform} carregado. F6 alterna entre a página e os controles.')
        # The page bridge is ready at this point. Refreshing here, rather than
        # waiting for F5, populates details on the first video that is opened.
        self.dispatch('refresh_info')

    def home(self, event=None):
        if not self.current():
            self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram.')
        elif not self.clients[self._active_name].pending:
            self.clients[self._active_name].navigate(PLATFORM_URLS[self._active_name])
        else:
            self.status('Aguarde o comando anterior.')

    def reload(self, event=None):
        if self.current():
            self.current().Reload()
        else:
            self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram.')

    def new_window(self, event):
        if urlsplit(event.GetURL()).scheme == 'https':
            event.GetEventObject().LoadURL(event.GetURL())
        else:
            self.status('Esse link exige um aplicativo externo e não foi aberto.')

    def dispatch(self, action, argument=None):
        if action == 'exit':
            self.Close()
            return
        if action in ('post_comment', 'reply_comment'):
            self.status('A publicação e as respostas a comentários estão desativadas temporariamente.')
            return
        if action == 'search':
            self.activities.SetSelection(2)
            self.query_field.SetFocus()
            return
        if not self.current():
            self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram.')
            return
        name = self._active_name
        client = self.clients[name]
        if client.pending:
            return
        logger.info('Command requested: platform=%s action=%s', name, action)
        focused = wx.Window.FindFocus()
        restore_focus = focused if focused and focused is not self.current() else None
        def completed(result):
            if self._closing_app:
                return
            self._result(name, action, argument, result)
            if name == self._active_name and self.IsActive() and action not in ('open_comments', 'collect_search_results', 'close_comments'):
                if restore_focus and wx.Window.FindFocus() is self.current():
                    restore_focus.SetFocus()
        client.execute('seek' if action in SEEK_SECONDS else COMMANDS.get(action, action),
                       SEEK_SECONDS.get(action, argument), completed)

    # Compatibility hooks retained for callers of the former native window.
    def _dispatch_shortcut(self, action):
        self.dispatch(action)

    def _run_video_command(self, action, argument=None):
        self.dispatch(action, argument)

    def _result(self, name, action, argument, result):
        if result.get('ignored'):
            return
        if result.get('ok') is not True:
            logger.warning('Command failed: platform=%s action=%s message=%s', name, action, result.get('error'))
            self._platform_error(name, result.get('error') or 'A rede não confirmou o comando.')
            return
        logger.info('Command completed: platform=%s action=%s', name, action)
        data = self.platform_data[name]
        for field in ('author', 'description', 'link', 'comments'):
            if field in result:
                data[field] = result[field]
        active = name == self._active_name
        if 'results' in result:
            normalize = normalize_search_results if name == 'TikTok' else normalize_reel_results
            data['results'] = normalize(result['results'])
        if active:
            self._restore_fields()
        message = 'Comando concluído.'
        if action in SEEK_SECONDS:
            position = round(result.get('position', 0))
            message = f'Posição: {position // 60} minutos e {position % 60} segundos.'
        if action in ('next_video', 'previous_video', 'refresh_info'):
            message = None
        elif action == 'read_author':
            message = 'Autor: ' + data.get('author', 'Não encontrado')
        elif action == 'read_description':
            message = 'Descrição: ' + data.get('description', 'Não encontrada')
        elif action == 'copy_link' and active:
            if result.get('nativeCopied'):
                self.status('Link copiado.')
                return
            self._copy_link(name, result.get('link'))
            return
        elif action in ('toggle_playback', 'play'):
            message = 'Vídeo pausado.' if result.get('paused') else 'Reproduzindo vídeo.'
        elif action in ('volume_up', 'volume_down'):
            message = f"Volume: {round(result.get('volume', 0) * 100)}%."
        elif action in ('speed_up', 'speed_down'):
            rate = f"{result.get('playbackRate', 1):g}".replace('.', ',')
            message = f"Velocidade: {rate}x."
        elif action == 'toggle_mute':
            message = 'Som desativado.' if result.get('muted') else 'Som ativado.'
        elif action == 'toggle_like':
            message = 'Curtida adicionada.' if result.get('state') else 'Curtida removida.'
        elif action == 'toggle_favorite':
            message = 'Vídeo salvo.' if result.get('state') else 'Vídeo removido dos salvos.'
        elif action == 'open_comments' and active:
            self.activities.SetSelection(1)
            self.current().SetCanFocus(False)
            self.comments_list.SetFocus()
            message = f"{len(data.get('comments', []))} comentários carregados."
        elif action == 'close_comments' and active:
            self.focus_controls()
            return
        elif action == 'collect_search_results' and active:
            self.activities.SetSelection(2)
            self.results_list.SetFocus()
            message = f'{len(self._results)} resultados. Selecione um e pressione Enter para abrir.'
        elif action == 'diagnostics':
            message = result.get('message', 'Página incorporada conectada.')
        if active and message:
            self.status(message)

    def _copy_link(self, name, value):
        try:
            link = (validate_search_result_url if name == 'TikTok' else validate_reel_url)(value)
        except (ValueError, VideoControlError):
            self.status('Não foi possível identificar um link válido para o vídeo.')
            return
        success = _copy_text_to_clipboard(link)
        self.status('Link copiado.' if success else 'Não foi possível copiar o link.')

    def search(self, event=None):
        query = self.query_field.GetValue().strip()
        if not query:
            self.status('Digite o que deseja pesquisar.')
            return
        if not self.current():
            self.status('Use Ctrl+1 para abrir TikTok ou Ctrl+2 para abrir Instagram.')
            return
        name = self._active_name
        if self.clients[name].pending:
            self.status('Aguarde o comando anterior.')
            return
        url = search_url(query) if name == 'TikTok' else 'https://www.instagram.com/explore/search/keyword/?q=' + quote_plus(query)
        self.clients[name].navigate(url, lambda: self.dispatch('collect_search_results') if name == self._active_name else None)
        self.status('Carregando pesquisa no ' + name + '...')

    def open_result(self, event=None):
        index = self.results_list.GetSelection()
        if not 0 <= index < len(self._results):
            self.status('Selecione um resultado da pesquisa.')
            return
        if self.clients[self._active_name].pending:
            self.status('Aguarde o comando anterior.')
            return
        self.clients[self._active_name].navigate(self._results[index].url)
        self.focus_controls()

    def _closing(self, event):
        self._closing_app = True
        self._release_hotkey()
        for client in self.clients.values():
            client.close()
        event.Skip()
