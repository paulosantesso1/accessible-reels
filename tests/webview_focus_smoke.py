"""Windows focus integration test with an unfinished local page resource.

Run with python -m tests.webview_focus_smoke. No accounts are accessed.
"""
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import wx
import wx.html2 as html2
from ui.webview_focus import EmbeddedFocusMixin
from ui.webview_native import evaluate


def main():
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path == '/slow.png':
                release.wait(20)
                self.send_response(204)
                self.end_headers()
                return
            body = b'<!doctype html><title>Local login</title><input id="login" aria-label="User"><input aria-label="Password"><button>Enter</button><img src="/slow.png">'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = tempfile.mkdtemp(prefix='reels-focus-')
    app = wx.App(False)
    class Frame(EmbeddedFocusMixin, wx.Frame):
        def current(self): return self.view
        def status(self, message): print(message, flush=True)
    frame = Frame(None, title='Teste local de foco F6', size=(650, 450))
    panel = wx.Panel(frame)
    box = wx.BoxSizer(wx.VERTICAL)
    frame.play_button = wx.Button(panel, label='Controles do aplicativo')
    box.Add(frame.play_button)
    frame.view = html2.WebView.New(backend=html2.WebViewBackendEdge)
    frame._pending_page_focus = None
    frame.network = SimpleNamespace(GetStringSelection=lambda: 'Teste local')
    failures = []
    def report(value, error):
        print('PAGE:', value, 'error:', error, flush=True)
        if error or not value.get('focused') or value.get('id') != 'login': failures.append('page focus failed')
        frame.toggle_page_controls()
        wx.CallLater(300, returned)
    def returned():
        print('CONTROLS:', wx.Window.FindFocus() is frame.play_button, flush=True)
        if wx.Window.FindFocus() is not frame.play_button: failures.append('return failed')
        release.set()
        frame.Close()
    def ready(value, error):
        if error or not value:
            wx.CallLater(100, poll)
            return
        print('BUSY:', frame.view.IsBusy(), flush=True)
        if not frame.view.IsBusy(): failures.append('slow resource did not reproduce loading state')
        frame.play_button.SetFocus()
        frame.toggle_page_controls()
        wx.CallLater(500, lambda: evaluate(frame.view, '({focused:document.hasFocus(),id:document.activeElement.id})', report))
    def poll(): evaluate(frame.view, 'Boolean(document.getElementById("login"))', ready)
    frame.view.Create(panel, url=f'http://127.0.0.1:{server.server_port}/')
    frame.view.SetCanFocus(False)
    box.Add(frame.view, 1, wx.EXPAND)
    panel.SetSizer(box)
    frame.Show()
    wx.CallLater(200, poll)
    timer = wx.CallLater(15000, lambda: (failures.append('timeout'), release.set(), frame.Close()))
    app.MainLoop()
    timer.Stop()
    release.set()
    server.shutdown()
    server.server_close()
    print('FAILURES:', failures, flush=True)
    return bool(failures)

if __name__=='__main__': raise SystemExit(main())
