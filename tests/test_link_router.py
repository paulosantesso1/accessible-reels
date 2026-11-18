import json
import sys
import threading
import uuid
from unittest.mock import Mock, patch

import pytest

import link_router
from link_router import (LinkServer, build_command, link_from_arguments, open_in_default_browser,
                         route_launch, send_to_running_instance)

CHROME = r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --single-argument %1'
FIREFOX = r'"C:\Program Files\Mozilla Firefox\firefox.exe" -osint -url "%1"'


def test_link_from_arguments_takes_first_http_url():
    assert link_from_arguments(['app.exe', '--x', 'https://vm.tiktok.com/ABC/']) == 'https://vm.tiktok.com/ABC/'
    assert link_from_arguments(['app.exe']) is None
    assert link_from_arguments(['app.exe', 'file:///c:/x', 'ftp://a']) is None


def test_build_command_fills_placeholder_and_appends_when_missing():
    assert build_command(CHROME, 'https://a.test/x?y=1').endswith('--single-argument https://a.test/x?y=1')
    assert build_command('"c:\b.exe"', 'https://a.test/') == '"c:\b.exe" "https://a.test/"'


def test_build_command_cannot_break_out_of_quotes():
    command = build_command(FIREFOX, 'https://a.test/" --evil "x y')
    assert command.count('"') == 4
    assert ' --evil' not in command and ' y' not in command.split('-url')[1]


@pytest.mark.parametrize('url, expected', [
    ('https://www.tiktok.com/@ana/video/123', True),
    ('https://www.tiktok.com/@ana/live', True),
    ('https://live.tiktok.com/@ana', True),
    ('https://vm.tiktok.com/ABC123/', True),
    ('https://example.com/', False),
    ('http://www.tiktok.com/@ana/video/123', False),
])
def test_is_video_link(url, expected):
    assert link_router.is_video_link(url) is expected


def test_open_in_default_browser_skips_this_application_and_uses_next(monkeypatch):
    own = f'"{sys.executable}" "%1"'
    started = []
    monkeypatch.setattr(link_router, '_browser_commands', lambda: iter([own, CHROME]))
    monkeypatch.setattr(link_router.subprocess, 'Popen', lambda command, **kw: started.append(command))
    assert open_in_default_browser('https://a.test/')
    assert len(started) == 1 and 'chrome.exe' in started[0]


def test_open_in_default_browser_reports_failure_without_browser(monkeypatch):
    monkeypatch.setattr(link_router, '_browser_commands', lambda: iter([]))
    assert not open_in_default_browser('https://a.test/')


def test_browser_candidates_prefer_current_then_remembered_and_never_ourselves(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    commands = {'Other': 'other.exe %1', 'Old': 'old.exe %1'}
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: link_router.PROG_ID)
    monkeypatch.setattr(link_router, 'remembered_progid', lambda: 'Old')
    monkeypatch.setattr(link_router, '_progid_command', lambda progid: commands.get(progid))
    monkeypatch.setattr(link_router, '_registered_browser_commands', lambda: ['edge.exe'])
    assert list(link_router._browser_commands()) == ['old.exe %1', 'edge.exe']


def test_remember_default_browser_ignores_this_application(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: 'ChromeHTML')
    link_router.remember_default_browser()
    assert link_router.remembered_progid() == 'ChromeHTML'
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: link_router.PROG_ID)
    link_router.remember_default_browser()
    assert link_router.remembered_progid() == 'ChromeHTML'


def test_preferred_browser_takes_precedence_in_browser_commands(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(link_router, 'registered_browsers', lambda: {'Google Chrome': 'chrome.exe %1', 'Edge': 'edge.exe %1'})
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: 'MSEdgeHTM')
    monkeypatch.setattr(link_router, '_progid_command', lambda progid: 'edge.exe %1')
    monkeypatch.setattr(link_router, '_registered_browser_commands', lambda: ['edge.exe %1'])

    link_router.set_preferred_browser('Google Chrome')
    candidates = list(link_router._browser_commands())
    assert candidates[0] == 'chrome.exe %1'


def test_without_a_choice_the_windows_default_comes_first(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(link_router, 'registered_browsers', lambda: {'Google Chrome': 'chrome.exe %1', 'Edge': 'edge.exe %1'})
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: 'MSEdgeHTM')
    monkeypatch.setattr(link_router, '_progid_command', lambda progid: 'edge.exe %1')
    monkeypatch.setattr(link_router, '_registered_browser_commands', lambda: ['chrome.exe %1', 'edge.exe %1'])

    assert link_router.get_preferred_browser() is None
    assert list(link_router._browser_commands())[0] == 'edge.exe %1'
    link_router.set_preferred_browser('Google Chrome')
    link_router.set_preferred_browser(None)
    assert link_router.get_preferred_browser() is None
    assert list(link_router._browser_commands())[0] == 'edge.exe %1'


def test_browser_commands_excludes_own_command_and_app_name(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(link_router, 'get_preferred_browser', lambda: None)
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: 'MSEdgeHTM')
    monkeypatch.setattr(link_router, '_progid_command', lambda progid: f'"{link_router.APP_NAME}.exe" %1')
    monkeypatch.setattr(link_router, '_registered_browser_commands', lambda: ['iexplore.exe', 'valid_browser.exe %1'])

    commands = list(link_router._browser_commands())
    assert commands == ['valid_browser.exe %1']


