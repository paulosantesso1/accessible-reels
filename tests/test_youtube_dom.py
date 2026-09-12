from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 900, "height": 700})
    page.set_content('''
      <base href="https://www.youtube.com/shorts/test-video">
      <style>video { display:block; width:500px; height:650px }</style>
      <video id="active"></video>
    ''')
    page.evaluate('''() => {
      window.ytStorage = {accessibleReelsYouTubeVolume: 0.35, accessibleReelsYouTubeMuted: false};
      window.__accessibleTransport = {
        storage: {local: {
          get: async () => window.ytStorage,
          set: async values => Object.assign(window.ytStorage, values)
        }},
        runtime: {onMessage: {addListener: handler => window.ytListener = handler}}
      };
      window.ytCommand = (action, argument) => new Promise(resolve =>
        window.ytListener({type:'accessible-reels-command', platform:'youtube', action, argument}, {}, resolve));
    }''')
    page.evaluate(Path("ui/web_scripts/audio_guard.js").read_text(encoding="utf-8"))
    page.evaluate(Path("ui/web_scripts/youtube.js").read_text(encoding="utf-8"))
    yield page
    page.close()


def command(page, action):
    return page.evaluate("action => window.ytCommand(action)", action)


def test_youtube_audio_preference_is_saved_and_reapplied(page):
    assert page.locator("#active").evaluate("video => video.volume") == pytest.approx(0.35)
    assert command(page, "volume_up") == {"ok": True, "volume": 0.4, "muted": False}
    assert page.evaluate("window.ytStorage") == {
        "accessibleReelsYouTubeVolume": pytest.approx(0.4),
        "accessibleReelsYouTubeMuted": False,
    }

    page.evaluate('''() => {
      const video = document.querySelector('#active');
      video.volume = 1;
      video.muted = true;
    }''')
    assert page.locator("#active").evaluate("video => video.volume") == pytest.approx(0.4)
    assert page.locator("#active").evaluate("video => video.muted") is False


def test_youtube_search_collects_shorts_from_current_card_layout(page):
    page.evaluate('''() => {
      document.body.innerHTML = `
        <ytm-shorts-lockup-view-model>
          <a href="https://www.youtube.com/shorts/AbCdEfGhI_j"><img></a>
          <h3><a href="https://www.youtube.com/shorts/AbCdEfGhI_j" title="Curiosidade histórica">Curiosidade histórica</a></h3>
        </ytm-shorts-lockup-view-model>`;
    }''')
    result = command(page, "collect_search_results")
    assert result['ok'] is True
    assert result['results'] == [{
        'url': 'https://www.youtube.com/shorts/AbCdEfGhI_j',
        'author': '',
        'description': 'Curiosidade histórica',
    }]


def test_youtube_automatic_play_does_not_pause_an_autoplaying_short(page):
    page.evaluate('''() => {
      const video = document.querySelector('#active');
      let paused = false;
      Object.defineProperty(video, 'paused', {get: () => paused});
      video.play = async () => { paused = false; };
      video.pause = () => { paused = true; };
    }''')
    assert command(page, 'play') == {'ok': True, 'paused': False}
    assert command(page, 'toggle') == {'ok': True, 'paused': True}
