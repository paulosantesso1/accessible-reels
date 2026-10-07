"""TikTok shows a saved video only through the color of the bookmark icon."""
from tests.test_video_dom import browser, install_embedded_tiktok, page  # noqa: F401

# Same accessible name in both states and no pressed attribute, like the real page.
FAVORITE_PAGE = """
<style>
  article, video { width:500px; height:350px; }
  [role="button"] { display:block; width:120px; height:40px; }
</style>
<article>
  <video id="active"></video>
  <div role="button" data-e2e="like-icon" aria-label="Curtir vídeo" aria-pressed="false" tabindex="0"
       onclick="this.setAttribute('aria-pressed', this.getAttribute('aria-pressed') !== 'true')">Curtir</div>
  <div role="button" data-e2e="favorite-icon" tabindex="0" id="favorite"
       aria-label="Adicionar aos favoritos. 123 adicionado aos Favoritos">
    <svg id="mark" viewBox="0 0 48 48" width="20" height="20" fill="currentColor" color="rgba(255, 255, 255, .9)">
      <path d="M13 4h22v38L24 33 13 42z"></path></svg>
  </div>
</article>
<script>
  const favorite = document.getElementById('favorite');
  const mark = document.getElementById('mark');
  window.clicks = 0;
  favorite.addEventListener('click', () => {
    window.clicks++;
    if (window.ignoreClicks) return;
    const saved = mark.getAttribute('color') === '#FACE15';
    mark.setAttribute('color', saved ? 'rgba(255, 255, 255, .9)' : '#FACE15');
  });
</script>
"""


def load(page):
    page.set_content(FAVORITE_PAGE)
    page.evaluate("""() => {
      const video = document.querySelector('video');
      video.testPaused = false;
    }""")
    install_embedded_tiktok(page)


def test_favorite_state_is_read_from_the_bookmark_color(page):
    load(page)
    first = page.evaluate("command('toggle_favorite')")
    assert first['ok'] is True and first['state'] is True
    second = page.evaluate("command('toggle_favorite')")
    assert second['ok'] is True and second['state'] is False
    assert page.evaluate("window.clicks") == 2


def test_an_already_saved_video_is_unsaved_by_the_first_toggle(page):
    load(page)
    page.evaluate("document.getElementById('mark').setAttribute('color', '#FACE15')")
    result = page.evaluate("command('toggle_favorite')")
    assert result['ok'] is True and result['state'] is False


def test_a_click_the_page_ignores_is_still_reported_as_unconfirmed(page):
    load(page)
    page.evaluate("window.ignoreClicks = true")
    result = page.evaluate("command('toggle_favorite')")
    assert result['ok'] is False
    assert 'não confirmou' in result['error']


def test_like_still_uses_its_pressed_attribute(page):
    load(page)
    assert page.evaluate("command('toggle_like')")['state'] is True
    assert page.evaluate("command('toggle_like')")['state'] is False
