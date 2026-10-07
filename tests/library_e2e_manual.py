"""Manual end-to-end check of the liked/saved video lists with the real session.

Runs the whole MainFrame against the persistent profile (the logged-in
account), sends real keystrokes with SendInput and records what the screen
reader announcer received. Videos are muted. Nothing is liked, saved or
changed in the account. Run: python -m tests.library_e2e_manual
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
    return frame.results_list.GetCount() > 0 or any('Nenhum vídeo' in s or 'Entre na sua conta' in s for s in statuses[-3:])


def complete(kind):
    return lambda: any(f'Lista completa' in s and kind in s for s in statuses)


def labels():
    return [frame.results_list.GetString(i) for i in range(frame.results_list.GetCount())]


def step_liked():
    statuses.clear()
    print('> Alt+Shift+L (curtidos), TikTok ainda fechado', flush=True)
    state['t0'] = time.monotonic()
    send('alt', 'shift', 'l')
    wait(library_ready, after_liked, 220, 'liked list')


def after_liked(ok):
    count = frame.results_list.GetCount()
    elapsed = time.monotonic() - state['t0']
    check('Alt+Shift+L abre a lista de curtidos', ok and count > 0, f'{count} itens em {elapsed:.0f}s')
    check('lista abre com os primeiros (>= 50) antes de carregar tudo', 50 <= count < 500, str(count))
    print('  primeiros:', [frame.results_list.GetString(i)[:60] for i in range(min(3, count))], flush=True)
    check('foco na lista de resultados', wx.Window.FindFocus() is frame.results_list)
    check('aba Pesquisa selecionada', frame.activities.GetSelection() == 2)
    check('aviso de que o resto carrega em segundo plano', any('prontos; o restante continua carregando' in s and 'Alt+L descurte' in s for s in statuses), statuses[-1:] and statuses[-1][:140])
    check('NVDA recebeu o aviso', any('segundo plano' in m and r for _, m, r in speech))
    state['opened'], state['opened_labels'] = count, labels()
    wx.CallLater(500, step_open)


def step_open():
    frame.results_list.SetSelection(0)
    statuses.clear()
    print('> Enter abre o primeiro curtido enquanto o resto ainda carrega', flush=True)
    send('enter')
    wait(lambda: frame.platform_data['TikTok'].get('is_list_mode') is True and any('Abrindo vídeo' in s for s in statuses), after_open, 60, 'open')


def after_open(ok):
    check('Enter abre o vídeo durante o carregamento', ok)
    print('> Alt+Down avança na lista', flush=True)
    before = frame.results_list.GetSelection()
    send('alt', 'down')
    wait(lambda: frame.results_list.GetSelection() == before + 1, after_next, 20, 'next')


def after_next(ok):
    check('Alt+Down vai ao próximo da lista', ok, str(frame.results_list.GetSelection()))
    state['selection'] = frame.results_list.GetSelection()
    wait(lambda: frame.results_list.GetCount() > state['opened'], after_growth, 180, 'list growth')


def after_growth(ok):
    count = frame.results_list.GetCount()
    check('a lista continua crescendo em segundo plano', ok, f'{state["opened"]} -> {count}')
    check('a posição na lista não mudou com o crescimento', frame.results_list.GetSelection() == state['selection'])
    check('os itens anteriores continuam iguais', labels()[:state['opened']] == state['opened_labels'])
    wait(complete('curtidos'), after_complete, 400, 'complete liked')


def after_complete(ok):
    count = frame.results_list.GetCount()
    check('aviso de lista completa de curtidos', ok, statuses[-1][:120] if statuses else '')
    check('lista completa tem 500 itens (limite)', count == 500, str(count))
    check('NVDA recebeu o aviso de lista completa', any('Lista completa' in m and r for _, m, r in speech))
    check('seleção preservada ao final', frame.results_list.GetSelection() == state['selection'])
    state['liked'] = labels()
    wx.CallLater(500, step_back)


def step_back():
    print('> Ctrl+R volta aos resultados', flush=True)
    send('ctrl', 'r')
    wait(lambda: wx.Window.FindFocus() is frame.results_list, after_back, 30, 'back to results')


def after_back(ok):
    check('Ctrl+R devolve o foco à lista', ok)
    check('lista de curtidos preservada', labels() == state['liked'])
    wx.CallLater(500, step_favorites)


def step_favorites_only():
    state['liked'] = []
    step_favorites()


def step_favorites():
    statuses.clear()
    print('> Alt+Shift+F (favoritos)', flush=True)
    send('alt', 'shift', 'f')
    wait(lambda: library_ready() and frame.platform_data['TikTok'].get('library') == 'favorites', after_favorites, 220, 'favorites list')


def after_favorites(ok):
    count = frame.results_list.GetCount()
    check('Alt+Shift+F abre a lista de favoritos', ok and count > 0, f'{count} itens')
    check('mensagem de favoritos menciona Alt+F', any('favoritos' in s and 'Alt+F remove dos favoritos' in s for s in statuses), statuses[-1:] and statuses[-1][:140])
    wait(complete('favoritos'), after_favorites_complete, 300, 'complete favorites')


def after_favorites_complete(ok):
    count = frame.results_list.GetCount()
    check('aviso de lista completa de favoritos', ok, statuses[-1][:120] if statuses else '')
    check('favoritos diferem dos curtidos', labels() != state['liked'])
    print('  favoritos:', count, flush=True)
    wx.CallLater(500, step_download)


def step_download():
    items = list(frame._results[:2])
    state['two'] = items
    frame._results = items
    chosen = download_dir

    class FakeDirDialog:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ShowModal(self): return wx.ID_OK
        def GetPath(self): return str(chosen)
    wx.DirDialog = FakeDirDialog
    statuses.clear()
    print('> Ctrl+Shift+L baixa a lista (2 primeiros), pasta', chosen, flush=True)
    send('ctrl', 'shift', 'l')
    wait(lambda: frame._list_download is None and any('Download em lote' in s for s in statuses), after_download, 240, 'batch download')


def after_download(ok):
    files = sorted(p.name for p in download_dir.iterdir())
    check('download em lote terminou', ok, statuses[-1][:150] if statuses else '')
    check('arquivos baixados', len(files) >= 1, str(files)[:200])
    statuses.clear()
    print('> Repetir: itens existentes são pulados', flush=True)
    frame._results = state['two']  # another refresh may have restored the full list
    send('ctrl', 'shift', 'l')
    wait(lambda: frame._list_download is None and any('Download em lote' in s for s in statuses), after_repeat, 120, 'repeat')


def after_repeat(ok):
    check('segunda execução pula os já baixados', ok and any('já existiam' in s for s in statuses), statuses[-1][:150] if statuses else '')
    for path in download_dir.iterdir():
        path.unlink()
    download_dir.rmdir()
    finish()


state = {}
wx.CallLater(2500, step_favorites_only if os.environ.get('ONLY') == 'favorites' else step_liked)
wx.CallLater(900000, lambda: (print('HARD TIMEOUT'), os._exit(2)))
app.MainLoop()