def test_browser_commands_deduplicates_by_executable_path(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(link_router, 'get_preferred_browser', lambda: None)
    monkeypatch.setattr(link_router, 'current_default_progid', lambda: 'ChromeHTML')
    monkeypatch.setattr(link_router, '_progid_command', lambda progid: '"C:\\Program Files\\Chrome\\chrome.exe" -- "%1"')
    monkeypatch.setattr(link_router, '_registered_browser_commands', lambda: ['"C:\\Program Files\\Chrome\\chrome.exe"', 'edge.exe %1'])

    commands = list(link_router._browser_commands())
    assert len(commands) == 2
    assert commands[0] == '"C:\\Program Files\\Chrome\\chrome.exe" -- "%1"'
    assert commands[1] == 'edge.exe %1'


@pytest.fixture
def pipe(monkeypatch):
    address = '\\\\.\\pipe\\AccessibleReelsTest-' + uuid.uuid4().hex
    monkeypatch.setattr(link_router, 'pipe_address', lambda: address)
    return address


@pytest.mark.skipif(sys.platform != 'win32', reason='named pipes are Windows specific')
def test_server_receives_links_and_holds_them_until_handler_is_set(pipe):
    server = LinkServer()
    assert server.start()
    try:
        assert send_to_running_instance({'action': 'open', 'url': 'https://vm.tiktok.com/ABC/'})
        received, arrived = [], threading.Event()
        server.set_handler(lambda message: (received.append(message), arrived.set()))
        assert arrived.wait(2)
        assert received == [{'action': 'open', 'url': 'https://vm.tiktok.com/ABC/'}]
    finally:
        server.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='named pipes are Windows specific')
def test_server_rejects_unexpected_messages(pipe):
    server = LinkServer()
    assert server.start()
    received = []
    server.set_handler(received.append)
    try:
        assert not send_to_running_instance({'action': 'open', 'url': 'file:///c:/secret'}, timeout=0.5)
        assert not send_to_running_instance({'action': 'run', 'cmd': 'calc'}, timeout=0.5)
        assert received == []
    finally:
        server.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='named pipes are Windows specific')
def test_route_launch_forwards_to_running_instance_and_reuses_it(pipe, monkeypatch):
    monkeypatch.setattr(link_router, 'remember_default_browser', lambda: None)
    first = route_launch(['app.exe'])
    assert isinstance(first, LinkServer)
    received, arrived = [], threading.Event()
    first.set_handler(lambda message: (received.append(message), arrived.set()))
    try:
        assert route_launch(['app.exe', 'https://vt.tiktok.com/ABC/']) is None
        assert arrived.wait(2)
        assert received == [{'action': 'open', 'url': 'https://vt.tiktok.com/ABC/'}]
    finally:
        first.close()


def test_route_launch_sends_other_links_to_the_browser_without_starting_the_app(pipe, monkeypatch):
    opened = []
    monkeypatch.setattr(link_router, 'remember_default_browser', lambda: None)
    monkeypatch.setattr(link_router, 'open_in_default_browser', lambda url: opened.append(url) or True)
    assert route_launch(['app.exe', 'https://example.com/a']) is None
    assert opened == ['https://example.com/a']


def test_route_launch_first_instance_queues_its_own_link(pipe, monkeypatch):
    monkeypatch.setattr(link_router, 'remember_default_browser', lambda: None)
    server = route_launch(['app.exe', 'https://www.tiktok.com/t/ABC123/'])
    try:
        received = []
        server.set_handler(received.append)
        assert received == [{'action': 'open', 'url': 'https://www.tiktok.com/t/ABC123/'}]
    finally:
        server.close()


def test_is_forbidden_browser_filters_app_and_ie():
    assert link_router._is_forbidden_browser("") is True
    assert link_router._is_forbidden_browser("   ") is True
    assert link_router._is_forbidden_browser("iexplore.exe") is True
    assert link_router._is_forbidden_browser('"C:\\Program Files\\Internet Explorer\\iexplore.exe"') is True
    assert link_router._is_forbidden_browser(f'"{link_router.APP_NAME}.exe" %1') is True
    assert link_router._is_forbidden_browser('"C:\\Program Files\\Google\\Chrome\\chrome.exe" -- "%1"') is False


def test_open_in_default_browser_skips_forbidden_and_opens_valid(monkeypatch):
    monkeypatch.setattr(link_router, "_browser_commands", lambda: ['iexplore.exe', '"C:\\Chrome\\chrome.exe" %1'])
    launched = []
    with patch("subprocess.Popen", side_effect=lambda cmd, **kw: launched.append(cmd) or Mock()):
        result = link_router.open_in_default_browser("https://example.com")
        assert result is True
        assert len(launched) == 1
        assert "chrome.exe" in str(launched[0]).lower()


def test_link_server_set_handler_properly_assigns_handler():
    server = link_router.LinkServer()
    mock_handler = Mock()
    server.set_handler(mock_handler)
    assert server._handler is mock_handler
