from __future__ import annotations

import wx

from app_logging import configure_logging, install_exception_logging
from ui.app_frame import MainFrame


def main() -> None:
    configure_logging()
    install_exception_logging()
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
