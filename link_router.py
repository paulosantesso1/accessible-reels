"""Receive links opened by other apps while Accessible Reels is the default browser.

Video links (TikTok, Instagram, YouTube) open inside the application, reusing the
running instance when there is one. Every other link is passed to the browser that
was the default before Accessible Reels took over, so ordinary links keep working.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from multiprocessing.connection import Client, Listener
from pathlib import Path
from urllib.parse import quote

from app_logging import get_logger
from app_version import APP_NAME

PROG_ID = 'AccessibleReelsURL'
DEFAULT_APPS_URI = f'ms-settings:defaultapps?registeredAppUser={APP_NAME}'
MAX_MESSAGE_BYTES = 4096
MAX_URL_LENGTH = 2048
_URL_START = re.compile(r'https?://', re.IGNORECASE)
_URL_PLACEHOLDER = re.compile(r'%[1lL]')
_USER_CHOICE = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
_BROWSERS_KEY = r'Software\Clients\StartMenuInternet'
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
logger = get_logger()


def link_from_arguments(argv):
    """Return the first http(s) URL passed on the command line, if any."""
    for argument in argv[1:]:
        if _URL_START.match(argument) and len(argument) <= MAX_URL_LENGTH:
            return argument
    return None


def is_video_link(url):
    from tiktok.video_controls import VideoControlError
    from ui.video_link import parse_video_link
    try:
        parse_video_link(url)
    except VideoControlError:
        return False
    return True


def build_command(template, url):
    """Fill a registry ``open`` command with the URL.

    The command runs without a shell, but browsers such as Firefox wrap ``%1`` in
    quotes, so anything that could end that quote or carry whitespace is encoded.
    """
    safe = quote(url, safe="!#$&'()*+,/:;=?@[]~%-._")
    if _URL_PLACEHOLDER.search(template):
        return _URL_PLACEHOLDER.sub(lambda match: safe, template)
    return f'{template} "{safe}"'


def _executable_of(command):
    command = command.strip()
    if command.startswith('"'):
        # Caminho entre aspas: extrai até a aspa de fechamento.
        return command[1:].split('"', 1)[0]
    # BUG-01: Caminhos sem aspas podem conter espaços (ex: C:\Program Files\...).
    # Usamos um padrão mais inteligente: lemos até o primeiro espaço que é
    # seguido de um argumento típico (%-placeholder ou flag com hífen),
    # ou até o primeiro espaço quando nenhum padrão melhor é encontrado.
    import re as _re
    # Captura tudo até " %" ou " -" ou " /" que indicam início de argumentos.
    match = _re.match(r'^(.*?)\s+(?=%|--|/|$)', command)
    if match and match.group(1):
        return match.group(1)
    return command.split(' ', 1)[0]


def _is_own_command(command):
    own = os.path.normcase(os.path.abspath(sys.executable))
    return os.path.normcase(os.path.abspath(_executable_of(command))) == own


def _is_forbidden_browser(command):
    if not command or not command.strip():
        return True
    if _is_own_command(command) or APP_NAME in command:
        return True
    exe = _executable_of(command)
    if os.path.basename(exe).casefold() == 'iexplore.exe':
        return True
    return False


def _registry_value(root, path, name=''):
    import winreg
    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) and value else None


def current_default_progid():
    import winreg
    return _registry_value(winreg.HKEY_CURRENT_USER, _USER_CHOICE, 'ProgId')


def _progid_command(progid):
    import winreg
    return _registry_value(winreg.HKEY_CLASSES_ROOT, rf'{progid}\shell\open\command')


def _registered_browser_commands():
    return list(registered_browsers().values())


def state_path():
    root = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return root / APP_NAME / 'default_browser.json'


def load_browser_settings():
    try:
        data = json.loads(state_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_browser_settings(values):
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        current = load_browser_settings()
        current.update(values)
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        logger.exception('Could not save browser settings')


def registered_browsers():
    """Return a mapping of friendly browser names to launch commands."""
    import winreg
    browsers = {}
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, _BROWSERS_KEY) as key:
                count = winreg.QueryInfoKey(key)[0]
                names = [winreg.EnumKey(key, index) for index in range(count)]
        except OSError:
            continue
        for name in names:
            # Windows 11 only redirects Internet Explorer to Edge, so it is no real choice.
            if name.casefold() == 'iexplore.exe':
                continue
            command = _registry_value(root, rf'{_BROWSERS_KEY}\{name}\shell\open\command')
            if not command or _is_own_command(command) or APP_NAME in command:
                continue
            display = _registry_value(root, rf'{_BROWSERS_KEY}\{name}') or name
            if display not in browsers:
                browsers[display] = command
    return browsers


def get_preferred_browser():
    """The browser the user picked, or None to follow Windows' default."""
    value = load_browser_settings().get('preferred_browser')
    return value if isinstance(value, str) and value else None


def set_preferred_browser(name):
    """Store the chosen browser; None goes back to Windows' default."""
    save_browser_settings({'preferred_browser': name or None})


