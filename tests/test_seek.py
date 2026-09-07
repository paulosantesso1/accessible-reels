from pathlib import Path

import pytest
import wx
from playwright.sync_api import sync_playwright

from ui.shortcuts import SEEK_ACCELERATOR_SPECS, SEEK_SECONDS, action_shortcut


def test_seek_shortcuts_have_requested_keys_and_intervals():
    for action, modifiers, key in SEEK_ACCELERATOR_SPECS:
        seconds = SEEK_SECONDS[action]
        assert key == (wx.WXK_LEFT if seconds < 0 else wx.WXK_RIGHT)
        assert modifiers == (wx.ACCEL_ALT | wx.ACCEL_SHIFT if abs(seconds) == 15 else wx.ACCEL_ALT)
        assert 'Seta para' in action_shortcut(action)


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize('platform', ['tiktok', 'instagram'])
@pytest.mark.parametrize('delta, start, duration, expected', [
    (-15, 50, 120, 35), (15, 50, 120, 65),
    (-30, 50, 120, 20), (30, 50, 120, 80),
    (-30, 10, 120, 0), (30, 110, 120, 120),
    (15, 0, None, None), (999, 50, 120, None),
])
def test_seek_targets_current_video_and_preserves_pause(browser, platform, delta, start, duration, expected):
    page = browser.new_page()
    try:
        page.set_content('<video id="active" style="width:300px;height:300px"></video>'
                         '<video id="other" style="display:none"></video>')
        page.evaluate('''({start, duration, platform}) => {
          const video = document.querySelector('#active');
          Object.defineProperty(video, 'duration', {value: duration ?? NaN});
          video.currentTime = start;
          window.__accessibleTransport = {
            storage: {local: {get: async () => ({}), set: async () => {}}},
            runtime: {onMessage: {addListener: fn => window.listener = fn}}
          };
          window.seek = argument => new Promise(resolve => window.listener(
            {type:'accessible-reels-command', platform, action:'seek', argument}, {}, resolve));
        }''', {'start': start, 'duration': duration, 'platform': platform})
        page.add_script_tag(content=Path(f'ui/web_scripts/{platform}.js').read_text(encoding='utf-8'))
        result = page.evaluate('delta => seek(delta)', delta)
        assert result['ok'] is (expected is not None)
        if expected is not None:
            assert result['position'] == expected
        assert page.eval_on_selector('#active', 'v => v.currentTime') == (start if expected is None else expected)
        assert page.eval_on_selector('#active', 'v => v.paused') is True
        assert page.eval_on_selector('#other', 'v => v.currentTime') == 0
    finally:
        page.close()
