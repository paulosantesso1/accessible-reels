"""Page-side listing of the logged-in account's liked YouTube Shorts."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

# A liked-videos playlist that loads 40 more cards each time the page is
# scrolled. Every 4th card is a one-minute Short, every 10th a one-minute
# regular clip (YouTube redirects /shorts/ID for those), the rest are long.
PLAYLIST = """<!doctype html><body style="margin:0">
<base href="https://www.youtube.com/playlist?list=LL">
<div id="list"></div>
<script>
  const list = document.getElementById('list');
  const total = 120;
  let shown = 0;
  const idFor = i => 'vid' + String(i).padStart(8, '0');
  window.kindOf = i => i % 10 === 5 ? 'clip' : (i % 4 === 0 ? 'short' : 'long');
  function more() {
    const upto = Math.min(total, shown + 40);
    for (; shown < upto; shown++) {
      const kind = window.kindOf(shown);
      const row = document.createElement('yt-lockup-view-model');
      row.style.display = 'block'; row.style.height = '120px';
      row.innerHTML = `<a href="/watch?v=${idFor(shown)}&list=LL&index=${shown}"><span>${kind === 'long' ? '12:34' : '0:58'}</span></a>
        <h3>Título ${shown}</h3><span>4 mil visualizações</span>`;
      list.append(row);
    }
  }
  more();
  window.addEventListener('scroll', () => {
    if (innerHeight + scrollY >= document.body.scrollHeight - 400 && shown < total) more();
  });
  window.fetchedShorts = [];
  window.fetch = async (url, options) => {
    const id = String(url).split('/').pop();
    window.fetchedShorts.push([id, options && options.method]);
    const index = Number(id.replace('vid', ''));
    if (window.kindOf(index) === 'short') return {type: 'basic', status: 200};
    return {type: 'opaqueredirect', status: 0};
  };
</script></body>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 900, "height": 700})
    page.route("https://www.youtube.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=PLAYLIST))
    page.goto("https://www.youtube.com/playlist?list=LL")
    page.evaluate('''() => {
      window.__accessibleTransport = {
        storage: {local: {get: async () => ({}), set: async () => {}}},
        runtime: {onMessage: {addListener: handler => window.ytListener = handler},
                  sendMessage: async () => ({ok: true})}
      };
      window.ytCommand = (action, argument) => new Promise(resolve =>
        window.ytListener({type: 'accessible-reels-command', platform: 'youtube', action, argument}, {}, resolve));
    }''')
    page.evaluate(Path("ui/web_scripts/youtube.js").read_text(encoding="utf-8"))
    yield page
    page.close()


def run_steps(page, kind="liked", limit=60):
    steps = []
    for _ in range(limit):
        step = page.evaluate("kind => window.ytCommand('library_step', kind)", kind)
        steps.append(step)
        if not step["ok"] or step["done"]:
            break
    return steps


def test_whole_playlist_is_scanned_and_only_real_shorts_are_listed(page):
    steps = run_steps(page)
    assert all(step["ok"] for step in steps)
    final = steps[-1]
    assert final["done"] is True and final["library"] == "liked"
    urls = [item["url"] for item in final["results"]]
    expected = [f"https://www.youtube.com/shorts/vid{i:08d}" for i in range(120) if i % 10 != 5 and i % 4 == 0]
    assert urls == expected
    assert final["scanned"] == 120


def test_regular_clips_and_long_videos_are_never_listed(page):
    final = run_steps(page)[-1]
    listed = {url.rsplit("/", 1)[1] for url in (item["url"] for item in final["results"])}
    assert not any(int(video[3:]) % 10 == 5 for video in listed)
    assert not any(int(video[3:]) % 4 != 0 for video in listed)


def test_only_candidates_up_to_three_minutes_are_checked_with_head_requests(page):
    run_steps(page)
    fetched = page.evaluate("window.fetchedShorts")
    assert fetched and all(method == "HEAD" for _id, method in fetched)
    checked = {int(video[3:]) for video, _method in fetched}
    assert all(i % 4 == 0 or i % 10 == 5 for i in checked)
    assert len(checked) == len(fetched)


def test_results_grow_in_steps_in_playlist_order_with_titles(page):
    steps = run_steps(page)
    sizes = [len(step["results"]) for step in steps]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1] and len(steps) > 2
    assert not any(step["done"] for step in steps[:-1])
    first = steps[-1]["results"][0]
    assert first["description"] == "Título 0" and first["author"] == ""


def test_missing_playlist_reports_a_login_hint(page):
    page.set_content("<p>Faça login</p>")
    page.evaluate("Date.now = (now => { const start = now(); return () => start + 21000 * (window.__tick = (window.__tick || 0) + 1); })(Date.now)")
    result = page.evaluate("window.ytCommand('library_step', 'liked')")
    assert result["ok"] is False
    assert "logado" in result["error"]


def test_only_liked_is_supported_on_youtube(page):
    result = page.evaluate("window.ytCommand('library_step', 'favorites')")
    assert result["ok"] is False