def remembered_progid():
    value = load_browser_settings().get('progid')
    return value if isinstance(value, str) and value else None


def remember_default_browser():
    """Store the browser that is default now, unless that is this application."""
    progid = current_default_progid()
    if not progid or progid.casefold() == PROG_ID.casefold() or progid == remembered_progid():
        return
    save_browser_settings({'progid': progid})


def _browser_commands():
    """Commands of candidate browsers: preferred first, then current/remembered, then registered."""
    seen = set()

    def add(cmd):
        if not cmd or _is_forbidden_browser(cmd):
            return False
        try:
            exe = os.path.normcase(os.path.abspath(_executable_of(cmd)))
        except Exception:
            exe = cmd.strip().casefold()
        if exe in seen:
            return False
        seen.add(exe)
        return True

    preferred = get_preferred_browser()
    if preferred:
        for name, cmd in registered_browsers().items():
            if name.casefold() == preferred.casefold():
                if add(cmd):
                    yield cmd
                break

    for progid in (current_default_progid(), remembered_progid()):
        if progid and progid.casefold() != PROG_ID.casefold():
            command = _progid_command(progid)
            if add(command):
                yield command

    for command in _registered_browser_commands():
        if add(command):
            yield command


def open_in_default_browser(url):
    """Open the URL in the user's real browser. Returns whether one accepted it."""
    for template in _browser_commands():
        if _is_forbidden_browser(template):
            continue
        try:
            subprocess.Popen(build_command(template, url), close_fds=True, creationflags=_DETACHED)
            return True
        except OSError:
            logger.exception('Could not start browser command')
    return False


def open_default_apps_settings():
    """Open Windows' default apps page for Accessible Reels."""
    os.startfile(DEFAULT_APPS_URI)


def pipe_address():
    user = re.sub(r'\W', '_', os.environ.get('USERNAME', 'user'))
    return rf'\\.\pipe\AccessibleReels-{user}'


def send_to_running_instance(message, timeout=5.0):
    """Hand a message to the instance that owns the pipe. Returns whether it acknowledged."""
    result = []

    def worker():
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
            with Client(pipe_address(), family='AF_PIPE') as connection:
                connection.send_bytes(json.dumps(message).encode('utf-8'))
                if connection.poll(timeout):
                    result.append(connection.recv_bytes(MAX_MESSAGE_BYTES) == b'ok')
        except (OSError, EOFError, ValueError):
            pass

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout + 1)
    return bool(result and result[0])


def _valid_message(data):
    if not isinstance(data, dict):
        return None
    if data.get('action') == 'show':
        return {'action': 'show'}
    url = data.get('url')
    if data.get('action') == 'open' and isinstance(url, str) and len(url) <= MAX_URL_LENGTH \
            and _URL_START.match(url):
        return {'action': 'open', 'url': url}
    return None


class LinkServer:
    """Listen for links sent by later launches and hand them to the window.

    Messages that arrive before the window exists are kept until a handler is set.
    """

    def __init__(self):
        self._listener = None
        self._handler = None
        self._pending = []
        self._lock = threading.Lock()
        self._closed = False

    def start(self):
        try:
            self._listener = Listener(pipe_address(), family='AF_PIPE')
        except OSError:
            logger.warning('Link pipe unavailable; another instance may own it')
            return False
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def deliver(self, message):
        with self._lock:
            handler = self._handler
            if handler is None:
                self._pending.append(message)
                return
        handler(message)

    def set_handler(self, handler):
        with self._lock:
            self._handler = handler
            pending, self._pending = self._pending, []
        for message in pending:
            handler(message)

    def close(self):
        self._closed = True
        if self._listener:
            try:
                self._listener.close()
            except OSError:
                pass

    def _serve(self):
        while not self._closed:
            try:
                connection = self._listener.accept()
            except (OSError, EOFError):
                if self._closed:
                    return
                continue
            try:
                with connection:
                    if not connection.poll(2):
                        continue
                    message = _valid_message(json.loads(connection.recv_bytes(MAX_MESSAGE_BYTES)))
                    if message:
                        self.deliver(message)
                        connection.send_bytes(b'ok')
            except (OSError, EOFError, ValueError):
                continue


def route_launch(argv):
    """Decide what this launch does with a link.

    Returns a LinkServer when this process should run the application, or None when
    the launch was fully handled (link sent to the browser or to a running window).
    """
    try:
        remember_default_browser()
    except OSError:
        logger.exception('Could not read the default browser')
    url = link_from_arguments(argv)
    if url and not is_video_link(url):
        if not open_in_default_browser(url):
            logger.error('No browser available for a non-video link')
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, 'Não foi possível abrir o link no navegador anterior. Escolha um navegador '
                'padrão nas configurações do Windows.', APP_NAME, 0x10)
        return None
    message = {'action': 'open', 'url': url} if url else {'action': 'show'}
    if send_to_running_instance(message):
        return None
    server = LinkServer()
    if not server.start() and send_to_running_instance(message):
        return None
    if url:
        server.deliver(message)
    return server
