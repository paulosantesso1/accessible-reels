"""Run with python -m tests.webview_native_smoke (Windows desktop required)."""
import os
import tempfile
import wx
import wx.html2 as html2
from ui.webview_native import evaluate, click


def main():
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = tempfile.mkdtemp(prefix='reels-webview-test-')
    app = wx.App(False)
    frame = wx.Frame(None, title='Teste local WebView2', size=(500, 400))
    view = html2.WebView.New(frame, backend=html2.WebViewBackendEdge)
    failures = ['Não recebeu resposta em 15 segundos.']
    def finish(value, error):
        failures[:] = [str(error or value)] if error or value is not True else []
        print('WebView2 native trusted click:', 'PASS' if not failures else failures, flush=True)
        frame.Close()
    def ready(event):
        if view.GetCurrentURL() != 'about:blank':
            return
        evaluate(view, "document.body.innerHTML = '<button style=\"width:150px;height:80px\" onclick=\"window.trusted=event.isTrusted\">Teste local</button>'; true",
                 lambda value, error: click(view, 50, 40, lambda ok, error:
                     evaluate(view, 'window.trusted === true', finish) if ok else finish(None, error)))
    view.Bind(html2.EVT_WEBVIEW_LOADED, ready)
    frame.Show()
    view.LoadURL('about:blank')
    wx.CallLater(15000, lambda: frame.Close() if frame else None)
    app.MainLoop()
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
