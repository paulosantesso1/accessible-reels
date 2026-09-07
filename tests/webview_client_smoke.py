"""Exercise the actual WebView2 client against a local, account-free document."""
import os
import tempfile
from unittest.mock import patch

import wx
import wx.html2 as html2

from ui import webview_client as module
from ui.webview_native import evaluate
from ui.app_frame import MainFrame


def main():
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = tempfile.mkdtemp(prefix='reels-client-test-')
    app = wx.App(False)
    frame = wx.Frame(None, title='Teste local dos controles', size=(700, 600))
    profile = os.environ['WEBVIEW2_USER_DATA_FOLDER']
    with patch.object(MainFrame, 'status'):
        application = MainFrame()
        assert not application.views
        application.network.SetStringSelection('Instagram')
        application.select_network()
        application.dispatch('toggle_playback')
        application.focus_page()
        application.home()
        application.reload()
        assert not application.views, 'A network opened without the login button.'
        application.Destroy()
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = profile
    print('Startup and network selection without automatic login: PASS', flush=True)
    view = html2.WebView.New(backend=html2.WebViewBackendEdge)
    source = module.scripts_for('TikTok').replace("['tiktok.com', 'www.tiktok.com'].includes(location.hostname)", 'true')
    failures = ['Timeout: controles não ficaram prontos.']
    started = False

    def finish(result):
        failures[:] = [] if result.get('ok') else [str(result)]
        print('WebView2 client:', result, flush=True)
        client.close()
        frame.Close()

    def check(result, predicate, next_step):
        if not result.get('ok') or not predicate(result):
            finish({'ok': False, 'result': result})
        else:
            next_step()

    def command(action, predicate, next_step):
        client.execute(action, None, lambda result: check(result, predicate, next_step))

    def playback(value, error):
        if error:
            finish({'ok': False, 'error': error})
            return
        # An unnamed iframe must not invalidate the top document's controls.
        wx.CallLater(500, lambda: command('toggle', lambda r: r.get('paused') is True,
            lambda: command('toggle', lambda r: r.get('paused') is False,
                lambda: command('next', lambda r: True,
                    lambda: evaluate(view, 'window.position === 1 && window.trusted === true', advanced)))))

    def advanced(value, error):
        if error or value is not True:
            finish({'ok': False, 'error': error or 'Next did not click the feed button.'})
            return
        command('previous', lambda r: True, lambda: evaluate(view,
            'window.position === 0 && window.trusted === true',
            lambda value, error: finish({'ok': value is True and not error, 'error': error})))

    def loaded():
        nonlocal started
        if started:
            return
        started = True
        evaluate(view, """(async () => {
            document.body.innerHTML = '<video muted style="width:320px;height:200px"></video>' +
                '<button data-e2e="feed-navigation-next">Next</button>' +
                '<button data-e2e="feed-navigation-prev">Previous</button>';
            window.position = 0;
            document.querySelector('[data-e2e="feed-navigation-next"]').onclick = e => {
                window.position++; window.trusted = e.isTrusted;
            };
            document.querySelector('[data-e2e="feed-navigation-prev"]').onclick = e => {
                window.position--; window.trusted = e.isTrusted;
            };
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            window.paintTimer = setInterval(() => context.fillRect(0, 0, 100, 100), 30);
            document.querySelector('video').srcObject = canvas.captureStream(30);
            await document.querySelector('video').play();
            const child = document.createElement('iframe');
            child.src = 'about:blank?child'; document.body.appendChild(child);
            return true;
        })()""", playback)

    client = module.WebViewClient(view, 'TikTok', loaded, lambda error: print('ERROR:', error, flush=True))
    client.target_url = 'about:blank'
    def trace(event):
        print('EVENT:', event.GetEventType(), event.GetURL(), repr(event.GetTarget()), event.IsTargetMainFrame(), flush=True)
        event.Skip()
    view.Bind(html2.EVT_WEBVIEW_LOADED, trace)
    view.Bind(html2.EVT_WEBVIEW_NAVIGATING, trace)
    def inspect():
        evaluate(view, "({run:typeof __accessibleRun, transport:typeof __accessibleTransport, installed:!!window.__accessibleReelsInstalled})",
                 lambda value, error: print('STATE:', value, error, 'ready=', client.ready, flush=True))

    with patch.object(module, 'scripts_for', return_value=source), patch.object(module, 'belongs_to_platform', return_value=True):
        view.Create(frame)
        client.initialize()
        frame.Show()
        wx.CallLater(3000, inspect)
        timer = wx.CallLater(15000, frame.Close)
        app.MainLoop()
        timer.Stop()
    if failures:
        print(failures, flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
