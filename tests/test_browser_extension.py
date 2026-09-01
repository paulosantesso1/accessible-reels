from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

from tiktok.browser_extension import (
    BRIDGE_HEADER,
    BRIDGE_TOKEN,
    EXTENSION_HEADER,
    BrowserExtensionBridge,
    LocalBrowserWorker,
)


EXTENSION_ORIGIN = "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
EXTENSION_DIR = Path(__file__).resolve().parents[1] / "browser_extension"


def _request(
    bridge,
    path,
    *,
    method="GET",
    payload=None,
    authorized=True,
    origin=EXTENSION_ORIGIN,
):
    headers = {"Origin": origin}
    if authorized:
        headers[BRIDGE_HEADER] = BRIDGE_TOKEN
        headers[EXTENSION_HEADER] = EXTENSION_ORIGIN.removeprefix(
            "chrome-extension://"
        )
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{bridge.port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    return urllib.request.urlopen(request, timeout=2)


def test_extension_bridge_rejects_requests_without_local_token():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    try:
        try:
            _request(bridge, "/v1/command", authorized=False)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("a ponte aceitou uma requisição sem token")
    finally:
        bridge.stop()


def test_extension_bridge_accepts_brave_cors_preflight():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    try:
        with _request(
            bridge, "/v1/command", method="OPTIONS", authorized=False
        ) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
            assert BRIDGE_HEADER in response.headers["Access-Control-Allow-Headers"]
            assert EXTENSION_HEADER in response.headers["Access-Control-Allow-Headers"]
    finally:
        bridge.stop()


def test_extension_bridge_rejects_ordinary_web_origin():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    try:
        try:
            _request(bridge, "/v1/command", origin="https://example.com")
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("a ponte aceitou uma página web comum")
    finally:
        bridge.stop()


def test_extension_bridge_accepts_service_worker_request_without_origin():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    caller = threading.Thread(target=lambda: bridge.execute("diagnostics", timeout=2))
    caller.start()
    try:
        with _request(bridge, "/v1/command", origin="") as response:
            assert response.status == 200
            command = json.load(response)
        with _request(
            bridge,
            "/v1/result",
            method="POST",
            payload={"id": command["id"], "ok": True, "message": "ok"},
            origin="",
        ):
            pass
        caller.join(timeout=2)
        assert not caller.is_alive()
    finally:
        bridge.stop()


def test_extension_bridge_rejects_missing_extension_identity():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{bridge.port}/v1/command",
            headers={BRIDGE_HEADER: BRIDGE_TOKEN},
        )
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("a ponte aceitou uma requisição sem identidade")
    finally:
        bridge.stop()


def test_extension_bridge_delivers_command_and_correlates_result():
    bridge = BrowserExtensionBridge(port=0)
    bridge.start()
    outcome = {}

    def execute():
        outcome.update(bridge.execute("toggle_like", timeout=2))

    caller = threading.Thread(target=execute)
    caller.start()
    try:
        with _request(bridge, "/v1/command") as response:
            command = json.load(response)
        assert command["action"] == "toggle_like"
        with _request(
            bridge,
            "/v1/result",
            method="POST",
            payload={"id": command["id"], "ok": True, "state": True},
        ) as response:
            assert json.load(response) == {"ok": True}
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert outcome["state"] is True
    finally:
        bridge.stop()


def test_browser_content_script_registers_accessible_page_shortcuts():
    script = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")
    for action in (
        'return "next"',
        'return "previous"',
        'return "volume_up"',
        'return "volume_down"',
        'p: "toggle"',
        'a: "author"',
        'd: "description"',
        'c: "copy_link"',
        'l: "toggle_like"',
        'f: "toggle_favorite"',
    ):
        assert action in script
    assert 'document.addEventListener("keydown"' in script
    assert 'setAttribute("aria-live", "assertive")' in script


def test_browser_content_script_stabilizes_audio_during_video_transitions():
    script = (EXTENSION_DIR / "content.js").read_text(encoding="utf-8")
    assert "scheduleAudioPreference" in script
    assert "stabilizeAudio" in script
    assert 'attributeFilter: ["muted", "src"]' in script
    assert 'video.addEventListener("volumechange"' in script
    assert "document.querySelectorAll(\"video\").forEach(applyAudioPreference)" in script
    assert "applyingAudio.delete(video)" in script


def test_extension_icon_can_wake_or_open_tiktok():
    script = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    assert "chrome.action.onClicked.addListener" in script
    assert 'chrome.tabs.create({url: "https://www.tiktok.com/"' in script


def test_extension_can_close_only_the_controlled_tiktok_tab():
    script = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    assert "async function closeTikTokTab()" in script
    assert "await chrome.tabs.remove(tab.id)" in script
    assert 'command.action === "close_tiktok"' in script


class _ShutdownBridge:
    def __init__(self):
        self.actions = []
        self.stopped = False

    def execute(self, action, _argument=None, timeout=12):
        self.actions.append((action, timeout))
        return {"ok": True}

    def stop(self):
        self.stopped = True


def test_local_worker_closes_controlled_tab_when_application_exits():
    worker = LocalBrowserWorker(lambda _event: None)
    bridge = _ShutdownBridge()
    worker._bridge = bridge
    worker.start()
    worker.shutdown()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert bridge.actions == [("close_tiktok", 4)]
    assert bridge.stopped is True


def test_local_worker_disconnect_preserves_controlled_tab():
    worker = LocalBrowserWorker(lambda _event: None)
    bridge = _ShutdownBridge()
    worker._bridge = bridge
    worker.start()
    worker.disconnect()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert bridge.actions == []
    assert bridge.stopped is True
