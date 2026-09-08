"""Select the application-owned WebView2 before wx loads its Edge backend."""
import json
import os
from pathlib import Path
import struct
import sys

from app_logging import get_logger


def configure_runtime(*, root=None, frozen=None):
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    root = Path(root).resolve() if root else (Path(sys.executable).resolve().parent if frozen
                                   else Path(__file__).resolve().parent)
    manifest = root / 'webview2-runtime.json'
    if not frozen and not (root / 'runtime').exists():
        get_logger().info('WebView2: source mode, using system runtime')
        return None
    lock = json.loads(manifest.read_text(encoding='utf-8'))
    if lock['architecture'] != 'x64' or struct.calcsize('P') != 8:
        raise RuntimeError('O runtime incluído requer o aplicativo Windows x64.')
    runtime = root / 'runtime' / lock['version']
    if not (runtime / 'msedgewebview2.exe').is_file():
        raise RuntimeError('O runtime incluído está ausente. Reinstale o Accessible Reels.')
    # Overrides inherited environment settings for this process only.
    os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] = str(runtime)
    get_logger().info('WebView2: fixed version=%s architecture=%s folder=%s',
                      lock['version'], lock['architecture'], runtime)
    return runtime


def backend_version():
    """Query the Microsoft loader; wxPython does not expose this in every release."""
    import ctypes
    import wx
    loader_root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(wx.__file__).parent
    loader = ctypes.WinDLL(str(loader_root / 'WebView2Loader.dll'))
    query = loader.GetAvailableCoreWebView2BrowserVersionString
    query.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]
    query.restype = ctypes.c_long
    value = ctypes.c_void_p()
    result = query(os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'), ctypes.byref(value))
    if result < 0:
        raise OSError(f'WebView2 loader HRESULT=0x{result & 0xffffffff:08X}')
    free = ctypes.windll.ole32.CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    try:
        return ctypes.wstring_at(value)
    finally:
        free(value)


def check_runtime():
    """Hidden, account-free smoke test for the actual packaged executable."""
    import tempfile
    import wx
    import wx.html2 as html2

    logger = get_logger()
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = tempfile.mkdtemp(prefix='reels-runtime-check-')
    app = wx.App(False)
    available = html2.WebView.IsBackendAvailable(html2.WebViewBackendEdge)
    logger.info('WebView2 check: wx=%s available=%s folder=%s', wx.version(), available,
                os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'))
    if not available:
        return 1
    version = backend_version()
    logger.info('WebView2 loaded backend: %s', version)
    folder = os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER')
    if folder and Path(folder).name not in version:
        logger.error('WebView2 loaded an unexpected version')
        return 1
    frame = wx.Frame(None)
    view = html2.WebView.New(backend=html2.WebViewBackendEdge)
    result = [1]

    def finish(code):
        result[0] = code
        frame.Destroy()

    def loaded(event):
        ok, value = view.RunScript('1 + 1')
        logger.info('WebView2 page test: script_ok=%s result=%s', ok, value)
        # Do not destroy the native WebView while its event callback is on the stack.
        wx.CallAfter(finish, 0 if ok and str(value) == '2' else 1)

    view.Bind(html2.EVT_WEBVIEW_LOADED, loaded)
    document = Path(os.environ['WEBVIEW2_USER_DATA_FOLDER']) / 'check.html'
    document.write_text('<!doctype html><title>Runtime check</title><p>OK</p>', encoding='utf-8')
    if not view.Create(frame, url=document.as_uri()):
        logger.error('WebView2 check: Create failed')
        frame.Destroy()
        return 1
    timer = wx.CallLater(15000, finish, 1)
    app.MainLoop()
    timer.Stop()
    return result[0]
