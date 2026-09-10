import json
import os
import subprocess
import sys
from pathlib import Path

import wx

from video_download import settings_path

class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Configurações", size=(500, 350))
        
        self.settings_file = settings_path()
        self.current_folder = Path.home() / 'Downloads'
        self.check_ytdlp = True
        
        self._load_settings()
        
        self._build_ui()
        
    def _load_settings(self):
        try:
            value = json.loads(self.settings_file.read_text(encoding='utf-8'))
            folder = value.get('folder')
            if folder and Path(folder).is_absolute():
                self.current_folder = Path(folder)
            self.check_ytdlp = value.get('check_ytdlp_updates', True)
        except Exception:
            pass

    def _save_settings(self):
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            data = {'folder': str(self.current_folder), 'check_ytdlp_updates': self.check_ytdlp}
            self.settings_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            wx.MessageBox(f"Não foi possível salvar as configurações: {e}", "Erro", wx.OK | wx.ICON_ERROR, self)

    def _build_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Pasta de download
        vbox.Add(wx.StaticText(panel, label="Pasta de Download dos Vídeos:"), 0, wx.ALL, 5)
        
        hbox_folder = wx.BoxSizer(wx.HORIZONTAL)
        self.folder_text = wx.TextCtrl(panel, value=str(self.current_folder), style=wx.TE_READONLY)
        hbox_folder.Add(self.folder_text, 1, wx.EXPAND | wx.RIGHT, 5)
        
        btn_browse = wx.Button(panel, label="&Alterar Pasta...")
        btn_browse.Bind(wx.EVT_BUTTON, self.on_browse)
        hbox_folder.Add(btn_browse, 0, wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(hbox_folder, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        vbox.AddSpacer(10)
        
        # Auto update checkbox
        self.cb_auto_update = wx.CheckBox(panel, label="Verificar a&tualizações do motor de download automaticamente ao abrir")
        self.cb_auto_update.SetValue(self.check_ytdlp)
        vbox.Add(self.cb_auto_update, 0, wx.ALL, 5)
        
        vbox.AddSpacer(10)
        
        # Manual update button
        btn_update = wx.Button(panel, label="Verificar atualização do motor a&gora")
        btn_update.Bind(wx.EVT_BUTTON, self.on_manual_update)
        vbox.Add(btn_update, 0, wx.ALL, 5)
        
        vbox.AddSpacer(20)
        
        # Bottom buttons
        hbox_buttons = wx.BoxSizer(wx.HORIZONTAL)
        btn_save = wx.Button(panel, label="&Salvar e Fechar")
        btn_save.Bind(wx.EVT_BUTTON, self.on_save)
        
        btn_cancel = wx.Button(panel, id=wx.ID_CANCEL, label="Cancelar")
        
        hbox_buttons.Add(btn_save, 0, wx.RIGHT, 5)
        hbox_buttons.Add(btn_cancel, 0)
        
        vbox.Add(hbox_buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        
        panel.SetSizer(vbox)
        
    def on_browse(self, event):
        dlg = wx.DirDialog(self, "Escolha a pasta de destino dos vídeos", defaultPath=str(self.current_folder))
        if dlg.ShowModal() == wx.ID_OK:
            self.current_folder = Path(dlg.GetPath())
            self.folder_text.SetValue(str(self.current_folder))
        dlg.Destroy()
        self.folder_text.SetFocus()

    def on_manual_update(self, event):
        frozen = getattr(sys, 'frozen', False)
        root_dir = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent.parent
        exe_name = 'yt-dlp.exe' if os.name == 'nt' else 'yt-dlp'
        exe_path = root_dir / exe_name
        
        if not exe_path.is_file():
            wx.MessageBox("O arquivo executável do motor (yt-dlp) não foi encontrado na pasta do projeto.", "Erro", wx.OK | wx.ICON_ERROR, self)
            return
            
        dlg = wx.ProgressDialog("Atualizando Motor", "Buscando atualizações...", maximum=100, parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        dlg.Pulse()
        
        def worker():
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                process = subprocess.run([str(exe_path), "-U"], capture_output=True, text=True, creationflags=creationflags)
                wx.CallAfter(finish, process.returncode, process.stdout + "\n" + process.stderr)
            except Exception as e:
                wx.CallAfter(finish_error, e)

        def finish(returncode, output):
            dlg.Destroy()
            if "up to date" in output or "up-to-date" in output:
                wx.MessageBox("O motor de downloads já está na versão mais recente!", "Atualizado", wx.OK | wx.ICON_INFORMATION, self)
            elif returncode == 0:
                wx.MessageBox("Motor de download atualizado com sucesso!", "Atualização Concluída", wx.OK | wx.ICON_INFORMATION, self)
            else:
                wx.MessageBox(f"Ocorreu um erro na atualização:\n{output}", "Erro", wx.OK | wx.ICON_ERROR, self)

        def finish_error(e):
            dlg.Destroy()
            wx.MessageBox(f"Erro ao executar atualizador: {e}", "Erro", wx.OK | wx.ICON_ERROR, self)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def on_save(self, event):
        self.check_ytdlp = self.cb_auto_update.GetValue()
        self._save_settings()
        self.EndModal(wx.ID_OK)
