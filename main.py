from __future__ import annotations

from app_logging import configure_logging, install_exception_logging
from webview_runtime import configure_runtime
import sys


def main() -> None:
    configure_logging()
    install_exception_logging()
    link_server = None
    if '--check-runtime' not in sys.argv:
        from link_router import route_launch
        link_server = route_launch(sys.argv)
        if link_server is None:
            return
    try:
        configure_runtime()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        from app_logging import get_logger
        get_logger().exception('WebView2 configuration failed')
        if '--check-runtime' in sys.argv:
            sys.exit(1)
        import wx
        app = wx.App(False)
        wx.MessageBox(str(error), 'Falha no runtime', wx.OK | wx.ICON_ERROR)
        return
    if '--check-runtime' in sys.argv:
        from webview_runtime import check_runtime
        sys.exit(check_runtime())
    import wx
    from ui.app_frame import MainFrame
    app = wx.App(False)
    frame = MainFrame()
    frame.attach_link_server(link_server)
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
