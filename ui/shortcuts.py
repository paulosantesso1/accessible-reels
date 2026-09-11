"""Atalhos compartilhados e sua apresentação aos leitores de tela."""

import wx

SEEK_SECONDS = {'seek_back_15': -15, 'seek_forward_15': 15,
                'seek_back_30': -30, 'seek_forward_30': 30}
SEEK_ACCELERATOR_SPECS = (
    ('seek_back_15', wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_LEFT),
    ('seek_forward_15', wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_RIGHT),
    ('seek_back_30', wx.ACCEL_ALT, wx.WXK_LEFT),
    ('seek_forward_30', wx.ACCEL_ALT, wx.WXK_RIGHT),
)


ACCELERATOR_SPECS = (
    ("next_video", wx.ACCEL_ALT, wx.WXK_DOWN),
    ("previous_video", wx.ACCEL_ALT, wx.WXK_UP),
    ("toggle_playback", wx.ACCEL_ALT, ord("P")),
    ("read_author", wx.ACCEL_ALT, ord("A")),
    ("read_description", wx.ACCEL_ALT, ord("D")),
    ("copy_link", wx.ACCEL_ALT, ord("C")),
    ("refresh_info", wx.ACCEL_NORMAL, wx.WXK_F5),
    ("open_settings", wx.ACCEL_NORMAL, wx.WXK_F2),
    ("search", wx.ACCEL_ALT, ord("E")),
    ("exit", wx.ACCEL_ALT, ord("S")),
    ("volume_up", wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_UP),
    ("volume_down", wx.ACCEL_ALT | wx.ACCEL_SHIFT, wx.WXK_DOWN),
    ("speed_down", wx.ACCEL_SHIFT, ord(",")),
    ("speed_up", wx.ACCEL_SHIFT, ord(".")),
    ("toggle_mute", wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("M")),
    ("diagnostics", wx.ACCEL_ALT, wx.WXK_F12),
    ("open_comments", wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("C")),
    ("toggle_like", wx.ACCEL_ALT, ord("L")),
    ("toggle_favorite", wx.ACCEL_ALT, ord("F")),
    ("open_profile", wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("P")),
)


def action_shortcut(action: str) -> str:
    _, modifiers, key = next(spec for spec in ACCELERATOR_SPECS + SEEK_ACCELERATOR_SPECS if spec[0] == action)
    parts = []
    if modifiers & wx.ACCEL_ALT:
        parts.append("Alt")
    if modifiers & wx.ACCEL_SHIFT:
        parts.append("Shift")
    names = {wx.WXK_UP: "Seta para cima", wx.WXK_DOWN: "Seta para baixo",
             wx.WXK_LEFT: "Seta para esquerda", wx.WXK_RIGHT: "Seta para direita",
             wx.WXK_F2: "F2", wx.WXK_F5: "F5", wx.WXK_F12: "F12",
             ord(","): "<", ord("."): ">"}
    parts.append(names.get(key, chr(key)))
    return "+".join(parts)


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
    """Complementa o controle nativo sem substituir seu papel, estado ou ação."""

    def __init__(self, control: wx.Window, shortcut: str) -> None:
        super().__init__(control)
        self.shortcut = shortcut

    def GetName(self, childId: int):
        if childId == 0:
            return wx.ACC_OK, self.GetWindow().GetName()
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetKeyboardShortcut(self, childId: int):
        if childId == 0:
            return wx.ACC_OK, self.shortcut
        return wx.ACC_NOT_IMPLEMENTED, ""


def set_shortcut(control: wx.Window, *, action: str | None = None,
                 shortcut: str | None = None) -> None:
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
