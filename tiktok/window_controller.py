from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol


SW_HIDE = 0
SW_SHOW = 5
TH32CS_SNAPPROCESS = 0x00000002
GW_OWNER = 4
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class WindowBackend(Protocol):
    def descendants_of(self, root_pid: int) -> set[int]: ...

    def top_level_windows(self) -> list[tuple[int, int, bool]]: ...

    def show_window(self, handle: int, command: int) -> None: ...


class BrowserWindowController:
    """Mostra/oculta somente janelas descendentes do Playwright deste app.

    Títulos de janela, nomes de executável e navegadores instalados pelo usuário
    não participam da decisão. Se a árvore de processos não puder ser comprovada,
    nenhuma janela é alterada.
    """

    def __init__(self, playwright_driver_pid: int | None, backend: WindowBackend | None = None) -> None:
        self._root_pid = playwright_driver_pid if playwright_driver_pid and playwright_driver_pid > 0 else None
        self._backend = backend or Win32WindowBackend()
        self._known_handles: set[int] = set()

    def set_visible(self, visible: bool) -> bool:
        if self._root_pid is None:
            return False
        try:
            descendants = self._backend.descendants_of(self._root_pid)
            if not descendants:
                return False
            records = self._backend.top_level_windows()
            verified = {handle for handle, pid, _visible in records if pid in descendants}
            visible_handles = {
                handle
                for handle, pid, is_visible in records
                if pid in descendants and is_visible
            }
            # Uma handle conhecida continua válida somente se ainda pertencer à
            # árvore atual. Janelas internas que sempre foram ocultas não entram.
            self._known_handles.intersection_update(verified)
            self._known_handles.update(visible_handles)
            handles = set(self._known_handles)
            if not handles:
                return False
            command = SW_SHOW if visible else SW_HIDE
            for handle in handles:
                self._backend.show_window(handle, command)
            return True
        except Exception:
            return False


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class Win32WindowBackend:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("O controlador de janelas requer Windows.")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        self._kernel32.Process32FirstW.restype = wintypes.BOOL
        self._kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        self._kernel32.Process32NextW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self._user32.GetWindow.restype = wintypes.HWND
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL

    def descendants_of(self, root_pid: int) -> set[int]:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (None, INVALID_HANDLE_VALUE):
            return set()
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            parents: dict[int, int] = {}
            if self._kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                    if not self._kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
        finally:
            self._kernel32.CloseHandle(snapshot)

        descendants = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, parent in parents.items():
                if parent in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        return descendants

    def top_level_windows(self) -> list[tuple[int, int, bool]]:
        windows: list[tuple[int, int, bool]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def collect(handle: int, _parameter: int) -> bool:
            if self._user32.GetWindow(handle, GW_OWNER):
                return True
            pid = wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            if pid.value:
                windows.append(
                    (
                        int(handle),
                        int(pid.value),
                        bool(self._user32.IsWindowVisible(handle)),
                    )
                )
            return True

        self._user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self._user32.EnumWindows.restype = wintypes.BOOL
        self._user32.EnumWindows(collect, 0)
        return windows

    def show_window(self, handle: int, command: int) -> None:
        self._user32.ShowWindow(wintypes.HWND(handle), command)


def playwright_driver_pid(playwright: object) -> int | None:
    """Obtém o PID do driver privado desta instância, falhando de modo seguro."""
    try:
        implementation = getattr(playwright, "_impl_obj")
        connection = getattr(implementation, "_connection")
        transport = getattr(connection, "_transport")
        process = getattr(transport, "_proc")
        pid = int(getattr(process, "pid"))
        return pid if pid > 0 else None
    except (AttributeError, TypeError, ValueError):
        return None
