from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import base64

import pytest
from playwright.sync_api import sync_playwright

from ui.browser_download import BrowserDownload


@pytest.mark.parametrize('invalid', [False, True])
def test_browser_session_transfer(tmp_path, monkeypatch, invalid):
    payload = b'HTML error' if invalid else b'\x00\x00\x00\x18ftypmp42' + bytes(range(256)) * 1024
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route('https://www.tiktok.com/', lambda route: route.fulfill(body='<html></html>', content_type='text/html'))
        page.route('https://v.tiktokcdn.com/test.mp4', lambda route: route.fulfill(
            body=payload, headers={'content-type': 'video/mp4', 'content-length': str(len(payload)),
                                   'access-control-allow-origin': 'https://www.tiktok.com',
                                   'access-control-allow-credentials': 'true'}))
        page.goto('https://www.tiktok.com/')
        def evaluate(view, script, callback):
            try:
                value = page.evaluate(script)
            except Exception:
                callback(None, 'failed')
            else:
                callback(value, None)
        monkeypatch.setattr('ui.browser_download.evaluate', evaluate)
        monkeypatch.setattr('ui.browser_download.wx.CallLater', Mock())
        callback = Mock()
        client = SimpleNamespace(platform='TikTok', alive=True, generation=0, view=None)
        destination = tmp_path / 'Meu vídeo escolhido.mp4'
        destination.write_bytes(b'original')
        transfer = BrowserDownload(client, 'https://v.tiktokcdn.com/test.mp4', tmp_path, Mock(), callback,
                                   destination=destination)
        transfer.start()
        path, error = callback.call_args.args
        if invalid:
            assert path is None and error
            assert destination.read_bytes() == b'original'
            assert list(tmp_path.iterdir()) == [destination]
        else:
            assert error is None
            assert path == destination
            assert path.read_bytes() == payload
        browser.close()


def test_navigation_cancels_transfer(tmp_path, monkeypatch):
    evaluate = Mock()
    monkeypatch.setattr('ui.browser_download.evaluate', evaluate)
    client = SimpleNamespace(platform='TikTok', alive=True, generation=0, view=None)
    callback = Mock()
    transfer = BrowserDownload(client, 'https://v.tiktokcdn.com/test.mp4', tmp_path, Mock(), callback)
    client.generation += 1
    transfer.start()
    assert callback.call_args.args[0] is None
    assert not list(tmp_path.iterdir())
    evaluate.assert_not_called()
