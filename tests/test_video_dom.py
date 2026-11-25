from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tiktok.video_controls import TikTokVideoController, VideoControlError
from tiktok.window_controller import playwright_driver_pid


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        assert playwright_driver_pid(playwright) is not None
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 800, "height": 600})
    yield page
    page.close()


def install_embedded_tiktok(page):
    page.evaluate("""() => {
      window.__accessibleTransport = {
        storage: {local: {get: async () => ({}), set: async () => {}}},
        runtime: {
          onMessage: {addListener: fn => { window.commandListener = fn; }},
          sendMessage: async ({type, x, y, key}) => {
            if (type === 'accessible-reels-trusted-key') {
              window.dispatchedKeys = (window.dispatchedKeys || []).concat(key);
              document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
              document.dispatchEvent(new KeyboardEvent('keyup', {key, bubbles: true, cancelable: true}));
              return {ok: true};
            }
            document.elementFromPoint(x, y).click();
            return {ok: true};
          }
        }
      };
      window.command = (action, argument) => new Promise(resolve =>
        window.commandListener({type: 'accessible-reels-command', action, argument}, {}, resolve));
      for (const video of document.querySelectorAll('video')) {
        video.testPaused = video.id !== 'active';
        Object.defineProperty(video, 'paused', {get: () => video.testPaused});
        video.pause = () => { video.testPaused = true; };
        video.play = async () => { video.testPaused = false; };
      }
    }""")
    page.add_script_tag(content=(
        Path(__file__).resolve().parents[1] / "ui/web_scripts/tiktok.js"
    ).read_text(encoding="utf-8"))


def load_tiktok_page(page, path_or_url, body):
    page.route("https://www.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=body
    ))
    page.route("https://live.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=body
    ))
    target = path_or_url if path_or_url.startswith("http") else ("https://www.tiktok.com" + path_or_url)
    page.goto(target)


def test_download_identifies_active_feed_media_without_search(page):
    page.set_content('<video id="active" style="width:600px;height:400px"></video>')
    page.evaluate("Object.defineProperty(document.querySelector('video'), 'currentSrc', {value: 'https://v.tiktokcdn.com/current.mp4'})")
    install_embedded_tiktok(page)
    result = page.evaluate("command('download_link')")
    assert result['ok'] is True
    assert result['media_url'] == 'https://v.tiktokcdn.com/current.mp4'


@pytest.mark.parametrize('state_kind', ['hydration', 'react', 'react_array'])
def test_download_resolves_blob_from_matching_feed_item(page, state_kind):
    page.set_content('''<div data-video-id="7682105671503990037">
      <video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana/video/7682105671503990037">ana</a></div>''')
    page.evaluate('''kind => {
      const video = document.querySelector('video');
      Object.defineProperty(video, 'currentSrc', {value: 'blob:https://www.tiktok.com/local'});
      const data = {items: [
        {id: '111', video: {playAddr: 'https://v.tiktokcdn.com/wrong.mp4'}},
        {id: '7682105671503990037', video: {playAddr: 'https://v.tiktokcdn.com/correct.mp4?sign=test'}}
      ]};
      if (kind === 'react_array') data.items[1].video.playAddr = [{src: data.items[1].video.playAddr}];
      if (kind.startsWith('react')) {
        video.parentElement.__reactProps$test = {children: {props: data}};
      } else {
        const script = document.createElement('script');
        script.type = 'application/json'; script.id = 'SIGI_STATE';
        script.textContent = JSON.stringify(data); document.body.append(script);
      }
    }''', state_kind)
    install_embedded_tiktok(page)
    result = page.evaluate("command('download_link')")
    assert result['ok'] is True
    assert result['media_url'] == 'https://v.tiktokcdn.com/correct.mp4?sign=test'


def test_download_captures_dynamic_feed_response(page):
    page.set_content('''<div data-video-id="7682105671503990037"><video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana/video/7682105671503990037">ana</a></div>''')
    page.evaluate('''() => {
      window.fetch = async () => new Response(JSON.stringify({itemList: [
        {id: '7682105671503990037', video: {playAddr: 'https://v.tiktokcdn.com/live.mp4'}}
      ]}), {headers: {'content-type': 'application/json'}});
    }''')
    page.evaluate(Path('ui/web_scripts/media_capture.js').read_text(encoding='utf-8'))
    install_embedded_tiktok(page)
    page.evaluate("fetch('https://www.tiktok.com/api/recommend/item_list/')")
    page.wait_for_function('window.__accessibleMediaItems.size === 1')
    result = page.evaluate("command('download_link')")
    assert result['media_url'] == 'https://v.tiktokcdn.com/live.mp4'


def test_search_waits_for_delayed_cards_without_needing_a_video(page):
    page.set_content('<main id="results"></main>')
    install_embedded_tiktok(page)
    page.evaluate('''() => setTimeout(() => {
      document.getElementById('results').innerHTML =
        '<a href="https://www.tiktok.com/@ana/video/123"><img alt="Resultado tardio"></a>';
    }, 350)''')
    result = page.evaluate("command('collect_search_results')")
    assert result['ok'] is True
    assert result['results'] == [{'url': 'https://www.tiktok.com/@ana/video/123',
                                  'author': '@ana', 'description': 'Resultado tardio'}]


