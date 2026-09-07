"""Accessible controls and embedded social pages in one application window."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import wx
import wx.html2 as html2
from wx.lib.scrolledpanel import ScrolledPanel

from ui.webview_focus import EmbeddedFocusMixin, FOCUS_PAGE_HOTKEY, FOCUS_CONTROLS_HOTKEY
from ui.webview_client import WebViewClient, PLATFORM_URLS
from ui.video_link import parse_video_link
from ui.shortcuts import ACCELERATOR_SPECS, SEEK_ACCELERATOR_SPECS, SEEK_SECONDS, set_shortcut
from ui.nvda_announcer import speak_with_accessible_output, speak_with_nvda, raise_uia_notification
from tiktok.search import search_url, normalize_search_results, validate_search_result_url
from instagram.search import normalize_reel_results, validate_reel_url
from tiktok.video_controls import VideoControlError
from updater import UpdateError, can_self_update, check_for_update, download_update, launch_installer

COMMANDS = {'next_video':'next', 'previous_video':'previous', 'toggle_playback':'toggle',
            'read_author':'author', 'read_description':'description', 'open_comments':'comments'}


class MainFrame(EmbeddedFocusMixin, wx.Frame):
    def __init__(self, *, auto_open=False):
        super().__init__(None, title='Accessible Reels', size=(1180, 850))
        data_root = (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Accessible Reels'
                     if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1] / 'data')
        profile = data_root / 'webview_profile'
        profile.mkdir(parents=True, exist_ok=True)
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(profile)
        self.views, self.clients, self.platform_data = {}, {}, {}
        self._active_name = 'TikTok'
        self._pending_page_focus = None
        self._closing_app = False
        self._update_checking = False
        self._registered_hotkeys = set()
        self._accelerator_ids = {}
        self._results = ()
        self.CreateStatusBar()
        self.panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.network = wx.RadioBox(self.panel, label='Rede social', choices=['TikTok', 'Instagram'])
        self.network.SetHelpText('Escolha a rede e pressione Logar / abrir rede selecionada. Seu login salvo será reutilizado.')
        layout.Add(self.network, 0, wx.EXPAND | wx.ALL, 6)
        self.status_field = wx.StaticText(self.panel, label='Pronto.')
        self.status_field.SetName('Status do aplicativo')
        layout.Add(self.status_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.activities = wx.Notebook(self.panel, size=(440, -1))
        self.activities.SetMinSize((420, -1))
        self.activities.SetName('Atividades: vídeo, comentários e pesquisa')
        row.Add(self.activities, 0, wx.EXPAND | wx.ALL, 5)
        self.content = wx.BoxSizer(wx.VERTICAL)
        self.hint = wx.StaticText(self.panel, label='Escolha a rede e pressione Logar / abrir rede selecionada.')
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
        self.network.Bind(wx.EVT_RADIOBOX, self.select_network)
        self.Bind(wx.EVT_HOTKEY, self.focus_page, id=FOCUS_PAGE_HOTKEY)
        self.Bind(wx.EVT_HOTKEY, self.focus_controls, id=FOCUS_CONTROLS_HOTKEY)
        self.Bind(wx.EVT_ACTIVATE, self._activation_changed)
        self.Bind(wx.EVT_CLOSE, self._closing)
        self.Bind(wx.EVT_CHAR_HOOK, self._plain_shortcuts)
        self.status('Escolha a rede e pressione Logar / abrir rede selecionada. F6 entra na página; Shift+F6 retorna aos controles.')
        self.network.SetFocus()
        if can_self_update():
            wx.CallLater(2000, self._check_for_updates)
        if auto_open:
            wx.CallAfter(self.open_network)

    def _button(self, parent, label, handler, action=None):
        button = wx.Button(parent, label=label)
        button.SetName(label.replace('&', ''))
        set_shortcut(button, action=action) if action else set_shortcut(button)
        button.Bind(wx.EVT_BUTTON, handler)
        return button

    def _build_video_controls(self):
        page = ScrolledPanel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, handler in [('Logar / abrir rede selecionada', self.open_network),
                               ('Abrir link a partir de uma URL...', self.open_link),
                               ('Voltar ao feed', self.home),
                               ('Página / login — F6', self.focus_page), ('Recarregar página', self.reload),
                               ('Verificar atualizações', self.on_check_for_updates)]:
            sizer.Add(self._button(page, label, handler), 0, wx.EXPAND | wx.ALL, 3)
        sizer.Add(wx.StaticText(page, label='Autor:'), 0, wx.LEFT, 4)
        self.author_field = wx.TextCtrl(page, style=wx.TE_READONLY)
        self.author_field.SetName('Autor do vídeo atual, somente leitura')
        sizer.Add(self.author_field, 0, wx.EXPAND | wx.ALL, 3)
        sizer.Add(wx.StaticText(page, label='Descrição:'), 0, wx.LEFT, 4)
        self.description_field = wx.TextCtrl(page, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 90))
        self.description_field.SetName('Descrição do vídeo atual, somente leitura')
        sizer.Add(self.description_field, 0, wx.EXPAND | wx.ALL, 3)
        grid = wx.GridSizer(cols=2, vgap=5, hgap=5)
        for label, action in [
            ('Vídeo anterior', 'previous_video'), ('Próximo vídeo', 'next_video'),
            ('Reproduzir ou pausar', 'toggle_playback'), ('Atualizar informações', 'refresh_info'),
            ('Voltar 15 segundos', 'seek_back_15'), ('Avançar 15 segundos', 'seek_forward_15'),
            ('Voltar 30 segundos', 'seek_back_30'), ('Avançar 30 segundos', 'seek_forward_30'),
            ('Ler autor', 'read_author'), ('Ler descrição', 'read_description'),
            ('Diminuir volume', 'volume_down'), ('Aumentar volume', 'volume_up'),
            ('Ativar ou desativar mudo', 'toggle_mute'), ('Copiar link', 'copy_link'),
            ('Curtir ou descurtir', 'toggle_like'), ('Salvar ou remover dos salvos', 'toggle_favorite'),
            ('Comentários', 'open_comments'), ('Pesquisar vídeos', 'search'),
        ]:
            button = self._button(page, label, lambda e, a=action: self.dispatch(a), action)
            if action == 'toggle_playback':
                self.play_button = button
            grid.Add(button, 0, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 3)
        sizer.Add(self._button(page, '&Sair', lambda e: self.Close(), 'exit'), 0, wx.EXPAND | wx.ALL, 3)
        page.SetSizer(sizer)
        page.SetupScrolling(scroll_x=False)
        self.activities.AddPage(page, 'Vídeo')

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

    def _build_comments(self):
        page = wx.Panel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label='Comentários do vídeo atual:'), 0, wx.ALL, 5)
        self.comments_field = wx.TextCtrl(page, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.comments_field.SetName('Comentários, somente leitura')
        sizer.Add(self.comments_field, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self._button(page, 'Carregar comentários', lambda e: self.dispatch('open_comments')), 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(page, label='Escrever comentário:'), 0, wx.LEFT, 5)
        self.comment_input = wx.TextCtrl(page, style=wx.TE_MULTILINE, size=(-1, 100))
        self.comment_input.SetName('Escrever comentário; envio somente pelo botão Publicar')
        sizer.Add(self.comment_input, 0, wx.EXPAND | wx.ALL, 5)
        self.publish_button = self._button(page, 'Publicar comentário', self.publish_comment)
        sizer.Add(self.publish_button, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self._button(page, 'Fechar comentários', lambda e: self.dispatch('close_comments')), 0, wx.EXPAND | wx.ALL, 5)
        page.SetSizer(sizer)
        self.activities.AddPage(page, 'Comentários')

    def _build_search(self):
        page = wx.Panel(self.activities)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(page, label='Pesquisar vídeos:'), 0, wx.ALL, 5)
        self.query_field = wx.TextCtrl(page, style=wx.TE_PROCESS_ENTER)
        self.query_field.SetName('Termo da pesquisa')
        self.query_field.Bind(wx.EVT_TEXT_ENTER, self.search)
        sizer.Add(self.query_field, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self._button(page, 'Pesquisar', self.search), 0, wx.EXPAND | wx.ALL, 5)
        self.results_list = wx.ListBox(page)
        self.results_list.SetName('Resultados da pesquisa')
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self.open_result)
        sizer.Add(self.results_list, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self._button(page, 'Abrir vídeo selecionado', self.open_result), 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self._button(page, 'Atualizar resultados', lambda e: self.dispatch('collect_search_results')), 0, wx.EXPAND | wx.ALL, 5)
        page.SetSizer(sizer)
        self.activities.AddPage(page, 'Pesquisa')

    def _configure_accelerators(self):
        entries = []
        for action, modifiers, key in ACCELERATOR_SPECS + SEEK_ACCELERATOR_SPECS:
            if modifiers == wx.ACCEL_NORMAL and key in (ord('C'), ord('L'), ord('F')):
                continue  # Preserve typing in comment/search editors.
            identifier = wx.NewIdRef()
            self._accelerator_ids[action] = identifier
            self.Bind(wx.EVT_MENU, lambda e, a=action: self.dispatch(a), id=identifier)
            entries.append((modifiers, key, identifier))
        for modifiers, callback in [(wx.ACCEL_NORMAL, self.focus_page), (wx.ACCEL_SHIFT, self.focus_controls)]:
            identifier = wx.NewIdRef()
            self.Bind(wx.EVT_MENU, callback, id=identifier)
            entries.append((modifiers, wx.WXK_F6, identifier))
        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def _plain_shortcuts(self, event):
        focused = wx.Window.FindFocus()
        if (event.HasAnyModifiers() or isinstance(focused, wx.TextCtrl) and focused.IsEditable()
                or focused is self.current()):
            event.Skip()
            return
        action = {ord('C'):'open_comments', ord('L'):'toggle_like', ord('F'):'toggle_favorite'}.get(event.GetKeyCode())
        if action:
            self.dispatch(action)
        else:
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
        if self._active_name in self.platform_data:
            self.platform_data[self._active_name]['draft'] = self.comment_input.GetValue()
        self._pending_page_focus = None
        self._active_name = name
        for platform, view in self.views.items():
            self.clients[platform].set_active(platform == name)
            view.Show(platform == name)
        self.hint.Show(self.current() is None)
        self._restore_fields()
        self.panel.Layout()
        self.status(f'{name} selecionado. Pressione Logar / abrir rede selecionada.' if not self.current()
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
            self.status('Microsoft Edge WebView2 Runtime indisponível neste Windows.')
            return
        self._pending_page_focus = None
        if self._active_name in self.platform_data:
            self.platform_data[self._active_name]['draft'] = self.comment_input.GetValue()
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
            if not view.Create(self.panel):
                self.status('Não foi possível criar a página incorporada.')
                client.close()
                del self.views[name], self.clients[name], self.platform_data[name]
                return
            client.initialize()
            self.content.Add(view, 1, wx.EXPAND)
        elif url:
            self.clients[name].navigate(url, after_load)
        self.current().Show()
        self._restore_fields()
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
        self.author_field.ChangeValue(data.get('author', ''))
        self.description_field.ChangeValue(data.get('description', ''))
        self.comment_input.ChangeValue(data.get('draft', ''))
        self.comments_field.ChangeValue('\n\n'.join(data.get('comments', [])))
        self._results = data.get('results', ())
        self.results_list.Set([item.label for item in self._results])
        if self._results:
            self.results_list.SetSelection(0)

    def _platform_error(self, platform, message):
        if platform == self._active_name:
            self.status(message)

    def loaded(self, platform):
        if platform != self._active_name or self._closing_app:
            return
        if self._pending_page_focus is self.current():
            wx.CallAfter(self._enter_page, self.current())
        else:
            self.status(f'{platform} carregado. F5 atualiza autor e descrição; F6 entra na página.')

    def home(self, event=None):
        if not self.current():
            self.status('Escolha a rede e pressione Logar / abrir rede selecionada.')
        elif not self.clients[self._active_name].pending:
            self.clients[self._active_name].navigate(PLATFORM_URLS[self._active_name])
        else:
            self.status('Aguarde o comando anterior.')

    def reload(self, event=None):
        if self.current():
            self.current().Reload()
        else:
            self.status('Escolha a rede e pressione Logar / abrir rede selecionada.')

    def new_window(self, event):
        if urlsplit(event.GetURL()).scheme == 'https':
            event.GetEventObject().LoadURL(event.GetURL())
        else:
            self.status('Esse link exige um aplicativo externo e não foi aberto.')

    def dispatch(self, action, argument=None):
        if action == 'exit':
            self.Close()
            return
        if action == 'search':
            self.activities.SetSelection(2)
            self.query_field.SetFocus()
            return
        if not self.current():
            self.status('Escolha a rede e pressione Logar / abrir rede selecionada.')
            return
        name = self._active_name
        client = self.clients[name]
        if client.pending:
            return
        focused = wx.Window.FindFocus()
        restore_focus = focused if focused and focused is not self.current() else None
        self.status('Executando comando no ' + name + '...')
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
            self._platform_error(name, result.get('error') or 'A rede não confirmou o comando.')
            return
        data = self.platform_data[name]
        for field in ('author', 'description', 'link', 'comments'):
            if field in result:
                data[field] = result[field]
        active = name == self._active_name
        if 'results' in result:
            normalize = normalize_search_results if name == 'TikTok' else normalize_reel_results
            data['results'] = normalize(result['results'])
        if active:
            data['draft'] = self.comment_input.GetValue()
            self._restore_fields()
        message = 'Comando concluído.'
        if action in SEEK_SECONDS:
            position = round(result.get('position', 0))
            message = f'Posição: {position // 60} minutos e {position % 60} segundos.'
        if action in ('next_video', 'previous_video', 'refresh_info'):
            message = f"{data.get('author', '')}. {data.get('description', '')}"
        elif action == 'read_author':
            message = 'Autor: ' + data.get('author', 'Não encontrado')
        elif action == 'read_description':
            message = 'Descrição: ' + data.get('description', 'Não encontrada')
        elif action == 'copy_link' and active:
            self._copy_link(name, result.get('link'))
            return
        elif action in ('toggle_playback', 'play'):
            message = 'Vídeo pausado.' if result.get('paused') else 'Reproduzindo vídeo.'
        elif action in ('volume_up', 'volume_down'):
            message = f"Volume: {round(result.get('volume', 0) * 100)}%."
        elif action == 'toggle_mute':
            message = 'Som desativado.' if result.get('muted') else 'Som ativado.'
        elif action == 'toggle_like':
            message = 'Curtida adicionada.' if result.get('state') else 'Curtida removida.'
        elif action == 'toggle_favorite':
            message = 'Vídeo salvo.' if result.get('state') else 'Vídeo removido dos salvos.'
        elif action == 'open_comments' and active:
            self.activities.SetSelection(1)
            self.comments_field.SetInsertionPoint(0)
            self.comments_field.SetFocus()
            message = f"{len(data.get('comments', []))} comentários carregados."
        elif action == 'close_comments' and active:
            self.focus_controls()
            return
        elif action == 'post_comment':
            if active and self.comment_input.GetValue().strip() == argument:
                self.comment_input.ChangeValue('')
                data['draft'] = ''
            message = 'Comentário publicado e confirmado na página.'
        elif action == 'collect_search_results' and active:
            self.activities.SetSelection(2)
            self.results_list.SetFocus()
            message = f'{len(self._results)} resultados. Selecione um e pressione Abrir vídeo selecionado.'
        elif action == 'diagnostics':
            message = result.get('message', 'Página incorporada conectada.')
        if active:
            self.status(message)

    def _copy_link(self, name, value):
        try:
            link = (validate_search_result_url if name == 'TikTok' else validate_reel_url)(value)
        except (ValueError, VideoControlError):
            self.status('Não foi possível identificar um link válido para o vídeo.')
            return
        if not wx.TheClipboard.Open():
            self.status('A área de transferência está ocupada.')
            return
        try:
            success = wx.TheClipboard.SetData(wx.TextDataObject(link))
        finally:
            wx.TheClipboard.Close()
        self.status('Link copiado.' if success else 'Não foi possível copiar o link.')

    def publish_comment(self, event=None):
        text = self.comment_input.GetValue().strip()
        if not text:
            self.status('Digite um comentário antes de publicar.')
            return
        self.dispatch('post_comment', text)

    def search(self, event=None):
        query = self.query_field.GetValue().strip()
        if not query:
            self.status('Digite o que deseja pesquisar.')
            return
        if not self.current():
            self.status('Escolha a rede e pressione Logar / abrir rede selecionada.')
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
