from __future__ import annotations

import wx

from ui.app_frame import MainFrame


def main() -> None:
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
