from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from tiktok.browser_extension import (
    BRIDGE_HEADER,
    BRIDGE_TOKEN,
    BrowserExtensionBridge,
)


EXTENSION_ORIGIN = "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


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
