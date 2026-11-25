"""Exercise the real login window against a local, account-free page.

Run with: python -m tests.login_window_smoke
"""
import http.server
import os
import tempfile
import threading
from unittest.mock import patch

os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='reels-login-test-')

import wx
import wx.html2 as html2

from ui import app_frame as module
from ui.webview_native import call_devtools, evaluate

PAGES = {
    '/': b'<script>window.got = ""; addEventListener("message", e => { window.got = e.data; });</script>',
    # What a provider does: hand the result to the page and close its window.
    '/login': b'<script>if (window.opener) { window.opener.postMessage("login-ok", "*");'
              b'setTimeout(() => window.close(), 500); }</script>',
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(PAGES.get(self.path, b''))

    def log_message(self, *args):
        pass


def main():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    app = wx.App(False)
    results = {}
    statuses = []
    with patch.object(module.MainFrame, 'status', lambda self, message, *a, **k: statuses.append(message)), \
            patch.object(module.MainFrame, 'RegisterHotKey', lambda *a, **k: True), \
            patch.object(module.MainFrame, '_show_new_release_notes_if_needed', lambda *a, **k: None):
        frame = module.MainFrame()
        frame._active_name = 'TikTok'
        view = html2.WebView.New(backend=html2.WebViewBackendEdge)
        # new_window only accepts https; the local page stands for it.
        view.Bind(html2.EVT_WEBVIEW_NEWWINDOW, lambda event: event.Skip())
        view.Bind(module.EVT_WEBVIEW_NEWWINDOW_FEATURES, frame.new_window_features)
        view.Create(frame.panel)

        def opened(_value, _error):
            wx.CallLater(300, lambda: results.update(opened=len(frame._login_windows)))
            wx.CallLater(3500, finish)

        def finish():
            results['left'] = len(frame._login_windows)
            evaluate(view, 'window.got', done)

        def done(value, error):
            results.update(got=value, error=error)
            frame.Destroy()
            app.ExitMainLoop()

        wx.CallLater(2500, lambda: call_devtools(view, 'Runtime.evaluate', {
            'expression': f"!!window.open('{base}/login', 'login', 'width=420,height=520')",
            'userGesture': True}, opened))
        view.LoadURL(base + '/')
        frame.ShowWithoutActivating()
        timer = wx.CallLater(15000, app.ExitMainLoop)
        app.MainLoop()
        timer.Stop()
    print(results, statuses[-1:], flush=True)
    passed = results.get('got') == 'login-ok' and results.get('opened') == 1 and results.get('left') == 0
    print('Login window linked to the page:', 'PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
