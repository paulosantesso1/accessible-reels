"""Catálogo, persistência e apresentação dos atalhos."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import wx


@dataclass(frozen=True)
class ShortcutDefinition:
    action: str
    label: str
    default: str


SHORTCUT_DEFINITIONS = (
    ShortcutDefinition("show_help", "Mostrar ajuda", "F1"),
    ShortcutDefinition("open_settings", "Abrir configurações", "F2"),
    ShortcutDefinition("refresh_info", "Atualizar informações", "F5"),
    ShortcutDefinition("toggle_page_controls", "Alternar entre aplicativo e página", "F6"),
    ShortcutDefinition("diagnostics", "Copiar diagnóstico", "Alt+F12"),
    ShortcutDefinition("select_tiktok", "Selecionar TikTok", "Ctrl+1"),
    ShortcutDefinition("select_instagram", "Selecionar Instagram", "Ctrl+2"),
    ShortcutDefinition("select_youtube", "Selecionar YouTube Shorts", "Ctrl+3"),
    ShortcutDefinition("open_selected_platform", "Abrir plataforma selecionada", "Ctrl+Enter"),
    ShortcutDefinition("open_link", "Abrir link", "Ctrl+O"),
    ShortcutDefinition("download_video", "Baixar vídeo", "Ctrl+B"),
    ShortcutDefinition("return_results", "Voltar aos resultados", "Ctrl+R"),
    ShortcutDefinition("home", "Ir para o início", "Ctrl+Home"),
    ShortcutDefinition("next_video", "Próximo vídeo", "Alt+Down"),
    ShortcutDefinition("previous_video", "Vídeo anterior", "Alt+Up"),
    ShortcutDefinition("toggle_playback", "Reproduzir ou pausar", "Alt+P"),
    ShortcutDefinition("seek_back_15", "Voltar 15 segundos", "Alt+Shift+Left"),
    ShortcutDefinition("seek_forward_15", "Avançar 15 segundos", "Alt+Shift+Right"),
    ShortcutDefinition("seek_back_30", "Voltar 30 segundos", "Alt+Left"),
    ShortcutDefinition("seek_forward_30", "Avançar 30 segundos", "Alt+Right"),
    ShortcutDefinition("volume_up", "Aumentar volume", "Alt+Shift+Up"),
    ShortcutDefinition("volume_down", "Diminuir volume", "Alt+Shift+Down"),
    ShortcutDefinition("speed_down", "Diminuir velocidade", "Shift+Comma"),
    ShortcutDefinition("speed_up", "Aumentar velocidade", "Shift+Period"),
    ShortcutDefinition("toggle_mute", "Ativar ou desativar som", "Alt+Shift+M"),
    ShortcutDefinition("read_author", "Ler autor", "Alt+A"),
    ShortcutDefinition("read_description", "Ler descrição", "Alt+D"),
    ShortcutDefinition("read_follow_status", "Ler estado de seguindo", "Alt+G"),
    ShortcutDefinition("copy_link", "Copiar link", "Alt+C"),
    ShortcutDefinition("open_comments", "Abrir comentários", "Alt+Shift+C"),
    ShortcutDefinition("toggle_like", "Curtir ou descurtir", "Alt+L"),
    ShortcutDefinition("toggle_favorite", "Favoritar ou desfavoritar", "Alt+F"),
    ShortcutDefinition("open_profile", "Abrir perfil", "Alt+Shift+P"),
    ShortcutDefinition("search", "Pesquisar", "Alt+E"),
    ShortcutDefinition("exit", "Sair", "Alt+S"),
)

DEFAULT_SHORTCUTS = {item.action: item.default for item in SHORTCUT_DEFINITIONS}
SEEK_SECONDS = {"seek_back_15": -15, "seek_forward_15": 15,
                "seek_back_30": -30, "seek_forward_30": 30}

_KEY_NAMES = {
    "UP": wx.WXK_UP, "DOWN": wx.WXK_DOWN, "LEFT": wx.WXK_LEFT,
    "RIGHT": wx.WXK_RIGHT, "HOME": wx.WXK_HOME, "ENTER": wx.WXK_RETURN,
    "COMMA": ord(","), "PERIOD": ord("."),
}
_DISPLAY_NAMES = {"Up": "Seta para cima", "Down": "Seta para baixo",
                  "Left": "Seta para esquerda", "Right": "Seta para direita",
                  "Comma": "<", "Period": ">"}


def settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Accessible Reels"
    return base / "shortcut-settings.json"


def normalize_shortcut(value: str) -> str:
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if not parts:
        raise ValueError("Atalho vazio")
    aliases = {"CONTROL": "Ctrl", "CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift"}
    modifiers = []
    key = None
    for part in parts:
        upper = part.upper()
        if upper in aliases:
            name = aliases[upper]
            if name not in modifiers:
                modifiers.append(name)
        elif key is None:
            if len(part) == 1 and part.isalnum():
                key = part.upper()
            elif upper in _KEY_NAMES or (upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24):
                key = upper.title() if upper in _KEY_NAMES else upper
            else:
                raise ValueError(f"Tecla não reconhecida: {part}")
        else:
            raise ValueError("O atalho contém mais de uma tecla")
    if key is None:
        raise ValueError("Escolha uma tecla além dos modificadores")
    ordered = [name for name in ("Ctrl", "Alt", "Shift") if name in modifiers]
    return "+".join(ordered + [key])


def display_shortcut(value: str) -> str:
    normalized = normalize_shortcut(value)
    parts = normalized.split("+")
    parts[-1] = _DISPLAY_NAMES.get(parts[-1], parts[-1])
    return "+".join(parts)


def shortcut_to_wx(value: str) -> tuple[int, int]:
    parts = normalize_shortcut(value).split("+")
    modifiers = wx.ACCEL_NORMAL
    if "Ctrl" in parts: modifiers |= wx.ACCEL_CTRL
    if "Alt" in parts: modifiers |= wx.ACCEL_ALT
    if "Shift" in parts: modifiers |= wx.ACCEL_SHIFT
    key_name = parts[-1]
    key = _KEY_NAMES.get(key_name.upper())
    if key is None and key_name.startswith("F") and key_name[1:].isdigit():
        key = wx.WXK_F1 + int(key_name[1:]) - 1
    if key is None:
        key = ord(key_name)
    return modifiers, key


def shortcut_to_windows(value: str) -> tuple[int, int]:
    parts = normalize_shortcut(value).split("+")
    modifiers = (0x0002 if "Ctrl" in parts else 0) | (0x0001 if "Alt" in parts else 0) | (0x0004 if "Shift" in parts else 0)
    key_name = parts[-1]
    special = {"Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
               "Home": 0x24, "Enter": 0x0D, "Comma": 0xBC, "Period": 0xBE}
    if key_name in special:
        key = special[key_name]
    elif key_name.startswith("F") and key_name[1:].isdigit():
        key = 0x70 + int(key_name[1:]) - 1
    else:
        key = ord(key_name)
    return modifiers | 0x4000, key


def shortcut_from_event(event) -> str | None:
    code = event.GetKeyCode()
    reverse = {value: name.title() for name, value in _KEY_NAMES.items()}
    if code in reverse:
        key = reverse[code]
    elif wx.WXK_F1 <= code <= wx.WXK_F24:
        key = f"F{code - wx.WXK_F1 + 1}"
    elif ord("A") <= code <= ord("Z") or ord("0") <= code <= ord("9"):
        key = chr(code)
    else:
        return None
    parts = []
    if event.ControlDown(): parts.append("Ctrl")
    if event.AltDown(): parts.append("Alt")
    if event.ShiftDown(): parts.append("Shift")
    return "+".join(parts + [key])


def can_be_global(value: str) -> bool:
    parts = normalize_shortcut(value).split("+")
    return len(parts) > 1 or (parts[-1].startswith("F") and parts[-1][1:].isdigit())


def load_shortcut_settings(path: Path | None = None) -> tuple[dict[str, str], set[str]]:
    shortcuts = dict(DEFAULT_SHORTCUTS)
    try:
        value = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        for action, shortcut in value.get("shortcuts", {}).items():
            if action in shortcuts:
                shortcuts[action] = normalize_shortcut(shortcut)
        globals_ = {action for action in value.get("global", []) if action in shortcuts and can_be_global(shortcuts[action])}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        globals_ = set()
    return shortcuts, globals_


def save_shortcut_settings(shortcuts: dict[str, str], globals_: set[str], path: Path | None = None) -> None:
    normalized = {action: normalize_shortcut(shortcuts.get(action, default)) for action, default in DEFAULT_SHORTCUTS.items()}
    duplicates = len(set(normalized.values())) != len(normalized)
    if duplicates:
        raise ValueError("Dois comandos não podem usar o mesmo atalho")
    invalid_globals = [action for action in globals_ if action not in normalized or not can_be_global(normalized[action])]
    if invalid_globals:
        raise ValueError("Atalhos globais com letras ou números precisam de Ctrl, Alt ou Shift")
    destination = path or settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"shortcuts": normalized, "global": sorted(globals_)}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)


def accelerator_specs(shortcuts: dict[str, str] | None = None):
    values = shortcuts or DEFAULT_SHORTCUTS
    return tuple((item.action, *shortcut_to_wx(values[item.action])) for item in SHORTCUT_DEFINITIONS)


_DEFAULT_SPECS = accelerator_specs()
SEEK_ACCELERATOR_SPECS = tuple(spec for spec in _DEFAULT_SPECS if spec[0] in SEEK_SECONDS)
ACCELERATOR_SPECS = tuple(spec for spec in _DEFAULT_SPECS if spec[0] not in SEEK_SECONDS)


def action_shortcut(action: str, shortcuts: dict[str, str] | None = None) -> str:
    return display_shortcut((shortcuts or DEFAULT_SHORTCUTS)[action])


def mnemonic_shortcut(label: str) -> str:
    index = 0
    while index < len(label) - 1:
        if label[index] == "&":
            if label[index + 1] != "&":
                return f"Alt+{label[index + 1].upper()}"
            index += 1
        index += 1
    return ""


class ShortcutAccessible(wx.Accessible):
    def __init__(self, control: wx.Window, shortcut: str) -> None:
        super().__init__(control)
        self.shortcut = shortcut

    def GetName(self, childId: int):
        return (wx.ACC_OK, self.GetWindow().GetName()) if childId == 0 else (wx.ACC_NOT_IMPLEMENTED, "")

    def GetKeyboardShortcut(self, childId: int):
        return (wx.ACC_OK, self.shortcut) if childId == 0 else (wx.ACC_NOT_IMPLEMENTED, "")


def set_shortcut(control: wx.Window, *, action: str | None = None, shortcut: str | None = None) -> None:
    if action is not None:
        shortcut = action_shortcut(action)
    if shortcut is None:
        shortcut = mnemonic_shortcut(control.GetLabel())
    if not shortcut:
        return
    accessible = getattr(control, "_shortcut_accessible", None)
    if accessible is None:
        accessible = ShortcutAccessible(control, shortcut)
        control.SetAccessible(accessible)
        control._shortcut_accessible = accessible
    else:
        accessible.shortcut = shortcut