def test_search_collects_video_cards(page):
    page.set_content('''<main>
      <div data-e2e="search-card-video-container">
        <a href="https://www.tiktok.com/@bia/video/456"><img alt="Vídeo da Bia"></a>
      </div>
      <a href="https://www.tiktok.com/@ana/video/123"><img alt="Vídeo da Ana"></a>
      <a href="https://www.tiktok.com/@ana/other/page">Outra página</a>
    </main>''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('collect_search_results')")
    assert result['ok'] is True
    assert result['results'] == [
        {'url': 'https://www.tiktok.com/@bia/video/456', 'author': '@bia', 'description': 'Vídeo da Bia'},
        {'url': 'https://www.tiktok.com/@ana/video/123', 'author': '@ana', 'description': 'Vídeo da Ana'},
    ]


TIKTOK_COMMENT_PAGE = '''
  <style>
    video { display:block; width:400px; height:300px; }
    [role=button], button { display:block; width:140px; height:30px; }
    #panel { display:none; }
    #panel [contenteditable] { display:block; width:300px; height:40px; }
    [data-e2e=comment-level-1] { display:block; min-height:20px; }
  </style>
  <article>
    <video id="active"></video>
    <div role="button" data-e2e="comment-icon" aria-label="Comentários"
      onclick="document.getElementById('panel').style.display='block'">Comentários</div>
  </article>
  <section id="panel">
    <div data-e2e="comment-level-1">ana: Primeiro comentário</div>
    <div id="list"></div>
    <div data-e2e="comment-input">
      <div contenteditable="true" role="textbox"
        oninput="document.getElementById('post').setAttribute('aria-disabled', String(!this.textContent.trim()))"></div>
    </div>
    <button id="post" data-e2e="comment-post" aria-disabled="true" onclick="
      const editor = document.querySelector('[data-e2e=comment-input] [contenteditable]');
      if (this.getAttribute('aria-disabled') === 'true') return;
      const row = document.createElement('div');
      row.dataset.e2e = 'comment-level-1';
      row.textContent = 'eu: ' + editor.textContent;
      document.getElementById('list').append(row);
      editor.textContent = '';
      window.published = (window.published || 0) + 1;">Publicar</button>
    <button aria-label="Fechar" onclick="document.getElementById('panel').style.display='none'">X</button>
  </section>
'''


def install_trusted_typing(page, accept=True):
    """Fake the application side: real clicks focus, trusted text types into the focused field."""
    page.evaluate('''accept => {
      window.typed = [];
      window.__accessibleTransport.runtime.sendMessage = async message => {
        if (message.type === 'accessible-reels-trusted-text') {
          window.typed.push(message.text);
          if (accept) document.execCommand('insertText', false, message.text);
          return {ok: true};
        }
        const hit = document.elementFromPoint(message.x, message.y);
        hit.focus();
        hit.click();
        return {ok: true};
      };
    }''', accept)


def test_tiktok_comment_is_typed_by_the_application_and_confirmed(page):
    page.set_content(TIKTOK_COMMENT_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result == {'ok': True}
    assert page.evaluate('window.typed') == ['Comentário novo']
    assert page.evaluate('window.published') == 1
    assert page.locator('#list').inner_text() == 'eu: Comentário novo'
    assert not page.locator('#panel').is_visible()


def test_tiktok_comment_is_not_published_when_the_editor_rejects_the_text(page):
    page.set_content(TIKTOK_COMMENT_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page, accept=False)
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result['ok'] is False
    assert 'não aceitou o texto' in result['error']
    assert page.evaluate('window.published') is None


def test_tiktok_comment_keeps_a_draft_left_on_the_page(page):
    page.set_content(TIKTOK_COMMENT_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("document.querySelector('[contenteditable]').textContent = 'Rascunho'")
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result['ok'] is False
    assert 'rascunho' in result['error']
    assert page.evaluate('window.typed') == []
    assert page.locator('[contenteditable]').inner_text() == 'Rascunho'


def test_tiktok_comment_reports_when_the_network_does_not_show_it(page):
    page.set_content(TIKTOK_COMMENT_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    # The site accepts the click but never lists the comment.
    page.evaluate("document.getElementById('post').onclick = () => { window.published = 1; }")
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result['ok'] is False
    assert 'não foi confirmado' in result['error']


def test_initial_details_refresh_waits_for_delayed_video(page):
    page.set_content('<main id="player"></main>')
    install_embedded_tiktok(page)
    page.evaluate('''() => setTimeout(() => {
      document.getElementById('player').innerHTML =
        '<div><video style="width:600px;height:400px"></video>' +
        '<a href="https://www.tiktok.com/@ana">@ana</a>' +
        '<a href="https://www.tiktok.com/@ana/video/123">Vídeo</a></div>';
    }, 350)''')
    result = page.evaluate("command('refresh_info')")
    assert result['ok'] is True
    assert result['author'] == '@ana'


def test_tiktok_follow_status_is_unknown_without_an_explicit_control(page):
    page.set_content('''<article><video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana">@ana</a></article>''')
    install_embedded_tiktok(page)

    result = page.evaluate("command('author')")

    assert result['ok'] is True
    assert result['author'] == '@ana'
    assert result['follow_state'] is None
    assert result['needs_profile_follow'] is True


def test_tiktok_follow_clicks_feed_button_when_it_exposes_a_state(page):
    page.set_content('''<article><video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana">@ana</a>
      <button data-e2e="feed-follow" aria-label="Seguir @ana" aria-pressed="false"
        style="width:80px;height:40px"
        onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') === 'false' ? 'true' : 'false')"></button>
      </article>''')
    install_embedded_tiktok(page)

    assert page.evaluate("command('author')")['follow_state'] is False
    result = page.evaluate("command('toggle_follow')")
    assert result['follow_click_sent'] is True
    assert result['expected_state'] is True
    assert page.evaluate("command('author')")['follow_state'] is True


def test_feed_follow_without_accessible_state_uses_profile_toggle(page):
    page.set_content('''<article><video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana">@ana</a>
      <button data-e2e="feed-follow" style="width:80px;height:40px"
        onclick="window.clicks=(window.clicks || 0)+1"></button></article>''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('toggle_follow')")
    assert result['needs_follow_state'] is True
    assert result['follow_click_sent'] is False
    assert result['profile_url'] == 'https://www.tiktok.com/@ana'
    assert 'state' not in result
    assert page.evaluate('window.clicks') is None


def test_tiktok_follow_requires_a_feed_button_for_the_real_click(page):
    page.set_content('''<article><video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana">@ana</a>
      <button data-e2e="feed-follow" aria-label="Seguir @ana" aria-pressed="false"
        style="width:80px;height:40px" onclick="this.remove()"></button>
      </article>''')
    install_embedded_tiktok(page)

    result = page.evaluate("command('toggle_follow')")

    assert result['follow_click_sent'] is True
    assert result['expected_state'] is True


def test_tiktok_profile_follow_reads_and_changes_explicit_button_state(page):
    load_tiktok_page(page, '/@ana', '''
      <aside><button data-e2e="follow-button" style="width:100px;height:40px"
        onclick="window.wrongProfileClicked=true">Follow suggested account</button></aside>
      <main style="width:600px;height:400px"><header style="width:500px;height:100px">
        <button data-e2e="follow-button" aria-label="Seguir @ana" aria-pressed="false"
          style="width:100px;height:40px"
          onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') === 'false' ? 'true' : 'false')"></button>
      </header></main>''')
    install_embedded_tiktok(page)
    const_argument = "{toggle:%s, profile_url:'https://www.tiktok.com/@ana'}"

    assert page.evaluate("command('profile_follow', " + const_argument % 'false' + ")") == {'ok': True, 'state': False}
    assert page.evaluate("command('profile_follow', " + const_argument % 'true' + ")") == {'ok': True, 'state': True}
    assert page.evaluate("command('profile_follow', " + const_argument % 'true' + ")") == {'ok': True, 'state': False}
    assert page.evaluate("Boolean(window.wrongProfileClicked)") is False


def test_tiktok_profile_message_button_is_not_follow_evidence(page):
    load_tiktok_page(page, '/@ana', '''<main><header style="width:500px;height:100px">
      <button style="width:100px;height:40px">Message</button>
    </header></main>''')
    install_embedded_tiktok(page)

    result = page.evaluate("""async () => {
      setTimeout(() => {
        const follow = document.createElement('button');
        follow.dataset.e2e = 'follow-button';
        follow.textContent = 'Follow';
        follow.style = 'width:100px;height:40px';
        document.querySelector('header').append(follow);
      }, 250);
      return await command('profile_follow', {
        toggle:false, profile_url:'https://www.tiktok.com/@ana'
      });
    }""")

    assert result == {'ok': True, 'state': False}


def test_profile_read_waits_for_initial_state_to_settle(page):
    load_tiktok_page(page, '/@ana', '''<header style="width:500px;height:100px">
      <button data-e2e="follow-button" style="width:100px;height:40px">Follow</button>
    </header>''')
    install_embedded_tiktok(page)
    result = page.evaluate("""async () => {
      setTimeout(() => document.querySelector('button').textContent = 'Following', 400);
      return command('profile_follow', {toggle:false, profile_url:'https://www.tiktok.com/@ana'});
    }""")
    assert result == {'ok': True, 'state': True}


def test_profile_toggle_does_not_confirm_a_brief_optimistic_change(page):
    load_tiktok_page(page, '/@ana', '''<header style="width:500px;height:100px">
      <button data-e2e="follow-button" style="width:100px;height:40px"
        onclick="this.textContent='Following'; setTimeout(() => this.textContent='Follow', 300)">Follow</button>
    </header>''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('profile_follow', {toggle:true, profile_url:'https://www.tiktok.com/@ana'})")
    assert result['ok'] is False
    assert 'não confirmou' in result['error']


def test_tiktok_profile_unfollow_uses_follow_icon_and_verifies_replacement(page):
    load_tiktok_page(page, '/@ana', '''<main style="width:600px;height:400px"><header style="width:500px;height:100px">
      <button style="width:100px;height:40px">Message</button>
      <div role="button" class="DivFollowIcon-test" aria-label="Unfollow @ana"
        style="width:40px;height:40px" onclick="this.outerHTML='<button data-e2e=&quot;follow-button&quot; style=&quot;width:100px;height:40px&quot;>Follow</button>'"></div>
      </header></main>''')
    install_embedded_tiktok(page)

    argument = "{toggle:%s, profile_url:'https://www.tiktok.com/@ana'}"
    assert page.evaluate("command('profile_follow', " + argument % 'false' + ")") == {'ok': True, 'state': True}
    assert page.evaluate("command('profile_follow', " + argument % 'true' + ")") == {'ok': True, 'state': False}


def test_tiktok_profile_follow_refuses_a_different_profile(page):
    load_tiktok_page(page, '/@outra', '''<main><header style="width:500px;height:100px">
      <button data-e2e="follow-button" style="width:100px;height:40px">Follow</button>
    </header></main>''')
    install_embedded_tiktok(page)

    result = page.evaluate("""command('profile_follow', {
      toggle:true, profile_url:'https://www.tiktok.com/@ana'
    })""")

    assert result['ok'] is False
    assert 'não corresponde ao autor esperado' in result['error']


def test_tiktok_profile_follow_reports_captcha_without_clicking(page):
    load_tiktok_page(page, '/@ana', '''<main><header style="width:500px;height:100px">
      <div class="secsdk-captcha-wrapper" style="width:200px;height:80px">Verify</div>
    </header></main>''')
    install_embedded_tiktok(page)

    result = page.evaluate("""command('profile_follow', {
      toggle:true, profile_url:'https://www.tiktok.com/@ana'
    })""")

    assert result['ok'] is False
    assert 'exige uma verificação' in result['error']
    assert 'Não foi possível confirmar' in result['error']


def test_profile_link_ignores_video_permalink_before_author_link(page):
    page.set_content('''<div>
      <video id="active" style="width:600px;height:400px"></video>
      <a href="https://www.tiktok.com/@ana/video/7682105671503990037">Vídeo</a>
      <a href="https://www.tiktok.com/@ana">@ana</a>
    </div>''')
    install_embedded_tiktok(page)

    result = page.evaluate("command('refresh_info')")

    assert result['ok'] is True
    assert result['profile_url'] == 'https://www.tiktok.com/@ana'


def test_search_keeps_cards_that_tiktok_virtualizes_during_collection(page):
    page.set_content('''<main id="results">
      <a href="https://www.tiktok.com/@ana/video/123"><img alt="Primeiro resultado"></a>
    </main>''')
    install_embedded_tiktok(page)
    page.evaluate('''() => setTimeout(() => {
      document.getElementById('results').innerHTML =
        '<a href="https://www.tiktok.com/@bia/video/456"><img alt="Segundo resultado"></a>';
    }, 400)''')
    result = page.evaluate("command('collect_search_results')")
    assert result['ok'] is True
    assert [item['url'] for item in result['results']] == [
        'https://www.tiktok.com/@ana/video/123',
        'https://www.tiktok.com/@bia/video/456',
    ]


def test_embedded_play_starts_paused_video_and_keeps_playing_video(page):
    page.set_content('<video id="active" style="width:300px;height:300px"></video>')
    install_embedded_tiktok(page)
    page.eval_on_selector('video', 'v => v.pause()')
    assert page.evaluate("command('play')") == {'ok': True, 'paused': False}
    assert page.evaluate("command('play')") == {'ok': True, 'paused': False}


def test_embedded_play_retries_after_tiktok_replaces_an_empty_video_source(page):
    page.set_content('<video id="active" style="width:300px;height:300px"></video>')
    install_embedded_tiktok(page)
    page.evaluate('''() => {
      const video = document.querySelector('#active');
      let attempts = 0;
      Object.defineProperty(video, 'currentSrc', {configurable: true, value: ''});
      Object.defineProperty(video, 'readyState', {configurable: true, value: 0});
      video.play = () => {
        attempts += 1;
        if (attempts === 1) {
          setTimeout(() => {
            Object.defineProperty(video, 'currentSrc', {configurable: true, value: 'https://v.tiktokcdn.com/ready.mp4'});
            Object.defineProperty(video, 'readyState', {configurable: true, value: HTMLMediaElement.HAVE_METADATA});
          }, 200);
          return Promise.reject(new DOMException('Failed to load because no supported source was found.', 'NotSupportedError'));
        }
        video.testPaused = false;
        return Promise.resolve();
      };
    }''')
    assert page.evaluate("command('play')") == {'ok': True, 'paused': False}


def test_embedded_speed_commands_use_quarter_step_presets(page):
    page.set_content('<video id="active" style="width:300px;height:300px"></video>')
    install_embedded_tiktok(page)
    assert page.evaluate("command('speed_down')") == {'ok': True, 'playbackRate': 0.75}
    assert page.evaluate("command('speed_up')") == {'ok': True, 'playbackRate': 1}
    assert page.evaluate("command('speed_up')") == {'ok': True, 'playbackRate': 1.25}


def test_embedded_volume_moves_by_five_percent_with_exact_bounds(page):
    page.set_content('<video id="active" style="width:300px;height:300px"></video>')
    page.eval_on_selector('video', 'video => video.volume = 0')
    install_embedded_tiktok(page)
    for step in range(1, 23):
        result = page.evaluate("command('volume_up')")
        assert result['ok'] is True
        assert result['volume'] == pytest.approx(min(step * 5, 100) / 100)
    for step in range(1, 23):
        result = page.evaluate("command('volume_down')")
        assert result['ok'] is True
        assert result['volume'] == pytest.approx(max(100 - step * 5, 0) / 100)


def test_embedded_copy_link_uses_active_author_and_video_id_without_anchors(page):
    page.set_content('''
      <article data-video-id="222">
        <span data-e2e="video-author-uniqueid">correto</span>
        <video id="active" style="width:300px;height:300px"></video>
      </article>
    ''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('copy_link')")
    assert result['ok'] is True
    assert result['link'] == 'https://www.tiktok.com/@correto/video/222'


def test_embedded_link_is_never_taken_from_another_video_on_the_page(page):
    # A direct video page lists other videos outside the active one's own card.
    load_tiktok_page(page, '/@ana/video/222', '''
      <article><span data-e2e="browse-username">ana</span>
        <video id="active" style="width:300px;height:200px"></video></article>
      <section><a href="/@outra/video/111">Outro vídeo</a></section>''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('refresh_info')")['link'] == 'https://www.tiktok.com/@ana/video/222'
    assert page.evaluate("command('copy_link')")['link'] == 'https://www.tiktok.com/@ana/video/222'


def test_embedded_link_stays_empty_instead_of_naming_another_video(page):
    load_tiktok_page(page, '/foryou', '''
      <article><video id="active" style="width:300px;height:200px"></video></article>
      <section><a href="/@outra/video/111">Outro vídeo</a></section>''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('refresh_info')")['link'] == ''


def test_embedded_copy_link_uses_current_tiktok_feed_wrapper_id(page):
    page.set_content('''
      <article>
        <a href="/@correto">correto</a>
        <div id="xgwrapper-0-7667796792532094209">
          <div><video id="active" style="width:300px;height:300px"></video></div>
        </div>
      </article>
    ''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('copy_link')")
    assert result['ok'] is True
    assert result['link'] == 'https://www.tiktok.com/@correto/video/7667796792532094209'


def test_embedded_copy_link_uses_matching_tiktok_page_state(page):
    page.set_content('''
      <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
        {"feed":{"id":"333","desc":"descrição atual","author":{"uniqueId":"correto"}}}
      </script>
      <article>
        <span data-e2e="video-author-uniqueid">@correto</span>
        <div data-e2e="video-desc">descrição atual</div>
        <video id="active" style="width:300px;height:300px"></video>
      </article>
    ''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('copy_link')")
    assert result['ok'] is True
    assert result['link'] == 'https://www.tiktok.com/@correto/video/333'


def test_embedded_copy_link_uses_tiktok_share_when_no_canonical_link_is_available(page):
    page.set_content('''
      <article>
        <video id="active" style="width:300px;height:300px"></video>
        <button data-e2e="share-button" style="width:40px;height:40px"
          onclick="document.querySelector('#copy').style.display='block'">Compartilhar</button>
      </article>
      <div id="copy" style="display:none;width:80px;height:40px"
        onclick="window.tiktokCopied=true">Copiar link</div>
    ''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('copy_link')") == {'ok': True, 'nativeCopied': True}
    assert page.evaluate('window.tiktokCopied') is True


def test_embedded_copy_link_accepts_unlabeled_tiktok_copy_icon(page):
    page.set_content('''
      <article>
        <video id="active" style="width:300px;height:300px"></video>
        <button data-e2e="share-button" style="width:40px;height:40px"
          onclick="document.querySelector('#panel').style.display='block'">Compartilhar</button>
      </article>
      <div id="panel" style="display:none">
        <div data-e2e="share-group">Destinatários</div>
        <button id="more" style="width:40px;height:40px"
          onclick="window.tiktokCopied=true; document.querySelector('[data-e2e=share-group]').remove()"></button>
        <button aria-label="close" style="width:40px;height:40px"></button>
      </div>
    ''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('copy_link')") == {'ok': True, 'nativeCopied': True}
    assert page.evaluate('window.tiktokCopied') is True


@pytest.mark.parametrize("style", ["display:none", "opacity:0", "width:0;height:0"])
def test_embedded_controls_pause_and_resume_invisible_playing_video(page, style):
    page.set_content(f"""
      <video id="preload" style="position:absolute;top:900px"></video>
      <article><video id="active" style="{style}"></video></article>
    """)
    install_embedded_tiktok(page)
    assert page.evaluate("command('toggle')") == {"ok": True, "paused": True}
    assert page.evaluate("command('toggle')") == {"ok": True, "paused": False}
    assert page.eval_on_selector("#preload", "v => v.paused") is True
    page.eval_on_selector("#active", "v => v.remove()")
    assert page.evaluate("command('toggle')")['ok'] is False


@pytest.mark.parametrize("action, selector", [
    ("next", "feed-navigation-next"), ("previous", "feed-navigation-prev")
])
def test_embedded_navigation_with_invisible_playing_video(page, action, selector):
    page.set_content(f"""
      <article><video id="active" style="display:none"></video>
      <button data-e2e="{selector}" onclick="window.navigated=true; document.querySelector('video').setAttribute('src', 'next.mp4')">Navigate</button>
      </article>
    """)
    install_embedded_tiktok(page)
    page.evaluate("() => { document.querySelector('button').scrollIntoView = () => { throw new Error('Must not scroll navigation'); }; }")
    assert page.evaluate("action => command(action)", action)['ok'] is True
    assert page.evaluate("window.navigated") is True


@pytest.mark.parametrize("action, start, end", [("next", 0, 400), ("previous", 400, 0)])
def test_embedded_navigation_scrolls_feed_container(page, action, start, end):
    page.set_content('''
      <style>
        #feed {height:400px;overflow-y:scroll;scroll-snap-type:y mandatory}
        article {height:400px;scroll-snap-align:start}
        video {width:300px;height:350px}
      </style>
      <div id="feed"><article><video id="active"></video></article>
      <article><video></video></article></div>
    ''')
    install_embedded_tiktok(page)
    page.eval_on_selector("#feed", "(el, top) => el.scrollTop = top", start)
    assert page.evaluate("action => command(action)", action)['ok'] is True
    page.wait_for_function("top => Math.abs(document.querySelector('#feed').scrollTop - top) < 2", arg=end)
    assert page.evaluate("window.scrollY") == 0


def load_photo_feed(page, kinds, start):
    """A For You feed mixing videos and photo posts (which have no video element)."""
    items = ''.join(
        f'''<article data-e2e="recommend-list-item-container" id="item{index}">
          <a href="https://www.tiktok.com/@autor{index}/video/{100 + index}" data-e2e="video-author-uniqueid">autor{index}</a>
          <video id="{'active' if index == start else f'v{index}'}"></video></article>''' if kind == 'video' else
        f'''<article data-e2e="recommend-list-item-container" id="item{index}">
          <div class="css-1-7937d88b--DivPhotoPlayerContainer"><img class="css-2--ImgPhotoSlide" alt=""></div></article>'''
        for index, kind in enumerate(kinds))
    page.set_content('''<style>body {margin:0}
      #feed {height:600px;overflow-y:scroll;scroll-snap-type:y mandatory}
      article {height:590px;scroll-snap-align:start} video {width:300px;height:500px}
      </style><div id="feed">''' + items + '</div>')
    install_embedded_tiktok(page)
    page.eval_on_selector('#feed', '(feed, index) => { feed.scrollTop = index * 590; }', start)


def centered_item(page):
    return page.evaluate("""() => [...document.querySelectorAll('article')].find(item => {
      const rect = item.getBoundingClientRect();
      return rect.top <= 300 && rect.bottom > 300;
    }).id""")


@pytest.mark.parametrize('kinds, start, action, end', [
    (['video', 'photo', 'video'], 0, 'next', 2),
    (['video', 'photo', 'photo', 'video'], 0, 'next', 3),
    (['video', 'photo', 'video'], 2, 'previous', 0),
])
def test_tiktok_navigation_skips_photo_posts(page, kinds, start, action, end):
    load_photo_feed(page, kinds, start)
    result = page.evaluate('action => command(action)', action)
    assert result['ok'] is True, result
    assert result['author'] == f'@autor{end}'
    assert result['link'].endswith(f'/@autor{end}/video/{100 + end}')
    assert centered_item(page) == f'item{end}'


@pytest.mark.parametrize('action, end', [('next', 2), ('previous', 0)])
def test_tiktok_navigation_leaves_a_photo_post_already_on_screen(page, action, end):
    load_photo_feed(page, ['video', 'photo', 'video'], 1)
    result = page.evaluate('action => command(action)', action)
    assert result['ok'] is True, result
    assert result['author'] == f'@autor{end}'
    assert centered_item(page) == f'item{end}'


def test_tiktok_photo_post_is_not_described_as_the_next_video(page):
    # The next video already peeks into the screen below the photo post.
    load_photo_feed(page, ['video', 'photo', 'video'], 1)
    for action in ('refresh_info', 'copy_link', 'toggle'):
        result = page.evaluate('action => command(action)', action)
        assert result['ok'] is False
        assert 'publicação de fotos' in result['error']


def test_tiktok_navigation_explains_when_only_photo_posts_are_left(page):
    load_photo_feed(page, ['video', 'photo', 'photo'], 0)
    started = time.monotonic()
    result = page.evaluate("command('next')")
    assert result['ok'] is False
    assert 'publicações de fotos' in result['error']
    # The application gives up on a command after 20 seconds.
    assert time.monotonic() - started < 18


def test_tiktok_transparent_current_video_is_not_replaced_by_the_next_one(page):
    # TikTok may paint the current video on a canvas and make its element
    # transparent, while the preloaded next video already peeks into the screen.
    load_photo_feed(page, ['video', 'video'], 0)
    page.evaluate("document.querySelector('#active').style.opacity = '0'")
    info = page.evaluate("command('refresh_info')")
    assert info['link'].endswith('/@autor0/video/100')
    assert page.evaluate("command('toggle')") == {'ok': True, 'paused': True}
    assert page.evaluate("document.querySelector('#active').testPaused") is True
    assert page.evaluate("document.querySelector('#v1').testPaused") is True


def test_tiktok_next_is_not_confirmed_while_the_feed_stays_on_the_same_item(page):
    load_photo_feed(page, ['video', 'video'], 0)
    page.evaluate("""() => {
      // The current video turns transparent, but the feed never moves.
      document.querySelector('#feed').scrollBy = () => {};
      document.addEventListener('keydown', () => {
        document.querySelector('#active').style.opacity = '0';
      });
    }""")
    result = page.evaluate("command('next')")
    assert result['ok'] is False
    assert centered_item(page) == 'item0'


def test_tiktok_next_waits_for_a_late_video_instead_of_advancing_twice(page):
    load_photo_feed(page, ['video', 'video', 'video'], 0)
    page.evaluate("""() => {
      const late = document.querySelector('#v1');
      const item = document.querySelector('#item1');
      late.remove();
      document.addEventListener('keydown', () => {
        document.querySelector('#feed').scrollTop = 590;
        setTimeout(() => item.append(late), 2200);
      }, {once: true});
    }""")
    result = page.evaluate("command('next')")
    assert result['ok'] is True, result
    assert result['link'].endswith('/@autor1/video/101')
    assert centered_item(page) == 'item1'


@pytest.mark.parametrize("action, key", [("next", "ArrowDown"), ("previous", "ArrowUp")])
def test_embedded_navigation_uses_native_key_press_before_any_button(page, action, key):
    # No navigation button at all: only a real key press (which the mocked
    # transport turns into a genuine keydown/keyup) can advance this feed,
    # mirroring how TikTok's own player reacts to arrow keys regardless of
    # whatever nav-button markup it currently ships.
    page.set_content('''<video id="active"></video>''')
    install_embedded_tiktok(page)
    page.evaluate("""key => {
      document.addEventListener('keydown', event => {
        if (event.key === key) document.querySelector('video').setAttribute('src', 'next.mp4');
      });
    }""", key)
    result = page.evaluate("action => command(action)", action)
    assert result['ok'] is True
    assert page.evaluate("window.dispatchedKeys") == [key]


def test_embedded_navigation_does_not_report_replay_as_next_video(page):
    page.set_content('''<video id="active"></video>
      <button data-e2e="feed-navigation-next"
        onclick="document.querySelector('video').currentTime = 0">Next</button>''')
    install_embedded_tiktok(page)
    result = page.evaluate("command('next')")
    assert result['ok'] is False
    assert 'não mudou de vídeo' in result['error']


def test_embedded_controls_follow_new_playing_video_after_pause(page):
    page.set_content('''
      <video id="active" style="display:none"></video>
      <video id="next" style="display:none"></video>
    ''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('toggle')") == {"ok": True, "paused": True}
    page.eval_on_selector("#next", "v => v.play()")
    assert page.evaluate("command('toggle')") == {"ok": True, "paused": True}
    assert page.eval_on_selector("#next", "v => v.paused") is True
    assert page.eval_on_selector("#active", "v => v.paused") is True


def test_real_dom_chooses_visible_video_and_scoped_metadata(page):
    page.set_content(
        """
        <base href="https://www.tiktok.com/">
        <style>
          article { position: absolute; left: 0; width: 600px; height: 500px; }
          video { display: block; width: 600px; height: 400px; }
          a, [data-e2e="video-desc"] { display: block; height: 20px; }
          #preload { top: 900px; }
          #active { top: 0; }
        </style>
        <article id="preload">
          <a href="https://www.tiktok.com/@errado">@errado</a>
          <div data-e2e="video-desc">descrição errada</div>
          <a href="https://www.tiktok.com/@errado/video/111">vídeo errado</a>
          <video poster="preload.jpg"></video>
        </article>
        <article id="active">
          <a href="https://www.tiktok.com/@correto"> @correto </a>
          <div data-e2e="video-desc"> descrição correta </div>
          <a href="https://www.tiktok.com/@correto/video/222?utm_source=x">vídeo correto</a>
          <video poster="active.jpg"></video>
        </article>
        """
    )
    controller = TikTokVideoController(page)
    info = controller.get_info()
    assert info.author == "@correto"
    assert info.description == "descrição correta"
    assert controller.current_url() == "https://www.tiktok.com/@correto/video/222"


def test_active_video_without_description_does_not_read_another_feed_item(page):
    page.set_content(
        """
        <style>
          main { position:relative; width:600px; height:1200px; }
          .feed-item { position:absolute; left:0; width:600px; height:500px; }
          video { display:block; width:600px; height:400px; }
          [data-e2e="video-desc"] { display:block; height:20px; }
          #active { top:0; }
          #other { top:700px; }
        </style>
        <main>
          <div class="feed-item" id="active">
            <video poster="sem-descricao.jpg"></video>
          </div>
          <div class="feed-item" id="other">
            <div data-e2e="video-desc">descrição de outro vídeo</div>
            <video poster="outro.jpg"></video>
          </div>
        </main>
        """
    )
    info = TikTokVideoController(page).get_info()
    assert info.description == "Este vídeo não possui descrição"


def test_real_dom_reads_comments_opened_from_active_video(page):
    page.set_content(
        """
        <style>
          article, video { width:500px; height:350px; }
          [role="button"] { display:block; width:120px; height:30px; }
          .DivCommentListContainer { display:none; width:500px; height:200px; }
          [data-e2e="comment-level-1"] { display:block; width:400px; height:30px; }
        </style>
        <article>
          <video></video>
          <div role="button" aria-label="Ler ou adicionar comentários, 2 comentários"
            data-e2e="comment-icon" tabindex="0"
            onclick="document.querySelector('.DivCommentListContainer').style.display='block'">
            Comentários
          </div>
        </article>
        <section class="DivCommentListContainer">
          <span data-e2e="comment-level-1">Excelente vídeo</span>
          <span data-e2e="comment-level-1">Muito bom</span>
        </section>
        """
    )
    comments = TikTokVideoController(page).read_comments()
    assert comments == ("Excelente vídeo", "Muito bom")


def test_real_dom_like_and_favorite_target_active_video(page):
    page.set_content(
        """
        <style>
          article, video { width:500px; height:350px; }
          [role="button"] { display:block; width:120px; height:30px; }
        </style>
        <article>
          <video></video>
          <div role="button" data-e2e="like-icon" aria-label="Curtir vídeo"
            aria-pressed="false" tabindex="0"
            onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') !== 'true')">
            Curtir
          </div>
          <div role="button" data-e2e="favorite-icon" aria-label="Adicionar aos favoritos"
            aria-pressed="false" tabindex="0"
            onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') !== 'true')">
            Favoritar
          </div>
        </article>
        """
    )
    controller = TikTokVideoController(page)
    assert controller.toggle_like() is True
    assert controller.toggle_favorite() is True
    assert controller.toggle_like() is False
    assert controller.toggle_favorite() is False


def test_real_dom_like_clicks_interactive_parent_with_trusted_event(page):
    page.set_content(
        """
        <style>
          article, video { width:500px; height:350px; }
          button { display:block; width:120px; height:30px; }
          svg { width:20px; height:20px; }
        </style>
        <article>
          <video></video>
          <button aria-label="Curtir vídeo" aria-pressed="false"
            onclick="if (event.isTrusted) {
              this.setAttribute('aria-pressed', 'true');
              this.setAttribute('aria-label', 'Descurtir vídeo');
            }">
            <svg data-e2e="like-icon"><circle r="5"></circle></svg>
          </button>
        </article>
        """
    )

    assert TikTokVideoController(page).toggle_like() is True
    assert page.get_attribute("button", "aria-pressed") == "true"


def test_real_dom_like_does_not_report_success_without_state_change(page):
    page.set_content(
        """
        <style>
          article, video { width:500px; height:350px; }
          button { display:block; width:120px; height:30px; }
        </style>
        <article>
          <video></video>
          <button data-e2e="like-icon" aria-label="Curtir vídeo"
            aria-pressed="false">Curtir</button>
        </article>
        """
    )

    with pytest.raises(VideoControlError, match="não manteve a curtida"):
        TikTokVideoController(page).toggle_like()


def test_real_dom_like_detects_server_style_rollback(page):
    page.set_content(
        """
        <style>
          article, video { width:500px; height:350px; }
          button { display:block; width:120px; height:30px; }
        </style>
        <article>
          <video></video>
          <button data-e2e="like-icon" aria-label="Curtir vídeo"
            aria-pressed="false"
            onclick="this.setAttribute('aria-pressed', 'true');
              setTimeout(() => this.setAttribute('aria-pressed', 'false'), 200)">
            Curtir
          </button>
        </article>
        """
    )

    with pytest.raises(VideoControlError, match="não manteve a curtida"):
        TikTokVideoController(page).toggle_like()


def test_real_dom_posts_comment_through_visible_comment_editor(page):
    page.set_content(
        """
        <style>
          [role="dialog"], [contenteditable="true"] { width:500px; height:100px; }
          button { width:120px; height:30px; }
        </style>
        <section role="dialog">
          <div data-e2e="comment-input">
            <div contenteditable="true"></div>
            <button data-e2e="comment-post"
              onclick="document.body.dataset.published = this.previousElementSibling.textContent">
              Publicar
            </button>
          </div>
        </section>
        """
    )
    TikTokVideoController(page).post_comment("Comentário de teste")
    assert page.get_attribute("body", "data-published") == "Comentário de teste"


def test_real_dom_prefers_largest_intersection_area(page):
    page.set_content(
        """
        <base href="https://www.tiktok.com/">
        <style>
          article { position:absolute; top:0; }
          video { display:block; }
          a { display:block; height:20px; }
          #small video { width:200px; height:200px; }
          #large { left:250px; }
          #large video { width:400px; height:400px; }
        </style>
        <article id="small"><a href="/@menor">@menor</a><video></video></article>
        <article id="large"><a href="/@maior">@maior</a><video></video></article>
        """
    )
    assert TikTokVideoController(page).get_info().author == "@maior"


def test_real_dom_volume_and_mute_target_active_video(page):
    page.set_content(
        """
        <style>article, video { width:400px; height:300px; }</style>
        <article><video id="active"></video></article>
        """
    )
    controller = TikTokVideoController(page)
    assert controller.set_volume(0.3) == 0.3
    assert page.eval_on_selector("#active", "video => video.volume") == 0.3
    assert controller.toggle_mute() is True
    assert page.eval_on_selector("#active", "video => video.muted") is True


def test_real_dom_uses_nearby_accessible_author_when_profile_link_is_absent(page):
    page.set_content(
        """
        <style>
          article, video { width:400px; height:300px; }
          span { display:block; width:100px; height:20px; }
        </style>
        <article>
          <span data-e2e="video-author-uniqueid" aria-label="@autor-aria"></span>
          <video></video>
        </article>
        """
    )
    assert TikTokVideoController(page).get_info().author == "@autor-aria"


def test_real_dom_falls_back_to_video_nearest_viewport_center(page):
    page.set_content(
        """
        <base href="https://www.tiktok.com/">
        <style>
          article { position:absolute; width:300px; height:300px; }
          video { width:300px; height:250px; }
          a { display:block; height:20px; }
          #near { top:700px; }
          #far { top:2000px; }
        </style>
        <article id="near"><a href="/@perto">@perto</a><video></video></article>
        <article id="far"><a href="/@longe">@longe</a><video></video></article>
        """
    )
    assert TikTokVideoController(page).get_info().author == "@perto"


def test_real_dom_reports_rejected_play_promise(page):
    page.set_content(
        """
        <style>article, video { width:400px; height:300px; }</style>
        <article><video id="active"></video></article>
        """
    )
    page.eval_on_selector(
        "#active", "video => video.play = () => Promise.reject(new Error('blocked'))"
    )
    with pytest.raises(VideoControlError, match="interação inicial necessária"):
        TikTokVideoController(page).toggle_playback()


def test_real_dom_pending_play_promise_times_out_without_blocking_queue(page):
    page.set_content(
        """
        <style>article, video { width:400px; height:300px; }</style>
        <article><video id="active"></video></article>
        """
    )
    page.eval_on_selector("#active", "video => video.play = () => new Promise(() => {})")
    with pytest.raises(VideoControlError, match="fila foi liberada"):
        TikTokVideoController(page).toggle_playback()


def test_real_dom_zero_volume_is_treated_as_muted_and_activated(page):
    page.set_content(
        """
        <style>article, video { width:400px; height:300px; }</style>
        <article><video id="active"></video></article>
        """
    )
    page.eval_on_selector("#active", "video => video.volume = 0")
    controller = TikTokVideoController(page, 0.6)
    assert controller.toggle_mute() is False
    assert page.eval_on_selector("#active", "video => video.muted") is False
    assert page.eval_on_selector("#active", "video => video.volume") == 0.6


def test_real_dom_volume_preference_survives_new_video_and_site_reset(page):
    page.set_content(
        """
        <style>article, video { width:400px; height:300px; }</style>
        <main><article><video id="first"></video></article></main>
        """
    )
    controller = TikTokVideoController(page, 0.4)
    assert controller.set_volume(0.4) == 0.4
    page.eval_on_selector(
        "main",
        """main => {
            const article = document.createElement('article');
            const video = document.createElement('video');
            video.id = 'new-video';
            article.appendChild(video);
            main.appendChild(article);
        }""",
    )
    page.wait_for_function(
        "() => Math.abs(document.querySelector('#new-video').volume - 0.4) < 0.001"
    )
    page.eval_on_selector("#new-video", "video => video.volume = 1")
    page.wait_for_function(
        "() => Math.abs(document.querySelector('#new-video').volume - 0.4) < 0.001"
    )


def test_extension_audio_guard_blocks_volume_spike_before_playback(page):
    page.set_content("<main><video id='first'></video></main>")
    page.evaluate(
        """() => {
            window.nativeVolumeSet = Object.getOwnPropertyDescriptor(
                HTMLMediaElement.prototype, 'volume'
            ).set;
        }"""
    )
    guard = (
        Path(__file__).resolve().parents[1] / "ui" / "web_scripts" / "audio_guard.js"
    ).read_text(encoding="utf-8")
    page.add_script_tag(content=guard)
    page.evaluate(
        """() => document.dispatchEvent(new CustomEvent(
            'accessible-reels-volume-preference',
            {detail: JSON.stringify({volume: 0.3, muted: false})}
        ))"""
    )
    # Simula uma redefinição interna do TikTok que contorna o setter protegido.
    page.evaluate(
        """() => {
            const video = document.querySelector('#first');
            window.nativeVolumeSet.call(video, 1);
            video.play().catch(() => {});
        }"""
    )
    assert page.eval_on_selector("#first", "video => video.volume") == 0.3

    page.eval_on_selector(
        "main",
        "main => main.appendChild(Object.assign(document.createElement('video'), {id: 'new'}))",
    )
    page.wait_for_function(
        "() => Math.abs(document.querySelector('#new').volume - 0.3) < 0.001"
    )


def test_audio_guard_hides_minimize_visibility_event_only_from_active_platform(page):
    page.set_content("<video></video>")
    page.evaluate("globalThis.__accessibleNetworkActive = true")
    guard = (Path(__file__).resolve().parents[1] / "ui" / "web_scripts" / "audio_guard.js").read_text(encoding="utf-8")
    page.add_script_tag(content=guard)
    page.evaluate("document.addEventListener('visibilitychange', () => globalThis.visibilityCount = (globalThis.visibilityCount || 0) + 1)")
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    assert page.evaluate("globalThis.visibilityCount || 0") == 0
    assert page.evaluate("document.hidden") is False
    assert page.evaluate("document.visibilityState") == "visible"
    page.evaluate("globalThis.__accessibleNetworkActive = false")
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    assert page.evaluate("globalThis.visibilityCount") == 1


def test_real_dom_finds_video_link_in_outer_feed_item_even_when_link_has_no_area(page):
    page.set_content(
        """
        <base href="https://www.tiktok.com/">
        <style>
          section { width:500px; height:500px; }
          [data-e2e="browse-video"], video { width:500px; height:420px; }
          a { display:none; }
          [data-e2e="video-desc"] { display:block; width:200px; height:20px; }
        </style>
        <section data-e2e="recommend-list-item-container">
          <div data-e2e="browse-video"><video></video></div>
          <a href="/@autor-externo">@autor-externo</a>
          <div data-e2e="video-desc">descrição externa</div>
          <a href="/@autor-externo/video/987654?utm_source=feed"></a>
        </section>
        """
    )
    controller = TikTokVideoController(page)
    assert controller.current_url() == (
        "https://www.tiktok.com/@autor-externo/video/987654"
    )


NOT_INTERESTED_PAGE = """
<style>
  article, video { width:500px; height:350px; }
  [role="button"], button { display:block; width:120px; height:30px; }
  #menu { position:fixed; left:600px; top:50px; width:180px; background:white; }
</style>
<article>
  <video id="active"></video>
  %s
</article>
<script>
  window.pressed = null;
  function openMenu(items) {
    const menu = document.createElement('div');
    menu.id = 'menu';
    menu.setAttribute('role', 'menu');
    for (const text of items) {
      const item = document.createElement('div');
      item.setAttribute('role', 'menuitem');
      item.style.cssText = 'height:30px';
      item.textContent = text;
      item.onclick = () => { window.pressed = text; menu.remove(); };
      menu.append(item);
    }
    document.body.append(menu);
  }
</script>
"""


def test_tiktok_not_interested_uses_the_more_button(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" data-e2e="more-menu-icon" aria-label="Mais opções"
        onclick="openMenu(['Copiar link', 'Não tenho interesse', 'Denunciar'])">Mais</div>""")
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "Não tenho interesse"


def test_tiktok_not_interested_falls_back_to_the_context_menu(page):
    page.set_content(NOT_INTERESTED_PAGE % "")
    page.evaluate("""document.querySelector('video').addEventListener('contextmenu',
      () => openMenu(['Not interested', 'Report']))""")
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "Not interested"


def test_tiktok_not_interested_reports_a_menu_without_the_option(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" data-e2e="more-menu-icon" aria-label="Mais opções"
        onclick="openMenu(['Copiar link', 'Denunciar'])">Mais</div>""")
    install_embedded_tiktok(page)
    result = page.evaluate("command('not_interested')")
    assert result["ok"] is False and "Não tenho interesse" in result["error"]
    assert page.evaluate("window.pressed") is None


def test_tiktok_not_interested_reveals_the_hover_only_more_button(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" id="more" data-e2e="more-menu-icon" style="display:none"
        onclick="openMenu(['Velocidade', 'Não tenho interesse'])">Mais</div>""")
    page.evaluate("""document.querySelector('article').addEventListener('mouseover',
      () => { document.querySelector('#more').style.display = 'block'; })""")
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "Não tenho interesse"


def test_tiktok_not_interested_clicks_a_more_button_that_never_becomes_visible(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" data-e2e="more-menu-icon" style="display:none"
        onclick="openMenu(['Velocidade', 'Não tenho interesse'])">Mais</div>""")
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "Não tenho interesse"


def test_tiktok_not_interested_finds_plain_text_items_in_the_menu(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" data-e2e="more-menu-icon" aria-label="Mais opções"
        onclick="const m=document.createElement('div');m.setAttribute('role','menu');m.id='menu';
          m.innerHTML='<div><span>Velocidade</span></div><div id=ni><span>Não tenho interesse</span></div>';
          m.querySelector('#ni').onclick=()=>{window.pressed='ni';m.remove()};document.body.append(m)">Mais</div>""")
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True, "advance": True}
    assert page.evaluate("window.pressed") == "ni"


def test_tiktok_failure_report_lists_menus_and_account_controls(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div data-e2e="top-login-button" style="width:50px;height:20px">Entrar</div>
      <div role="button" data-e2e="more-menu-icon" aria-label="Mais opções"
        onclick="openMenu(['Velocidade', 'Copiar link'])">Mais</div>""")
    install_embedded_tiktok(page)
    result = page.evaluate("command('not_interested')")
    assert result["ok"] is False
    details = result["details"]
    assert any("Copiar link" in popup for popup in details["popups"])
    assert "visible|top-login-button" in details["account"]


def test_tiktok_not_interested_does_not_skip_when_the_feed_already_moved_on(page):
    page.set_content(NOT_INTERESTED_PAGE % """
      <div role="button" data-e2e="more-menu-icon" aria-label="Mais opções"
        onclick="openMenu(['Não tenho interesse'])">Mais</div>""")
    page.evaluate('''() => {
      new MutationObserver(records => {
        for (const record of records) for (const node of record.addedNodes) {
          if (node.id === 'menu') {
            node.firstChild.addEventListener('click', () => {
              const next = document.createElement('video');
              next.id = 'next';
              document.querySelector('#active').replaceWith(next);
            });
          }
        }
      }).observe(document.body, {childList: true});
    }''')
    install_embedded_tiktok(page)
    assert page.evaluate("command('not_interested')") == {"ok": True}


def test_transport_sends_trusted_text_only_during_an_app_command(page):
    page.set_content('<main></main>')
    page.evaluate("() => { window.posted = []; window.reelsHost = {postMessage: m => window.posted.push(JSON.parse(m))}; }")
    page.add_script_tag(content=(Path(__file__).resolve().parents[1] / "ui/web_scripts/transport.js").read_text(encoding="utf-8"))
    result = page.evaluate('''async () => {
      const runtime = __accessibleTransport.runtime;
      const outside = await runtime.sendMessage({type: 'accessible-reels-trusted-text', text: 'fora'});
      runtime.onMessage.addListener((message, _sender, respond) => {
        runtime.sendMessage({type: 'accessible-reels-trusted-text', text: message.argument.text}).then(respond);
        setTimeout(() => __accessibleClickDone(1, {ok: true}), 10);
      });
      const inside = await __accessibleRun('post_comment', {text: 'Olá'}, 'token-1', 'tiktok');
      return {outside, inside, posted: window.posted};
    }''')
    assert result['outside']['ok'] is False
    assert result['inside'] == {'ok': True}
    assert result['posted'] == [{'type': 'text', 'token': 'token-1', 'id': 1, 'text': 'Olá'}]


def test_transport_trusted_click_message_is_unchanged(page):
    page.set_content('<main></main>')
    page.evaluate("() => { window.posted = []; window.reelsHost = {postMessage: m => window.posted.push(JSON.parse(m))}; }")
    page.add_script_tag(content=(Path(__file__).resolve().parents[1] / "ui/web_scripts/transport.js").read_text(encoding="utf-8"))
    result = page.evaluate('''async () => {
      const runtime = __accessibleTransport.runtime;
      runtime.onMessage.addListener((_message, _sender, respond) => {
        runtime.sendMessage({type: 'accessible-reels-trusted-click', x: 10, y: 20, follow_diagnostic: {target: 'x'}}).then(respond);
        setTimeout(() => __accessibleClickDone(1, {ok: true}), 10);
      });
      const done = await __accessibleRun('toggle_like', null, 'token-2', 'tiktok');
      const unknown = await runtime.sendMessage({type: 'outro-tipo'});
      return {done, unknown, posted: window.posted};
    }''')
    assert result['done'] == {'ok': True}
    assert result['unknown']['ok'] is False
    assert result['posted'] == [{'type': 'click', 'token': 'token-2', 'id': 1, 'x': 10, 'y': 20,
                                 'follow_diagnostic': {'target': 'x'}}]


TIKTOK_REPLY_PAGE = TIKTOK_COMMENT_PAGE.replace(
    '<div data-e2e="comment-level-1">ana: Primeiro comentário</div>',
    '''<div data-e2e="comment-level-1" id="ana">ana: Primeiro comentário
      <button onclick="
        const box = document.createElement('div');
        box.className = 'reply';
        box.innerHTML = '<div contenteditable=true role=textbox style=white-space:pre-wrap></div>' +
          '<button data-e2e=comment-post aria-disabled=true>Publicar</button>';
        const editor = box.firstChild, post = box.lastChild;
        editor.textContent = window.replyMention || '';
        editor.oninput = () => post.setAttribute('aria-disabled', String(!editor.textContent.trim()));
        post.onclick = () => {
          const row = document.createElement('div');
          row.dataset.e2e = 'comment-level-2';
          row.textContent = 'eu: ' + editor.textContent;
          document.getElementById('ana').append(row);
          box.remove();
          window.replies = (window.replies || 0) + 1;
        };
        this.after(box);
        editor.focus();">Responder</button></div>''')


def tiktok_reply_target(page):
    comments = page.evaluate("command('comments')")['comments']
    return next(item for item in comments if 'Primeiro comentário' in item['text'])


def test_tiktok_reply_is_typed_in_the_reply_editor_and_confirmed(page):
    page.set_content(TIKTOK_REPLY_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result == {'ok': True}
    assert page.evaluate('window.typed') == ['Concordo']
    assert page.evaluate('window.replies') == 1
    assert page.locator('[data-e2e=comment-level-2]').inner_text() == 'eu: Concordo'
    # The main field was not used.
    assert page.evaluate('window.published') is None


def test_tiktok_reply_keeps_the_mention_tiktok_fills_in(page):
    page.set_content(TIKTOK_REPLY_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("window.replyMention = '@ana '")
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result == {'ok': True}
    assert page.locator('[data-e2e=comment-level-2]').inner_text() == 'eu: @ana Concordo'


def test_tiktok_reply_keeps_a_draft_in_the_reply_editor(page):
    page.set_content(TIKTOK_REPLY_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("window.replyMention = 'Rascunho meu'")
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result['ok'] is False
    assert 'rascunho' in result['error']
    assert page.evaluate('window.typed') == []


def test_tiktok_reply_reports_a_comment_that_disappeared(page):
    page.set_content(TIKTOK_REPLY_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    result = page.evaluate("command('post_comment', {text: 'Concordo', replyTo: 'nao-existe', replyText: 'zé: sumiu'})")
    assert result['ok'] is False
    assert 'não está mais disponível' in result['error']
    assert page.evaluate('window.typed') == []


def test_tiktok_reply_is_not_sent_when_the_mention_would_merge_with_the_text(page):
    # An editor that collapses the mention's trailing space would publish "@anaConcordo".
    page.set_content(TIKTOK_REPLY_PAGE.replace(" style=white-space:pre-wrap", ""))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("window.replyMention = '@ana '")
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result['ok'] is False
    assert 'não aceitou o texto' in result['error']
    assert page.evaluate('window.replies') is None


def test_tiktok_new_comment_ignores_a_reply_box_left_open(page):
    page.set_content(TIKTOK_REPLY_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("window.replyMention = '@ana '")
    page.evaluate("document.getElementById('panel').style.display = 'block'; document.querySelector('#ana button').click()")
    result = page.evaluate("command('post_comment', {text: 'Comentário normal'})")
    assert result == {'ok': True}
    assert page.locator('#list').inner_text() == 'eu: Comentário normal'
    assert page.evaluate('window.replies') is None


SEND_BUTTONS = {
    'texto': '<button class="send">Publicar</button>',
    'icone_data_e2e': ('<div role="button" class="send" data-e2e="comment-post">'
                       '<svg viewBox="0 0 10 10" width="20" height="20"><path d="M0 0L10 5L0 10z" fill="currentColor"/></svg></div>'),
    'icone_so_cor': ('<div role="button" class="send">'
                     '<svg viewBox="0 0 10 10" width="20" height="20"><path d="M0 0L10 5L0 10z" fill="currentColor"/></svg></div>'),
}


def draft_field(kind, send):
    """A comment field shaped like TikTok's Draft.js editor: the text box sits 7 levels below the send button's area."""
    return (f'<div class="DivCommentInputWrapper" data-kind="{kind}"><div class="DivInputAreaContainer">'
            '<div class="DivInputEditorContainer"><div class="DraftEditor-root"><div class="DraftEditor-editorContainer">'
            '<div class="public-DraftStyleDefault-block"><div>'
            '<div contenteditable="true" role="textbox" style="white-space:pre-wrap"></div>'
            '</div></div></div></div></div>'
            '<div role="button" data-e2e="comment-emoji" aria-label="Emoji">😀</div></div>'
            f'{send}</div>')


def tiktok_draft_page(send):
    return f'''
      <style>
        video {{ display:block; width:400px; height:200px; }}
        [role=button], button {{ display:block; min-width:40px; min-height:28px; }}
        #panel {{ display:none; }}
        [contenteditable] {{ display:block; width:300px; min-height:30px; }}
        [data-e2e=comment-level-1] {{ display:block; min-height:20px; }}
      </style>
      <article><video id="active"></video>
        <div role="button" data-e2e="comment-icon" aria-label="Comentários"
          onclick="document.getElementById('panel').style.display='block'">Comentários</div></article>
      <section id="panel">
        <div data-e2e="comment-level-1" id="ana">ana: Primeiro comentário
          <button id="reply-trigger" onclick="this.insertAdjacentHTML('afterend', window.replyField); wire(this.nextElementSibling);">Responder</button></div>
        <div id="list"></div>
        {draft_field('main', send)}
        <button aria-label="Fechar" onclick="document.getElementById('panel').style.display='none'">X</button>
      </section>
      <script>
        window.replyField = {draft_field('reply', send)!r};
        function wire(wrapper) {{
          const editor = wrapper.querySelector('[contenteditable]'), send = wrapper.querySelector('.send');
          if (!send) return;
          const update = () => {{
            const on = Boolean(editor.textContent.trim());
            send.setAttribute('aria-disabled', String(!on));
            send.style.color = on ? 'rgb(254, 44, 85)' : 'rgb(160, 160, 160)';
          }};
          editor.addEventListener('input', update);
          update();
          send.addEventListener('click', () => {{
            if (send.getAttribute('aria-disabled') === 'true') return;
            const reply = wrapper.dataset.kind === 'reply';
            const row = document.createElement('div');
            row.dataset.e2e = reply ? 'comment-level-2' : 'comment-level-1';
            row.textContent = 'eu: ' + editor.textContent;
            (reply ? document.getElementById('ana') : document.getElementById('list')).append(row);
            editor.textContent = '';
            update();
            if (reply) wrapper.remove();
            window.sent = (window.sent || []).concat(wrapper.dataset.kind);
          }});
        }}
        document.querySelectorAll('.DivCommentInputWrapper').forEach(wire);
      </script>'''


@pytest.mark.parametrize('send', sorted(SEND_BUTTONS))
def test_tiktok_reply_finds_the_send_button_of_a_deep_draft_editor(page, send):
    page.set_content(tiktok_draft_page(SEND_BUTTONS[send]))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result == {'ok': True}
    assert page.evaluate('window.sent') == ['reply']
    assert page.locator('[data-e2e=comment-level-2]').inner_text() == 'eu: Concordo'


@pytest.mark.parametrize('send', sorted(SEND_BUTTONS))
def test_tiktok_new_comment_finds_the_send_button_of_a_deep_draft_editor(page, send):
    page.set_content(tiktok_draft_page(SEND_BUTTONS[send]))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result == {'ok': True}
    assert page.evaluate('window.sent') == ['main']
    assert page.locator('#list').inner_text() == 'eu: Comentário novo'


@pytest.mark.parametrize('send', sorted(SEND_BUTTONS))
def test_tiktok_new_comment_uses_its_own_button_while_a_reply_box_is_open(page, send):
    page.set_content(tiktok_draft_page(SEND_BUTTONS[send]))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("document.getElementById('panel').style.display = 'block'; document.getElementById('reply-trigger').click()")
    result = page.evaluate("command('post_comment', {text: 'Comentário novo'})")
    assert result == {'ok': True}
    assert page.evaluate('window.sent') == ['main']


def test_tiktok_reply_never_uses_the_emoji_button_or_another_fields_button(page):
    # The reply box has only an emoji button; the main field's button must not send the reply.
    page.set_content(tiktok_draft_page(SEND_BUTTONS['icone_so_cor']))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("f => { window.replyField = f; }", draft_field('reply', ''))
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result['ok'] is False
    assert 'Não foi possível localizar Publicar comentário' in result['error']
    assert page.evaluate('window.sent') is None
    # The log gets the controls around the field, to fix the selector with the real page.
    area = result['details']['post_area']
    assert any('comment-emoji' in line for line in area)
    assert all('Concordo' not in line for line in area)


def test_tiktok_reply_is_cancelled_when_the_reply_box_does_not_open(page):
    page.set_content(tiktok_draft_page(SEND_BUTTONS['texto']))
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    page.evaluate("document.getElementById('reply-trigger').onclick = null")
    target = tiktok_reply_target(page)
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result['ok'] is False
    assert 'caixa de resposta do TikTok não abriu' in result['error']
    assert page.evaluate('window.typed') == []
    assert page.evaluate('window.sent') is None


def tiktok_comment_item(author, text, reply_thread=''):
    """A comment shaped like TikTok's: the text paragraph is comment-level-1 inside the item with Responder."""
    return f'''
      <div class="css-1i7ohvi-DivCommentItemContainer eo72wou0" data-author="{author}">
        <div class="css-x-DivCommentContentContainer"><div class="css-x-DivContentContainer">
          <a href="/@{author}"><span data-e2e="comment-username-1">{author}</span></a>
          <p data-e2e="comment-level-1"><span>{text}</span></p>
          <p class="css-x-PCommentSubContent"><span data-e2e="comment-time-1">2d</span>
            <span data-e2e="comment-reply-1" role="button" onclick="openReply(this)">Responder</span></p>
        </div></div>
        <div class="css-x-DivReplyContainer">{reply_thread}</div>
      </div>'''


TIKTOK_REAL_COMMENTS_PAGE = '''
  <style>
    video { display:block; width:400px; height:200px; }
    [role=button], button { display:inline-block; min-width:40px; min-height:24px; }
    #panel { display:none; }
    [contenteditable] { display:block; width:300px; min-height:30px; }
  </style>
  <article><video id="active"></video>
    <div role="button" data-e2e="comment-icon" aria-label="Comentários"
      onclick="document.getElementById('panel').style.display='block'">Comentários</div></article>
  <section id="panel">
    <div id="comments">''' + tiktok_comment_item('ana', 'Primeiro comentário', '''
      <div class="css-y-DivCommentItemContainer"><span data-e2e="comment-username-2">carla</span>
        <p data-e2e="comment-level-2"><span>Resposta antiga</span></p></div>''') + tiktok_comment_item('bia', 'Segundo comentário') + '''
    </div>
    <button aria-label="Fechar" onclick="document.getElementById('panel').style.display='none'">X</button>
  </section>
  <script>
    function openReply(control) {
      const item = control.closest('[class*=DivCommentItemContainer]');
      const box = document.createElement('div');
      box.innerHTML = '<div contenteditable="true" role="textbox" style="white-space:pre-wrap"></div><button>Publicar</button>';
      const editor = box.firstChild, send = box.lastChild;
      send.onclick = () => {
        const row = document.createElement('div');
        row.innerHTML = '<p data-e2e="comment-level-2"></p>';
        row.firstChild.textContent = editor.textContent;
        item.querySelector('[class*=DivReplyContainer]').append(row);
        box.remove();
        window.sentTo = (window.sentTo || []).concat(item.dataset.author);
      };
      item.querySelector('[class*=DivContentContainer]').append(box);
      editor.focus();
    }
  </script>'''


def test_tiktok_lists_each_comment_once_with_its_author(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    comments = page.evaluate("command('comments')")['comments']
    assert [item['text'] for item in comments] == ['ana: Primeiro comentário', 'bia: Segundo comentário']
    assert len({item['id'] for item in comments}) == 2


@pytest.mark.parametrize('index, author', [(0, 'ana'), (1, 'bia')])
def test_tiktok_reply_uses_the_responder_of_the_chosen_comment(page, index, author):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    target = page.evaluate("command('comments')")['comments'][index]
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result == {'ok': True}
    assert page.evaluate('window.sentTo') == [author]


def test_tiktok_reply_reports_the_shape_of_a_comment_without_responder(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    install_trusted_typing(page)
    target = page.evaluate("command('comments')")['comments'][0]
    page.evaluate("document.querySelectorAll('[data-e2e=comment-reply-1]').forEach(e => e.remove())")
    result = page.evaluate("t => command('post_comment', {text: 'Concordo', replyTo: t.id, replyText: t.text})", target)
    assert result['ok'] is False
    assert result['error'] == 'Não foi possível localizar Responder neste comentário.'
    shape = result['details']['comment_item']
    assert any('DivCommentItemContainer' in line for line in shape)
    assert any('comment-level-1' in line for line in shape)
    # Neither the comment's text nor its author goes to the log.
    assert not any('Primeiro' in line or 'ana' in line.split('|') for line in shape)
    assert page.evaluate('window.typed') == []


def cover_tiktok_page(page, attributes, text):
    """A TikTok dialog over the whole page, as the login and the interests ones."""
    page.evaluate("""([attributes, text]) => {
      const cover = document.createElement('div');
      cover.id = 'cover';
      cover.style.cssText = 'position:fixed;inset:0;background:white;z-index:99';
      cover.innerHTML = `<div role="dialog" ${attributes} style="width:400px;height:300px">
        <h2>${text}</h2><button aria-label="Fechar">X</button></div>`;
      cover.onclick = () => { window.coverClicks = (window.coverClicks || 0) + 1; };
      document.body.append(cover);
    }""", [attributes, text])


@pytest.mark.parametrize('attributes, text, expected', [
    ('data-e2e="login-modal" id="loginModalContentContainer"', 'Entrar no TikTok', 'pediu login'),
    ('', 'O que você gostaria de assistir no TikTok?', 'O que você gostaria de assistir no TikTok?'),
])
def test_tiktok_comments_report_a_dialog_covering_the_page(page, attributes, text, expected):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    cover_tiktok_page(page, attributes, text)
    for action, argument in (('comments', None), ('post_comment', {'text': 'Não enviar'})):
        result = page.evaluate("([action, argument]) => command(action, argument)", [action, argument])
        assert result['ok'] is False
        assert expected in result['error'] and 'F6' in result['error']
    # Nothing in the dialog was pressed by mistake, not even its close button.
    assert page.evaluate('window.coverClicks || 0') == 0


def test_tiktok_comments_report_a_login_dialog_opened_by_the_click(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    page.evaluate("""() => {
      document.querySelector('[data-e2e=comment-icon]').onclick = () => {
        const dialog = document.createElement('div');
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('data-e2e', 'login-modal');
        dialog.style.cssText = 'position:fixed;inset:0;background:white';
        dialog.textContent = 'Entrar no TikTok';
        document.body.append(dialog);
      };
    }""")
    result = page.evaluate("command('comments')")
    assert result['ok'] is False
    assert 'pediu login' in result['error']


def test_tiktok_dialog_outside_the_screen_does_not_hide_the_comments(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
      '<div role="dialog" data-e2e="login-modal" style="position:fixed;top:2000px;width:300px;height:60px">Entrar no TikTok</div>')""")
    assert len(page.evaluate("command('comments')")['comments']) == 2


def test_tiktok_comments_only_expand_replies_and_stay_within_the_click_limit(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    page.evaluate('''() => {
      window.pressed = [];
      const add = (parent, name, text, aria) => {
        const button = document.createElement('button');
        if (aria) button.setAttribute('aria-label', aria);
        button.textContent = text;
        button.onclick = () => window.pressed.push(name);
        parent.append(button);
      };
      // Unrelated controls of the page, and the options menu of each comment.
      add(document.body, 'sidebar', 'Ver mais', 'Ver mais');
      add(document.querySelector('article'), 'video options', '...', 'Mais opções');
      for (const item of document.querySelectorAll('#comments > div')) {
        add(item, 'comment options', '...', 'Mais opções');
        add(item, 'replies', 'Ver mais 3 respostas');
      }
      const send = window.__accessibleTransport.runtime.sendMessage;
      window.clicks = 0;
      // The application accepts at most four clicks per command.
      window.__accessibleTransport.runtime.sendMessage = message => {
        if (message.type === 'accessible-reels-trusted-click' && ++window.clicks > 4) {
          return new Promise(resolve => setTimeout(() => resolve({ok: false}), 5000));
        }
        return send(message);
      };
    }''')
    started = time.monotonic()
    result = page.evaluate("command('comments')")
    assert time.monotonic() - started < 10
    assert len(result['comments']) == 2
    assert page.evaluate('window.pressed') == ['replies', 'replies']
    assert page.evaluate('window.clicks') <= 4
    assert not page.locator('#panel').is_visible()


def test_tiktok_comment_ids_never_repeat_after_the_list_is_rebuilt(page):
    page.set_content(TIKTOK_REAL_COMMENTS_PAGE)
    install_embedded_tiktok(page)
    first = page.evaluate("command('comments')")['comments']
    # TikTok renders the comments again with new elements.
    page.evaluate("document.getElementById('comments').innerHTML = document.getElementById('comments').innerHTML"
                  ".replace(/ data-accessible-reels-comment-id=\"[^\"]*\"/g, '')")
    second = page.evaluate("command('comments')")['comments']
    assert not {item['id'] for item in first} & {item['id'] for item in second}


# =============================================================================
# TESTES DE LIVES NO TIKTOK E LEITURA DE CHAT COM NVDA
# =============================================================================

LIVE_CHAT_PAGE = """
<article>
  <div data-e2e="video-author-uniqueid">streamer_top</div>
  <div data-e2e="video-desc">Live jogando ao vivo</div>
  <video id="active" style="width:400px;height:400px"></video>
  <div data-e2e="live-chat-room">
    <div data-e2e="chat-message-list">
      <div data-e2e="chat-message"><span>Ana</span>: Olá streamer</div>
      <div data-e2e="chat-message"><span>Bruno</span>: Boa noite!</div>
    </div>
  </div>
</article>
"""


def test_canonical_live_link_and_copy_on_standard_live_path(page):
    load_tiktok_page(page, "/@streamer_top/live", LIVE_CHAT_PAGE)
    install_embedded_tiktok(page)

    info = page.evaluate("command('refresh_info')")
    assert info["author"] == "@streamer_top"
    assert info["link"] == "https://www.tiktok.com/@streamer_top/live"

    copy_res = page.evaluate("command('copy_link')")
    assert copy_res["ok"] is True
    assert copy_res["link"] == "https://www.tiktok.com/@streamer_top/live"


def test_canonical_live_link_on_subdomain(page):
    html = """
    <article>
      <div data-e2e="video-author-uniqueid">streamer_sub</div>
      <video id="active" style="width:400px;height:400px"></video>
    </article>
    """
    load_tiktok_page(page, "https://live.tiktok.com/@streamer_sub", html)
    install_embedded_tiktok(page)

    info = page.evaluate("command('refresh_info')")
    assert info["link"] == "https://www.tiktok.com/@streamer_sub/live"


def test_live_chat_reading_and_toggle(page):
    load_tiktok_page(page, "/@streamer_top/live", LIVE_CHAT_PAGE)
    install_embedded_tiktok(page)

    read_res = page.evaluate("command('read_live_chat')")
    assert read_res["ok"] is True
    assert read_res["count"] == 2
    assert "Ana: Olá streamer" in read_res["messages"]
    assert "Bruno: Boa noite!" in read_res["messages"]

    toggle_on = page.evaluate("command('toggle_live_chat')")
    assert toggle_on["ok"] is True
    assert toggle_on["active"] is True
    assert len(toggle_on["messages"]) >= 2

    toggle_off = page.evaluate("command('toggle_live_chat')")
    assert toggle_off["ok"] is True
    assert toggle_off["active"] is False


def test_live_chat_fails_gracefully_outside_live(page):
    html = """
    <article>
      <div data-e2e="video-author-uniqueid">canal_padrao</div>
      <video id="active" style="width:400px;height:400px"></video>
    </article>
    """
    load_tiktok_page(page, "/@canal_padrao/video/123456789", html)
    install_embedded_tiktok(page)

    res_read = page.evaluate("command('read_live_chat')")
    assert res_read["ok"] is False
    assert "Você não está em uma live." in res_read["error"]

    res_toggle = page.evaluate("command('toggle_live_chat')")
    assert res_toggle["ok"] is False
    assert "Você não está em uma live." in res_toggle["error"]
