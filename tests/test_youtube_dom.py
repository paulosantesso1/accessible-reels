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
      window.dispatchedKeys = [];
      window.__accessibleTransport = {
        storage: {local: {
          get: async () => window.ytStorage,
          set: async values => Object.assign(window.ytStorage, values)
        }},
        runtime: {
          onMessage: {addListener: handler => window.ytListener = handler},
          sendMessage: async ({type, key}) => {
            if (type === 'accessible-reels-trusted-key') {
              window.dispatchedKeys.push(key);
              document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
              document.dispatchEvent(new KeyboardEvent('keyup', {key, bubbles: true, cancelable: true}));
            }
            return {ok: true};
          }
        }
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


@pytest.mark.parametrize("action, key", [("next", "ArrowDown"), ("previous", "ArrowUp")])
def test_youtube_navigation_uses_native_key_press_before_any_button(page, action, key):
    # No navigation button at all: only a real key press (which the mocked
    # transport turns into a genuine keydown/keyup) can advance this Short,
    # mirroring how YouTube's own player reacts to arrow keys regardless of
    # whatever nav-button markup it currently ships.
    page.evaluate("""key => {
      document.addEventListener('keydown', event => {
        if (event.key === key) document.querySelector('video').setAttribute('src', 'next.mp4');
      });
    }""", key)
    result = command(page, action)
    assert result['ok'] is True
    assert page.evaluate("window.dispatchedKeys") == [key]


@pytest.mark.parametrize("action, selector", [
    ("next", "navigation-button-down"), ("previous", "navigation-button-up"),
])
def test_youtube_navigation_falls_back_to_the_nav_button(page, action, selector):
    # No keydown listener responds here, so the key press is a no-op and the
    # existing button-click fallback must still take over.
    page.evaluate("""selector => {
      const button = document.createElement('button');
      button.id = selector;
      button.onclick = () => document.querySelector('video').setAttribute('src', 'next.mp4');
      document.body.append(button);
    }""", selector)
    result = command(page, action)
    assert result['ok'] is True


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


def test_youtube_profile_is_canonicalized_from_channel_shorts_link(page):
    page.evaluate('''() => {
      document.body.innerHTML = `
        <div style="width:500px;height:650px">
          <video id="active"></video>
          <a href="/@canal/shorts">@canal</a>
        </div>`;
    }''')

    result = command(page, 'refresh_info')

    assert result['ok'] is True
    assert result['profile_url'] == 'https://www.youtube.com/@canal/shorts'


def test_youtube_follow_status_is_unknown_without_an_explicit_control(page):
    page.evaluate('''() => {
      document.body.innerHTML = `
        <div style="width:500px;height:650px">
          <video id="active"></video><ytd-channel-name>@canal</ytd-channel-name>
        </div>`;
    }''')

    result = command(page, 'author')

    assert result['ok'] is True
    assert result['author'] == '@canal (Não foi possível verificar se você segue)'


def test_youtube_follow_uses_explicit_accessible_state(page):
    page.evaluate('''() => {
      document.body.innerHTML = `
        <ytd-reel-video-renderer style="display:block;width:500px;height:650px">
          <video id="active"></video><ytd-channel-name>@canal</ytd-channel-name>
          <div id="subscribe-button"><button aria-label="Inscrever-se em @canal" aria-pressed="false"
            onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') === 'false' ? 'true' : 'false')"></button></div>
        </ytd-reel-video-renderer>`;
    }''')

    assert command(page, 'author')['author'].endswith('(Não segue)')
    assert command(page, 'toggle_follow') == {'ok': True, 'state': True}
    assert command(page, 'author')['author'].endswith('(Você já segue)')
    assert command(page, 'toggle_follow') == {'ok': True, 'state': False}


def add_shorts_menu(page, items):
    page.evaluate('''items => {
      const video = document.querySelector('#active');
      const renderer = document.createElement('ytd-reel-video-renderer');
      video.replaceWith(renderer);
      const menu = document.createElement('ytd-menu-renderer');
      const more = document.createElement('button');
      more.setAttribute('aria-label', 'Mais ações');
      more.style.cssText = 'width:40px;height:30px';
      more.onclick = () => {
        const popup = document.createElement('div');
        popup.style.cssText = 'position:fixed;left:600px;top:100px;width:250px';
        for (const text of items) {
          const item = document.createElement('tp-yt-paper-item');
          item.style.cssText = 'display:block;width:240px;height:30px';
          item.textContent = text;
          item.onclick = () => { window.pressed = text; popup.remove(); };
          popup.append(item);
        }
        document.body.append(popup);
      };
      menu.append(more);
      renderer.append(video, menu);
    }''', items)


def test_youtube_not_interested_uses_the_shorts_menu(page):
    add_shorts_menu(page, ["Descrição", "Não tenho interesse", "Denunciar"])
    assert command(page, "not_interested") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "Não tenho interesse"


def test_youtube_not_interested_reports_a_menu_without_the_option(page):
    add_shorts_menu(page, ["Descrição", "Denunciar"])
    result = command(page, "not_interested")
    assert result["ok"] is False and "Não tenho interesse" in result["error"]
    assert page.evaluate("window.pressed") is None


def test_youtube_not_interested_accepts_a_follow_up_panel_asking_for_a_reason(page):
    add_shorts_menu(page, ["Descrição", "Não tenho interesse", "Denunciar"])
    page.evaluate('''() => new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        node.querySelectorAll?.('tp-yt-paper-item').forEach(item => {
          item.onclick = () => {
            const panel = document.createElement('div');
            panel.setAttribute('role', 'dialog');
            panel.style.cssText = 'position:fixed;left:300px;top:300px;width:200px;height:100px';
            panel.textContent = 'Irrelevante Chato Outro';
            document.body.append(panel);
          };
        });
      }
    }).observe(document.body, {childList: true})''')
    assert command(page, "not_interested") == {"ok": True, "follow_up": True, "advance": True}


def test_youtube_not_interested_closes_the_reason_panel_and_asks_to_skip(page):
    add_shorts_menu(page, ["Descrição", "Não tenho interesse"])
    page.evaluate('''() => new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) {
        node.querySelectorAll?.('tp-yt-paper-item').forEach(item => {
          item.onclick = () => {
            const panel = document.createElement('div');
            panel.setAttribute('role', 'dialog');
            panel.style.cssText = 'position:fixed;left:300px;top:300px;width:200px;height:100px';
            panel.innerHTML = 'Irrelevante Chato <button style="width:60px;height:20px">Fechar</button>';
            panel.querySelector('button').onclick = () => panel.remove();
            document.body.append(panel);
          };
        });
      }
    }).observe(document.body, {childList: true})''')
    assert command(page, "not_interested") == {"ok": True, "advance": True}
    assert page.evaluate("document.querySelector('[role=dialog]')") is None


def test_youtube_not_interested_does_not_skip_when_the_short_already_changed(page):
    add_shorts_menu(page, ["Não tenho interesse"])
    page.evaluate('''() => {
      new MutationObserver(records => {
        for (const record of records) for (const node of record.addedNodes) {
          node.querySelectorAll?.('tp-yt-paper-item').forEach(item => {
            item.onclick = () => {
              const next = document.createElement('video');
              next.id = 'next';
              document.querySelector('#active').replaceWith(next);
              item.parentElement.remove();
            };
          });
        }
      }).observe(document.body, {childList: true});
    }''')
    assert command(page, "not_interested") == {"ok": True}
