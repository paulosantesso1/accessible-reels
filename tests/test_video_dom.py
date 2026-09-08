from __future__ import annotations

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
          sendMessage: async ({x, y}) => {
            document.elementFromPoint(x, y).click();
            return {ok: true};
          }
        }
      };
      window.command = action => new Promise(resolve =>
        window.commandListener({type: 'accessible-reels-command', action}, {}, resolve));
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


def test_embedded_play_starts_paused_video_and_keeps_playing_video(page):
    page.set_content('<video id="active" style="width:300px;height:300px"></video>')
    install_embedded_tiktok(page)
    page.eval_on_selector('video', 'v => v.pause()')
    assert page.evaluate("command('play')") == {'ok': True, 'paused': False}
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
