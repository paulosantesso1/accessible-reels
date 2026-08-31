from __future__ import annotations

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
