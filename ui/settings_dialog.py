import os
import sys
import threading
from pathlib import Path

import wx

from video_download import load_download_settings, save_download_settings, settings_path, update_ytdlp
from .shortcuts import (DEFAULT_SHORTCUTS, SHORTCUT_DEFINITIONS, can_be_global,
                        display_shortcut, load_shortcut_settings,
                        save_shortcut_settings, shortcut_from_event)


class ShortcutCaptureDialog(wx.Dialog):
    def __init__(self, parent, action_label):
        super().__init__(parent, title="Alterar atalho", size=(450, 190))
        self.value = None
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label=f"Novo atalho para {action_label}. Pressione a combinação desejada."), 0, wx.ALL, 15)
        self.feedback = wx.StaticText(panel, label="Aguardando atalho...")
        box.Add(self.feedback, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)
        cancel = wx.Button(panel, wx.ID_CANCEL, "Cancelar")
        box.Add(cancel, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        panel.SetSizer(box)
        self.Bind(wx.EVT_CHAR_HOOK, self._capture)

    def _capture(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        value = shortcut_from_event(event)
        if value:
            self.value = value
            self.EndModal(wx.ID_OK)
        else:
            self.feedback.SetLabel("Essa tecla não pode ser usada. Tente outra combinação.")


class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Configurações", size=(680, 520))
        self.settings_file = settings_path()
        self.current_folder = Path.home() / "Downloads"
        self.check_ytdlp = True
        self.shortcuts, self.global_shortcuts = load_shortcut_settings()
        self._initial_shortcuts = dict(self.shortcuts)
        self._initial_global_shortcuts = set(self.global_shortcuts)
        self._load_settings()
        self._build_ui()

    def _load_settings(self):
        try:
            value = load_download_settings(path=self.settings_file)
            folder = value.get("folder")
            if folder and Path(folder).is_absolute():
                self.current_folder = Path(folder)
            self.check_ytdlp = value.get("check_ytdlp_updates", True)
        except Exception:
            pass

    def _build_ui(self):
        root = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        notebook = wx.Notebook(root)
        notebook.AddPage(self._general_page(notebook), "&Geral")
        notebook.AddPage(self._shortcuts_page(notebook), "&Atalhos")
        outer.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        buttons = wx.StdDialogButtonSizer()
        save = wx.Button(root, wx.ID_OK, "&Salvar")
        cancel = wx.Button(root, wx.ID_CANCEL, "Cancelar")
        buttons.AddButton(save); buttons.AddButton(cancel); buttons.Realize()
        save.Bind(wx.EVT_BUTTON, self.on_save)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        root.SetSizer(outer)

    def _general_page(self, notebook):
        panel = wx.Panel(notebook)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label="Pasta de download dos vídeos:"), 0, wx.ALL, 5)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_text = wx.TextCtrl(panel, value=str(self.current_folder), style=wx.TE_READONLY)
        browse = wx.Button(panel, label="&Alterar pasta...")
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        row.Add(self.folder_text, 1, wx.RIGHT, 5); row.Add(browse)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 5)
        self.cb_auto_update = wx.CheckBox(panel, label="Verificar a&tualizações do motor de download automaticamente ao abrir")
        self.cb_auto_update.SetValue(self.check_ytdlp)
        box.Add(self.cb_auto_update, 0, wx.ALL, 5)
        update = wx.Button(panel, label="Verificar atualização do motor a&gora")
        update.Bind(wx.EVT_BUTTON, self.on_manual_update)
        box.Add(update, 0, wx.ALL, 5)
        panel.SetSizer(box)
        return panel

    def _shortcuts_page(self, notebook):
        panel = wx.Panel(notebook)
        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(wx.StaticText(panel, label="Atalhos. Marque um item para fazê-lo funcionar em todo o Windows:"), 0, wx.ALL, 5)
        self.shortcut_list = wx.CheckListBox(panel, choices=[])
        self.shortcut_list.Bind(wx.EVT_CHECKLISTBOX, self.on_toggle_global)
        box.Add(self.shortcut_list, 1, wx.EXPAND | wx.ALL, 5)
        row = wx.BoxSizer(wx.HORIZONTAL)
        change = wx.Button(panel, label="&Alterar atalho...")
        restore = wx.Button(panel, label="&Restaurar selecionado")
        restore_all = wx.Button(panel, label="Restaurar &todos")
        change.Bind(wx.EVT_BUTTON, self.on_change_shortcut)
        restore.Bind(wx.EVT_BUTTON, self.on_restore_shortcut)
        restore_all.Bind(wx.EVT_BUTTON, self.on_restore_all)
        row.Add(change, 0, wx.RIGHT, 5); row.Add(restore, 0, wx.RIGHT, 5); row.Add(restore_all)
        box.Add(row, 0, wx.ALL, 5)
        panel.SetSizer(box)
        self._refresh_shortcut_list(0)
        return panel

    def _refresh_shortcut_list(self, selected=-1):
        self.shortcut_list.Clear()
        for item in SHORTCUT_DEFINITIONS:
            self.shortcut_list.Append(f"{item.label}: {display_shortcut(self.shortcuts[item.action])}")
            self.shortcut_list.Check(self.shortcut_list.GetCount() - 1, item.action in self.global_shortcuts)
        if selected >= 0:
            self.shortcut_list.SetSelection(min(selected, self.shortcut_list.GetCount() - 1))

    def _selected_definition(self):
        index = self.shortcut_list.GetSelection()
        return (index, SHORTCUT_DEFINITIONS[index]) if index != wx.NOT_FOUND else (index, None)

    def on_change_shortcut(self, event):
        index, item = self._selected_definition()
        if item is None:
            wx.MessageBox("Selecione primeiro um comando.", "Atalhos", parent=self)
            return
        dialog = ShortcutCaptureDialog(self, item.label)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            duplicate = next((other.label for other in SHORTCUT_DEFINITIONS if other.action != item.action and self.shortcuts[other.action] == dialog.value), None)
            if duplicate:
                wx.MessageBox(f"Esse atalho já é usado por {duplicate}.", "Atalho duplicado", wx.OK | wx.ICON_WARNING, self)
                return
            self.shortcuts[item.action] = dialog.value
            if item.action in self.global_shortcuts and not can_be_global(dialog.value):
                self.global_shortcuts.discard(item.action)
            self._refresh_shortcut_list(index)
        finally:
            dialog.Destroy()

    def on_toggle_global(self, event):
        index = event.GetInt()
        item = SHORTCUT_DEFINITIONS[index]
        if self.shortcut_list.IsChecked(index) and not can_be_global(self.shortcuts[item.action]):
            self.shortcut_list.Check(index, False)
            wx.MessageBox("Para ser global, uma letra ou número precisa estar combinado com Ctrl, Alt ou Shift.",
                          "Atalho global", wx.OK | wx.ICON_INFORMATION, self)

    def on_restore_shortcut(self, event):
        index, item = self._selected_definition()
        if item:
            self.shortcuts[item.action] = DEFAULT_SHORTCUTS[item.action]
            self._refresh_shortcut_list(index)

    def on_restore_all(self, event):
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.global_shortcuts.clear()
        self._refresh_shortcut_list(0)

    def on_browse(self, event):
        dialog = wx.DirDialog(self, "Escolha a pasta de destino dos vídeos", defaultPath=str(self.current_folder))
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self.current_folder = Path(dialog.GetPath())
                self.folder_text.SetValue(str(self.current_folder))
        finally:
            dialog.Destroy()
        self.folder_text.SetFocus()

    def on_manual_update(self, event):
        frozen = getattr(sys, "frozen", False)
        root_dir = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent.parent
        exe_path = root_dir / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
        if not exe_path.is_file():
            wx.MessageBox("O executável do motor de download não foi encontrado.", "Erro", wx.OK | wx.ICON_ERROR, self)
            return
        progress = wx.ProgressDialog("Atualizando motor", "Buscando atualizações...", parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        progress.Pulse()
        def finish(message, error=False):
            progress.Destroy()
            wx.MessageBox(message, "Erro" if error else "Atualização concluída", wx.OK | (wx.ICON_ERROR if error else wx.ICON_INFORMATION), self)
        def worker():
            try:
                output = update_ytdlp(exe_path)
                message = "O motor já está na versão mais recente." if "up to date" in output or "up-to-date" in output else "Motor de download atualizado com sucesso!"
                wx.CallAfter(finish, message)
            except Exception as exc:
                wx.CallAfter(finish, f"Erro ao executar atualizador: {exc}", True)
        threading.Thread(target=worker, daemon=True).start()

    def on_save(self, event):
        checked = {item.action for index, item in enumerate(SHORTCUT_DEFINITIONS) if self.shortcut_list.IsChecked(index)}
        try:
            if self.shortcuts != self._initial_shortcuts or checked != self._initial_global_shortcuts:
                save_shortcut_settings(self.shortcuts, checked)
            save_download_settings({"folder": str(self.current_folder), "check_ytdlp_updates": self.cb_auto_update.GetValue()}, path=self.settings_file)
        except Exception as exc:
            wx.MessageBox(f"Não foi possível salvar as configurações: {exc}", "Erro", wx.OK | wx.ICON_ERROR, self)
            return
        self.EndModal(wx.ID_OK)
