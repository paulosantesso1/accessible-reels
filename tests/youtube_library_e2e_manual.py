"""Manual end-to-end check of the liked YouTube Shorts list with the real session.

Runs the whole MainFrame against the persistent profile (the logged-in
account), sends real keystrokes with SendInput and records what the screen
reader announcer received. Videos are muted. Nothing is liked, saved or
changed in the account. Run: python -m tests.youtube_library_e2e_manual
"""
import ctypes
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import wx
import wx.html2 as html2

from webview_runtime import configure_runtime

configure_runtime()
from app_logging import configure_logging
configure_logging()

import ui.app_frame as app_frame  # noqa: E402
from ui.app_frame import MainFrame  # noqa: E402

MUTE = "setInterval(()=>document.querySelectorAll('video').forEach(v=>{v.muted=true;v.volume=0}),30);"
VK = {'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'enter': 0x0D, 'down': 0x28, 'up': 0x26, 'f6': 0x75, 'f1': 0x70}
KEYUP = 2
speech, checks = [], []


def _die(*info):
    traceback.print_exception(*info)
    os._exit(3)


sys.excepthook = _die


def check(name, ok, detail=''):
    checks.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ') + name + (f' -- {detail}' if detail else ''), flush=True)


def key(code):
    return VK.get(code) or ord(code.upper())


def send(*combo):
    """Press the modifiers and the last key, then release them in reverse order.

    Keys go to whatever window has the focus, so refuse to send unless the
    application window is in the foreground.
    """
    user32 = ctypes.windll.user32
    for _ in range(10):
        if user32.GetForegroundWindow() == frame.GetHandle():
            break
        user32.keybd_event(0x12, 0, 0, 0)  # an Alt tap lets SetForegroundWindow succeed
        user32.keybd_event(0x12, 0, KEYUP, 0)
        user32.SetForegroundWindow(frame.GetHandle())
        time.sleep(0.3)
    else:
        print('ABORT: app window is not in the foreground; no keys sent', flush=True)
        os._exit(4)
    codes = [key(item) for item in combo]
    for code in codes:
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        ctypes.windll.user32.keybd_event(code, 0, KEYUP, 0)


real_accessible, real_nvda = app_frame.speak_with_accessible_output, app_frame.speak_with_nvda


def spy_accessible(message):
    result = real_accessible(message)
    speech.append(('accessible_output', message, result))
    return result


def spy_nvda(message):
    result = real_nvda(message)
    speech.append(('nvda_controller', message, result))
    return result


app_frame.speak_with_accessible_output = spy_accessible
app_frame.speak_with_nvda = spy_nvda
real_new = html2.WebView.New


def muted_new(*args, **kwargs):
    view = real_new(*args, **kwargs)
    try:
        view.AddUserScript(MUTE)
    except Exception:
        pass
    return view


html2.WebView.New = muted_new

app = wx.App(False)
frame = MainFrame()
statuses = []
original_status = frame.status
frame.status = lambda message: (statuses.append(str(message)), original_status(message))
frame.Show()
frame.Raise()
ctypes.windll.user32.SetForegroundWindow(frame.GetHandle())
download_dir = Path(tempfile.mkdtemp(prefix='reels-list-'))


def wait(condition, then, timeout=60, label=''):
    deadline = time.monotonic() + timeout

    def tick():
        if condition():
            then(True)
        elif time.monotonic() > deadline:
            print('TIMEOUT waiting for', label, '| last status:', statuses[-1:] , flush=True)
            then(False)
        else:
            if int(time.monotonic()) % 20 == 0:
                print('  ...waiting for', label, '| status:', statuses[-1:], '| batch:', getattr(frame, '_list_download', None), flush=True)
            wx.CallLater(400, tick)
    tick()


def finish():
    print('\n--- SPEECH sent to the screen reader (last 12) ---')
    for item in speech[-12:]:
        print(item)
    failed = [name for name, ok in checks if not ok]
    print('\nRESULT:', 'ALL PASS' if not failed else f'FAILED {failed}', flush=True)
    frame.Close()
    wx.CallLater(1500, lambda: os._exit(1 if failed else 0))


def library_ready():
    return frame.results_list.GetCount() > 0 or any('Nenhum vídeo' in s or 'logado' in s or 'Não encontrei' in s for s in statuses[-3:])


def labels():
    return [frame.results_list.GetString(i) for i in range(frame.results_list.GetCount())]


def step_select():
    print('> Ctrl+3 abre o YouTube Shorts', flush=True)
    send('ctrl', '3')
    wait(lambda: 'YouTube' in frame.views and frame.network.GetStringSelection() == 'YouTube' and any('YouTube carregado' in s for s in statuses), step_favorites_message, 90, 'youtube loaded')


def step_favorites_message(ok):
    check('Ctrl+3 abre o YouTube', ok)
    statuses.clear()
    print('> Alt+Shift+F no YouTube (não existe lista de favoritos)', flush=True)
    send('alt', 'shift', 'f')
    wait(lambda: any('só existe a lista de curtidos' in s for s in statuses), after_favorites_message, 15, 'favorites message')


def after_favorites_message(ok):
    check('Alt+Shift+F no YouTube avisa que só há curtidos', ok, statuses[-1:] and statuses[-1][:100])
    wx.CallLater(500, step_liked)


def step_liked():
    statuses.clear()
    print('> Alt+Shift+L (Shorts curtidos) no YouTube', flush=True)
    state['t0'] = time.monotonic()
    send('alt', 'shift', 'l')
    wait(library_ready, after_liked, 300, 'liked shorts')


def after_liked(ok):
    count = frame.results_list.GetCount()
    elapsed = time.monotonic() - state['t0']
    check('Alt+Shift+L abre a lista de Shorts curtidos', ok and count > 0, f'{count} itens em {elapsed:.0f}s | {statuses[-1:] and statuses[-1][:140]}')
    print('  primeiros:', [frame.results_list.GetString(i)[:70] for i in range(min(4, count))], flush=True)
    check('todos os itens são links de Shorts', all('/shorts/' in item.url for item in frame._results))
    check('foco na lista de resultados', wx.Window.FindFocus() is frame.results_list)
    check('aba Pesquisa selecionada', frame.activities.GetSelection() == 2)
    check('aviso falado ao NVDA', any(('curtidos' in m) and r for _, m, r in speech))
    state['opened'], state['opened_labels'] = count, labels()
    wx.CallLater(500, step_open)


def step_open():
    frame.results_list.SetSelection(0)
    statuses.clear()
    print('> Enter abre o primeiro Short curtido', flush=True)
    send('enter')
    wait(lambda: frame.platform_data['YouTube'].get('is_list_mode') is True and any('Abrindo vídeo' in s for s in statuses), after_open, 60, 'open')


def after_open(ok):
    check('Enter abre o Short', ok)
    wait(lambda: frame.platform_data['YouTube'].get('author') or frame.platform_data['YouTube'].get('description'), after_details, 60, 'details')


def after_details(ok):
    check('detalhes do Short carregados', ok, str(frame.platform_data['YouTube'].get('description'))[:80])
    before = frame.results_list.GetSelection()
    print('> Alt+Down avança na lista', flush=True)
    send('alt', 'down')
    wait(lambda: frame.results_list.GetSelection() == before + 1, after_next, 30, 'next')


def after_next(ok):
    check('Alt+Down vai ao próximo Short da lista', ok, str(frame.results_list.GetSelection()))
    state['selection'] = frame.results_list.GetSelection()
    wait(lambda: frame._library_worker is None, after_complete, 900, 'complete')


def after_complete(ok):
    count = frame.results_list.GetCount()
    check('carregamento em segundo plano terminou', ok, f'{count} itens | {statuses[-1:] and statuses[-1][:120]}')
    check('posição preservada', frame.results_list.GetSelection() == state['selection'])
    check('itens iniciais iguais', labels()[:state['opened']] == state['opened_labels'])
    print('  total de Shorts curtidos listados:', count, flush=True)
    wx.CallLater(500, step_back)


def step_back():
    print('> Ctrl+R volta aos resultados', flush=True)
    send('ctrl', 'r')
    wait(lambda: wx.Window.FindFocus() is frame.results_list, after_back, 30, 'back')


def after_back(ok):
    check('Ctrl+R devolve o foco à lista', ok)
    finish()


state = {}
wx.CallLater(2500, step_select)
wx.CallLater(1200000, lambda: (print('HARD TIMEOUT'), os._exit(2)))
app.MainLoop()
