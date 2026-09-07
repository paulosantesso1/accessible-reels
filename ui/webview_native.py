"""Small WebView2 COM adapter. No listening port or external browser process.

wx.html2.GetNativeBackend returns ICoreWebView2_2 (derived from ICoreWebView2).
The stable ICoreWebView2 ABI has CallDevToolsProtocolMethod at vtable slot 36.
See Microsoft WebView2 SDK, ICoreWebView2 and its completion-handler interface.
All calls and callback delivery run on the wx GUI thread.
"""
from __future__ import annotations

import ctypes as ct
import json
import uuid

import wx

HRESULT = ct.c_int32
ULONG = ct.c_uint32
PTR = ct.c_void_p
CALL = ct.WINFUNCTYPE
QUERY = CALL(HRESULT, PTR, PTR, ct.POINTER(PTR))
REF = CALL(ULONG, PTR)
INVOKE = CALL(HRESULT, PTR, HRESULT, ct.c_wchar_p)
CDP = CALL(HRESULT, PTR, ct.c_wchar_p, ct.c_wchar_p, PTR)
IUNKNOWN = uuid.UUID('00000000-0000-0000-c000-000000000046').bytes_le
COMPLETION = uuid.UUID('5c4889f0-5ef6-4c5a-952c-d8f1b92d0574').bytes_le
_live_handlers = {}


class _Interface(ct.Structure):
    _fields_ = [('vtable', ct.POINTER(PTR))]


class _Completion:
    def __init__(self, callback):
        self.callback = callback
        self.references = 1
        self.functions = (QUERY(self.query), REF(self.add_ref), REF(self.release), INVOKE(self.invoke))
        self.table = (PTR * 4)(*[ct.cast(f, PTR).value for f in self.functions])
        self.interface = _Interface(self.table)
        self.address = ct.addressof(self.interface)
        _live_handlers[self.address] = self

    def query(self, _this, iid, output):
        if not output:
            return -2147467261  # E_POINTER
        output[0] = None
        if iid and ct.string_at(iid, 16) in (IUNKNOWN, COMPLETION):
            output[0] = self.address
            self.add_ref(_this)
            return 0
        return -2147467262  # E_NOINTERFACE

    def add_ref(self, _this):
        self.references += 1
        return self.references

    def release(self, _this):
        self.references -= 1
        if self.references == 0:
            # Keep ctypes trampolines alive until this callback has returned.
            wx.CallAfter(_live_handlers.pop, self.address, None)
        return self.references

    def invoke(self, _this, error, result):
        callback, self.callback = self.callback, None
        if callback is not None:
            try:
                payload = json.loads(result or '{}') if error >= 0 else {}
                message = None if error >= 0 else 'O WebView2 recusou o comando.'
            except (ValueError, TypeError):
                payload, message = {}, 'Resposta inválida do WebView2.'
            wx.CallAfter(callback, payload, message)
        return 0


def call_devtools(view, method, parameters, callback):
    """Use the in-process COM API; copy responses before returning to COM."""
    if not wx.IsMainThread():
        raise RuntimeError('WebView2 deve ser chamado na thread da interface.')
    pointer = view.GetNativeBackend()
    if not pointer:
        wx.CallAfter(callback, {}, 'A página ainda está inicializando.')
        return
    address = int(pointer)
    table = ct.cast(address, ct.POINTER(ct.POINTER(PTR))).contents
    handler = _Completion(callback)
    try:
        result = CDP(table[36])(address, method, json.dumps(parameters), handler.address)
        if result < 0:
            handler.invoke(None, result, None)
    finally:
        handler.release(None)


def evaluate(view, expression, callback):
    def complete(payload, error):
        if error or payload.get('exceptionDetails'):
            callback(None, error or 'A página não conseguiu executar o comando.')
        else:
            callback(payload.get('result', {}).get('value'), None)
    call_devtools(view, 'Runtime.evaluate', {
        'expression': expression, 'returnByValue': True, 'awaitPromise': True,
        'userGesture': True,
    }, complete)


def click(view, x, y, callback, still_valid=lambda: True):
    """Wait for mouse-down completion before mouse-up; never move the OS cursor."""
    parameters = {'x': x, 'y': y, 'button': 'left', 'clickCount': 1}
    def pressed(_payload, error):
        if error:
            callback(False, error)
            return
        if not still_valid():
            # Release without a click if navigation cancelled the operation.
            call_devtools(view, 'Input.dispatchMouseEvent', {
                **parameters, 'type': 'mouseReleased', 'clickCount': 0,
            }, lambda _p, _e: callback(False, 'A página mudou durante o comando.'))
            return
        call_devtools(view, 'Input.dispatchMouseEvent', {
            **parameters, 'type': 'mouseReleased',
        }, lambda _p, err: callback(not err, err))
    call_devtools(view, 'Input.dispatchMouseEvent', {
        **parameters, 'type': 'mousePressed',
    }, pressed)
