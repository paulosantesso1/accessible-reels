"""Page-side listing of the logged-in account's liked and saved TikTok videos."""
from __future__ import annotations

from tests.test_video_dom import browser, install_embedded_tiktok, load_tiktok_page, page  # noqa: F401

PROFILE = """<!doctype html><body>
<nav><a data-e2e="nav-profile" href="/@ana">Perfil</a></nav>
<aside><button role="tab" data-e2e="likes">Curtidas</button>
  <a data-e2e="inbox-list-item" href="/@999/video/1"><img alt="atividade"></a></aside>
<div>
  <p role="tab" aria-selected="true" data-e2e="videos-tab">Vídeos</p>
  <p role="tab" aria-selected="false" id="fav">Favoritos</p>
  <p role="tab" aria-selected="false" data-e2e="liked-tab">Curtido</p>
</div>
<div id="grid"></div>
<script>
  const grid = document.getElementById('grid');
  function render(kind, count) {
    const item = kind === 'liked' ? 'user-liked-item' : 'favorites-item';
    grid.innerHTML = '';
    for (let i = 0; i < count; i++) {
      const div = document.createElement('div');
      div.setAttribute('data-e2e', item);
      div.innerHTML = `<a href="https://www.tiktok.com/@${kind}${i}/video/${kind === 'liked' ? 1 : 2}${String(i).padStart(5, '0')}">
        <img alt="${kind} video ${i}"></a>`;
      grid.append(div);
    }
  }
  const sets = {liked: 40, favorites: 3};
  // Cards beyond the first 16 only appear when the page is scrolled, like TikTok.
  let shown = {liked: 16, favorites: 3};
  function open(kind) { render(kind, shown[kind]); document.querySelectorAll('[role=tab]').forEach(t => t.setAttribute('aria-selected', 'false')); }
  document.querySelector('[data-e2e=liked-tab]').onclick = () => { open('liked'); window.currentKind = 'liked'; };
  document.getElementById('fav').onclick = () => { open('favorites'); window.currentKind = 'favorites'; };
  window.addEventListener('scroll', () => {
    const kind = window.currentKind;
    if (kind && shown[kind] < sets[kind]) { shown[kind] = Math.min(sets[kind], shown[kind] + 8); render(kind, shown[kind]); }
  });
  document.body.style.minHeight = '3000px';
</script></body>"""


def steps(page, kind, limit=40):
    """Poll library_step the way the background page does until it reports done."""
    load_tiktok_page(page, '/@ana', PROFILE)
    install_embedded_tiktok(page)
    results = []
    for _ in range(limit):
        step = page.evaluate('kind => command("library_step", kind)', kind)
        results.append(step)
        if not step['ok'] or step['done']:
            break
    return results


def test_own_profile_reads_the_navigation_link(page):
    load_tiktok_page(page, '/', PROFILE)
    install_embedded_tiktok(page)
    result = page.evaluate('command("own_profile")')
    assert result['ok'] is True
    assert result['profile_url'] == 'https://www.tiktok.com/@ana'


def test_own_profile_asks_for_login_when_the_link_has_no_handle(page):
    load_tiktok_page(page, '/', '<nav><a data-e2e="nav-profile" href="/@">Perfil</a></nav>')
    install_embedded_tiktok(page)
    page.evaluate("Date.now = (now => { const start = now(); return () => start + 11000 * (window.__tick = (window.__tick || 0) + 1); })(Date.now)")
    result = page.evaluate('command("own_profile")')
    assert result['ok'] is False
    assert 'Entre na sua conta' in result['error']


def test_liked_tab_is_listed_in_growing_steps_until_done(page):
    results = steps(page, 'liked')
    assert all(step['ok'] for step in results)
    sizes = [len(step['results']) for step in results]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
    assert results[-1]['done'] is True and not any(step['done'] for step in results[:-1])
    final = results[-1]
    urls = [item['url'] for item in final['results']]
    assert final['library'] == 'liked'
    assert len(urls) == 40 and len(set(urls)) == 40
    assert urls[0].startswith('https://www.tiktok.com/@liked0/video/')
    assert final['results'][0]['description'] == 'liked video 0'
    # The activity panel's "Curtidas" button and inbox cards are not the profile grid.
    assert not any('/@999/' in url for url in urls)


def test_first_step_already_returns_the_first_cards(page):
    first = steps(page, 'liked', limit=1)[0]
    assert first['ok'] is True and first['done'] is False
    assert len(first['results']) >= 16


def test_favorites_tab_is_found_by_its_label(page):
    final = steps(page, 'favorites')[-1]
    assert final['ok'] is True and final['done'] is True
    assert final['library'] == 'favorites'
    assert [item['author'] for item in final['results']] == ['@favorites0', '@favorites1', '@favorites2']


def test_switching_kind_starts_a_new_listing(page):
    load_tiktok_page(page, '/@ana', PROFILE)
    install_embedded_tiktok(page)
    page.evaluate('command("library_step", "liked")')
    other = page.evaluate('command("library_step", "favorites")')
    assert other['library'] == 'favorites'
    assert all(item['author'].startswith('@favorites') for item in other['results'])


def test_missing_tab_reports_a_login_hint(page):
    load_tiktok_page(page, '/@ana', '<p>sem abas</p>')
    install_embedded_tiktok(page)
    page.evaluate("Date.now = (now => { const start = now(); return () => start + 11000 * (window.__tick = (window.__tick || 0) + 1); })(Date.now)")
    result = page.evaluate('command("library_step", "liked")')
    assert result['ok'] is False
    assert 'Curtidos' in result['error']
