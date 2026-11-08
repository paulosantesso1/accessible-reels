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


YOUTUBE_COMMENT_PANEL = '''
  <style>
    #yt-panel { position:fixed; right:0; top:0; width:330px; background:white; display:block; }
    #yt-panel[visibility="ENGAGEMENT_PANEL_VISIBILITY_HIDDEN"] { display:none; }
    #yt-panel div, #yt-panel button, ytd-comment-thread-renderer { display:block; min-height:24px; width:300px; }
    #comments-button { position:fixed; left:520px; top:600px; }
  </style>
  <ytd-button-renderer id="comments-button"><button
    onclick="document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED')">Comentários</button></ytd-button-renderer>
  <ytd-engagement-panel-section-list-renderer id="yt-panel" visibility="ENGAGEMENT_PANEL_VISIBILITY_HIDDEN">
    <div id="visibility-button"><button
      onclick="document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_HIDDEN')">Fechar</button></div>
    <div id="simplebox-placeholder"
      onclick="this.style.display = 'none'; document.getElementById('yt-editor').style.display = 'block'">Adicione um comentário...</div>
    <div id="yt-editor" style="display:none">
      <div id="contenteditable-root" contenteditable="true"
        oninput="document.querySelector('#submit-button button').disabled = !this.innerText.trim()"></div>
      <ytd-button-renderer id="submit-button"><button disabled onclick="
        const editor = document.getElementById('contenteditable-root');
        const thread = document.createElement('ytd-comment-thread-renderer');
        const text = document.createElement('span');
        text.id = 'content-text';
        text.textContent = editor.innerText;
        thread.append(text);
        document.getElementById('yt-threads').prepend(thread);
        editor.textContent = '';
        this.disabled = true;
        window.published = (window.published || 0) + 1;">Comentar</button></ytd-button-renderer>
    </div>
    <div id="yt-threads"></div>
  </ytd-engagement-panel-section-list-renderer>
'''


def install_youtube_comments(page, accept=True):
    page.evaluate('''([panel, accept]) => {
      document.body.insertAdjacentHTML('beforeend', panel);
      window.typed = [];
      window.clicked = [];
      window.__accessibleTransport.runtime.sendMessage = async message => {
        if (message.type === 'accessible-reels-trusted-text') {
          window.typed.push(message.text);
          if (accept) document.execCommand('insertText', false, message.text);
          return {ok: true};
        }
        const hit = document.elementFromPoint(message.x, message.y);
        window.clicked.push(hit.id || hit.textContent.trim());
        hit.focus();
        hit.click();
        return {ok: true};
      };
    }''', [YOUTUBE_COMMENT_PANEL, accept])


def post(page, text):
    return page.evaluate("text => window.ytCommand('post_comment', {text})", text)


def test_youtube_comment_is_typed_by_the_application_and_confirmed(page):
    install_youtube_comments(page)
    assert post(page, "Comentário novo") == {"ok": True}
    assert page.evaluate("window.typed") == ["Comentário novo"]
    assert page.evaluate("window.clicked") == ["Comentários", "simplebox-placeholder", "contenteditable-root", "Comentar"]
    assert page.locator("ytd-comment-thread-renderer #content-text").inner_text() == "Comentário novo"
    assert page.get_attribute("#yt-panel", "visibility") == "ENGAGEMENT_PANEL_VISIBILITY_HIDDEN"


def test_youtube_comment_is_not_published_when_the_editor_rejects_the_text(page):
    install_youtube_comments(page, accept=False)
    result = post(page, "Comentário novo")
    assert result["ok"] is False
    assert "não aceitou o texto" in result["error"]
    assert page.evaluate("window.published") is None


def test_youtube_comment_keeps_a_draft_left_on_the_page(page):
    install_youtube_comments(page)
    page.evaluate("document.getElementById('contenteditable-root').textContent = 'Rascunho'")
    result = post(page, "Comentário novo")
    assert result["ok"] is False
    assert "rascunho" in result["error"]
    assert page.evaluate("window.typed") == []


def test_youtube_comment_explains_an_account_without_a_channel(page):
    install_youtube_comments(page)
    page.evaluate("document.getElementById('simplebox-placeholder').remove()")
    result = post(page, "Comentário novo")
    assert result["ok"] is False
    assert "canal no YouTube" in result["error"]
    assert page.evaluate("window.typed") == []


def test_youtube_comment_does_not_close_a_panel_that_is_already_open(page):
    install_youtube_comments(page)
    page.evaluate("document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED')")
    assert post(page, "Comentário novo") == {"ok": True}
    assert "Comentários" not in page.evaluate("window.clicked")


def test_youtube_empty_comment_is_refused_without_touching_the_page(page):
    install_youtube_comments(page)
    result = post(page, "   ")
    assert result["ok"] is False
    assert page.evaluate("window.clicked") == []


