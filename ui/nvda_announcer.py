from __future__ import annotations

import ctypes
import os
import struct
import sys
from functools import lru_cache
from pathlib import Path
from ctypes import wintypes


@lru_cache(maxsize=1)
def _accessible_output_nvda() -> object | None:
    """Carrega a saída NVDA que acompanha o accessible-output2."""
    if os.name != "nt":
        return None
    try:
        from accessible_output2.outputs.nvda import NVDA

        return NVDA()
    except Exception:
        return None


def speak_with_accessible_output(message: str) -> bool:
    """Fala pelo NVDA via accessible-output2 quando ele estiver respondendo."""
    output = _accessible_output_nvda()
    if output is None:
        return False
    try:
        if not output.is_active():
            return False
        output.speak(str(message), interrupt=True)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _controller() -> object | None:
    if os.name != "nt":
        return None
    dll_name = (
        "nvdaControllerClient64.dll"
        if struct.calcsize("P") == 8
        else "nvdaControllerClient32.dll"
    )
    candidates = [
        Path(__file__).resolve().parents[1] / dll_name,
        Path(sys.executable).resolve().parent / dll_name,
    ]
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "NVDA" / dll_name)

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            controller = ctypes.WinDLL(str(candidate))
            controller.nvdaController_testIfRunning.restype = ctypes.c_int
            controller.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            controller.nvdaController_speakText.restype = ctypes.c_int
            return controller
        except (OSError, AttributeError):
            continue
    return None


def speak_with_nvda(message: str) -> bool:
    """Fala diretamente pelo NVDA; retorna falso para permitir fallback wx."""
    controller = _controller()
    if controller is None:
        return False
    try:
        if controller.nvdaController_testIfRunning() != 0:
            return False
        return controller.nvdaController_speakText(str(message)) == 0
    except (OSError, AttributeError, TypeError, ValueError):
        return False


def raise_uia_notification(window: object, message: str) -> bool:
    """Emite uma notificação UI Automation, suportada pelo NVDA moderno."""
    if os.name != "nt":
        return False
    provider = ctypes.c_void_p()
    try:
        handle = int(window.GetHandle())
        automation = ctypes.WinDLL("UIAutomationCore", use_last_error=True)
        automation.UiaHostProviderFromHwnd.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        automation.UiaHostProviderFromHwnd.restype = ctypes.c_long
        automation.UiaRaiseNotificationEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        automation.UiaRaiseNotificationEvent.restype = ctypes.c_long
        if automation.UiaHostProviderFromHwnd(
            wintypes.HWND(handle), ctypes.byref(provider)
        ) != 0 or not provider.value:
            return False
        return (
            automation.UiaRaiseNotificationEvent(
                provider,
                2,  # NotificationKind_ActionCompleted
                1,  # NotificationProcessing_ImportantMostRecent
                str(message),
                "AccessibleReels.Announcement",
            )
            == 0
        )
    except (OSError, AttributeError, TypeError, ValueError):
        return False
    finally:
        if provider.value:
            try:
                vtable = ctypes.cast(
                    provider, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                    vtable[2]
                )
                release(provider)
            except (OSError, TypeError, ValueError):
                pass
