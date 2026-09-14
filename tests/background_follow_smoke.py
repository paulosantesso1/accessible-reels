"""Account-free check of DevTools clicks in a hidden WebView2 viewport."""
import os
import tempfile

import wx
import wx.html2 as html2

from ui.webview_native import evaluate, click


def main():
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = tempfile.mkdtemp(prefix='reels-hidden-smoke-')
    app = wx.App(False)
    frame = wx.Frame(None, size=(1000, 800))
    panel = wx.Panel(frame, size=(1000, 800))
    panel.Hide()
    view = html2.WebView.New(backend=html2.WebViewBackendEdge)
    outcomes = []

    def finish(ok, error=None):
        if outcomes:
            return
        outcomes.append(bool(ok))
        print('Hidden WebView2 click:', 'PASS' if ok else 'FAIL', error or '', flush=True)
        frame.Destroy()
        app.ExitMainLoop()

    def clicked(ok, error):
        if not ok:
            finish(False, error)
            return
        evaluate(view, 'window.clicked === true', lambda value, err: finish(value is True, err))

    def prepared(value, error):
        if error:
            finish(False, error)
            return
        click(view, 50, 30, clicked)

    def loaded(event):
        evaluate(view, "document.body.innerHTML = '<button style=\"position:fixed;left:0;top:0;width:100px;height:60px\" onclick=\"window.clicked=true\">Follow</button>'; true", prepared)

    view.Bind(html2.EVT_WEBVIEW_LOADED, loaded)
    view.Create(panel, size=(1000, 800))
    wx.CallLater(1500, view.LoadURL, 'about:blank')
    wx.CallLater(15000, finish, False, 'timeout')
    app.MainLoop()
    assert outcomes == [True], outcomes


if __name__ == '__main__':
    main()