def test_youtube_comment_reports_a_draft_in_an_editor_already_open(page):
    install_youtube_comments(page)
    page.evaluate('''() => {
      document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED');
      document.getElementById('simplebox-placeholder').style.display = 'none';
      document.getElementById('yt-editor').style.display = 'block';
      document.getElementById('contenteditable-root').textContent = 'Rascunho';
    }''')
    result = post(page, "Comentário novo")
    assert result["ok"] is False
    assert "rascunho" in result["error"]
    assert "Comentários" not in page.evaluate("window.clicked")
    assert page.locator("#contenteditable-root").inner_text() == "Rascunho"


def test_youtube_comment_uses_an_empty_editor_already_open(page):
    install_youtube_comments(page)
    page.evaluate('''() => {
      document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED');
      document.getElementById('simplebox-placeholder').style.display = 'none';
      document.getElementById('yt-editor').style.display = 'block';
    }''')
    assert post(page, "Comentário novo") == {"ok": True}
    assert page.evaluate("window.clicked") == ["contenteditable-root", "Comentar"]


def add_youtube_thread(page, mention=""):
    page.evaluate('''mention => {
      const thread = document.createElement('ytd-comment-thread-renderer');
      thread.id = 'thread-ana';
      thread.innerHTML = `<ytd-comment-renderer><a id="author-text">@ana</a><span id="content-text">Primeiro comentário</span>
        <ytd-button-renderer id="reply-button-end"><button aria-label="Responder">Responder</button></ytd-button-renderer>
        </ytd-comment-renderer><div id="replies"></div>`;
      thread.querySelector('#reply-button-end button').onclick = () => {
        const box = document.createElement('div');
        box.innerHTML = `<div id="contenteditable-root" contenteditable="true" style="white-space:pre-wrap"></div>
          <ytd-button-renderer id="submit-button"><button disabled>Responder</button></ytd-button-renderer>`;
        const editor = box.querySelector('[contenteditable]'), submit = box.querySelector('button');
        editor.textContent = mention;
        editor.oninput = () => { submit.disabled = !editor.innerText.trim(); };
        submit.onclick = () => {
          const reply = document.createElement('ytd-comment-renderer');
          reply.innerHTML = '<span id="content-text"></span>';
          reply.firstChild.textContent = editor.innerText;
          thread.querySelector('#replies').append(reply);
          box.remove();
          window.replies = (window.replies || 0) + 1;
        };
        thread.append(box);
      };
      document.getElementById('yt-threads').append(thread);
      document.getElementById('yt-panel').setAttribute('visibility', 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED');
    }''', mention)


def reply(page, text, reply_text="@ana: Primeiro comentário"):
    return page.evaluate("([text, replyText]) => window.ytCommand('post_comment', {text, replyTo: 'yt-comment-1', replyText})",
                         [text, reply_text])


def test_youtube_reply_is_typed_in_the_conversation_and_confirmed(page):
    install_youtube_comments(page)
    add_youtube_thread(page)
    assert reply(page, "Concordo") == {"ok": True}
    assert page.evaluate("window.typed") == ["Concordo"]
    assert page.locator("#replies #content-text").inner_text() == "Concordo"
    # The main comment box was not used and the panel was not toggled closed first.
    assert page.evaluate("window.published") is None
    assert page.evaluate("window.clicked")[0] == "Responder"


def test_youtube_reply_keeps_the_mention_youtube_fills_in(page):
    install_youtube_comments(page)
    add_youtube_thread(page, mention="@ana ")
    assert reply(page, "Concordo") == {"ok": True}
    assert page.locator("#replies #content-text").inner_text() == "@ana Concordo"


def test_youtube_reply_keeps_a_draft_in_the_reply_box(page):
    install_youtube_comments(page)
    add_youtube_thread(page, mention="Meu rascunho")
    result = reply(page, "Concordo")
    assert result["ok"] is False
    assert "rascunho" in result["error"]
    assert page.evaluate("window.typed") == []


def test_youtube_reply_reports_a_comment_that_disappeared(page):
    install_youtube_comments(page)
    add_youtube_thread(page)
    result = reply(page, "Concordo", reply_text="@zé: apagado")
    assert result["ok"] is False
    assert "não está mais disponível" in result["error"]
    assert page.evaluate("window.typed") == []


def test_youtube_new_comment_ignores_a_reply_box_left_open(page):
    install_youtube_comments(page)
    add_youtube_thread(page, mention="@ana ")
    page.evaluate("document.querySelector('#reply-button-end button').click()")
    assert post(page, "Comentário normal") == {"ok": True}
    assert page.locator("#yt-threads > ytd-comment-thread-renderer #content-text").first.inner_text() == "Comentário normal"
    assert page.locator("#replies > *").count() == 0
