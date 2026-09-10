import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import wx
import pytest

from ui.settings_dialog import SettingsDialog

@pytest.fixture
def mock_settings_file(tmp_path):
    settings_file = tmp_path / "download-settings.json"
    with patch("ui.settings_dialog.settings_path", return_value=settings_file):
        yield settings_file

def test_settings_dialog_loads_default_values(mock_settings_file):
    app = wx.App(clearSigInt=False)
    dialog = SettingsDialog(None)
    
    assert dialog.check_ytdlp is True
    assert dialog.current_folder == Path.home() / 'Downloads'
    assert dialog.cb_auto_update.GetValue() is True
    
    dialog.Destroy()
    app.Destroy()

def test_settings_dialog_loads_saved_values(mock_settings_file):
    mock_settings_file.write_text(json.dumps({
        "folder": "C:\\Teste\\Pasta",
        "check_ytdlp_updates": False
    }), encoding="utf-8")
    
    app = wx.App(clearSigInt=False)
    dialog = SettingsDialog(None)
    
    assert dialog.check_ytdlp is False
    assert str(dialog.current_folder) == "C:\\Teste\\Pasta"
    assert dialog.cb_auto_update.GetValue() is False
    
    dialog.Destroy()
    app.Destroy()

def test_settings_dialog_saves_values(mock_settings_file):
    app = wx.App(clearSigInt=False)
    dialog = SettingsDialog(None)
    
    dialog.current_folder = Path("D:\\Nova\\Pasta")
    dialog.cb_auto_update.SetValue(False)
    
    with patch.object(dialog, 'EndModal') as mock_end_modal:
        dialog.on_save(None)
        mock_end_modal.assert_called_once_with(wx.ID_OK)
        
    saved_data = json.loads(mock_settings_file.read_text(encoding="utf-8"))
    assert saved_data["folder"] == "D:\\Nova\\Pasta"
    assert saved_data["check_ytdlp_updates"] is False
    
    dialog.Destroy()
    app.Destroy()
