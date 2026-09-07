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
def page(browser, request):
    page = browser.new_page(viewport={"width": 900, "height": 700})
    page.set_content('''
      <base href="https://www.instagram.com/">
      <style>article{width:600px;height:650px}video{display:block;width:500px;height:350px}
      button, [role=button]{min-width:40px;min-height:25px}svg{width:20px;height:20px}</style>
      <main>
        <article id="active">
          <div role="group"><video id="v1"></video><a href="https://www.instagram.com/ana/reels/">ana</a>
          <button id="caption">Descrição correta</button></div>
          <a href="https://www.instagram.com/reel/ABC_123/">Link</a>
          <div role="button" id="like" onclick="const s=this.querySelector('svg');s.setAttribute('aria-label',s.getAttribute('aria-label')==='Curtir'?'Descurtir':'Curtir')"><svg aria-label="Curtir"></svg></div>
          <div role="button"><div role="button" id="save" onclick="const s=this.querySelector('svg');s.setAttribute('aria-label',s.getAttribute('aria-label')==='Salvar'?'Remover':'Salvar')"><svg aria-label="Salvar"></svg></div></div>
          <button aria-label="Comentar" onclick="document.querySelector('[role=dialog]').style.display='block'"></button>
        </article>
        <article id="other"><video id="v2"></video><a href="https://www.instagram.com/errado/reels/">errado</a><button>Descrição errada</button></article>
      </main>
      <div style="position:fixed;left:760px;top:400px">
        <button aria-label="Navegar para o próximo reel" onclick="document.querySelector('#other').scrollIntoView()">Próximo</button>
        <button aria-label="Navegar para o reel anterior" onclick="document.querySelector('#active').scrollIntoView()">Anterior</button>
      </div>
      <div role="dialog" style="display:none;position:fixed;right:0;top:0;width:280px;background:white">
        Comentários
        <div><a href="/ana/">ana</a><time>1 h</time><span>Comentário de teste</span></div>
        <div><a href="/bia/">bia</a><time>2 h</time><span>Outro comentário</span></div>
        <input placeholder="Adicione um comentário...">
        <button onclick="const e=document.querySelector('input'); const row=document.createElement('div'); row.append(document.createElement('time'), document.createTextNode(e.value)); this.parentElement.append(row); e.value='';">Publicar</button>
        <button onclick="this.parentElement.style.display='none'">Fechar</button>
      </div>
    ''')
    page.evaluate('''() => {
      window.igStorage = {};
      window.igClicks = [];
      window.__accessibleTransport = {
        storage: {local: {
          get: async () => window.igStorage,
          set: async values => Object.assign(window.igStorage, values)
        }},
        runtime: {
          onMessage: {addListener: handler => window.igListener = handler},
          sendMessage: async message => {
            if (message.type === 'accessible-reels-trusted-click') {
              const target = document.elementFromPoint(message.x, message.y).closest('button,[role=button]');
              window.igClicks.push(target.id || target.textContent);
              target.click();
            }
            return {ok:true};
          }
        }
      };
      window.igCommand = (action, argument) => new Promise(resolve =>
        window.igListener({type:'accessible-reels-command',platform:'instagram',action,argument}, {}, resolve));
    }''')
    page.evaluate('''config => {
      window.igStorage = config.storage || {};
      const video = document.querySelector('#v1');
      video.volume = config.volume ?? 1;
      video.muted = config.muted ?? false;
    }''', getattr(request, "param", {}))
    page.evaluate(Path("ui/web_scripts/audio_guard.js").read_text(encoding="utf-8"))
    source = Path("ui/web_scripts/instagram.js").read_text(encoding="utf-8")
    page.evaluate(source)
    yield page
    page.close()


def command(page, action, argument=None):
    return page.evaluate("([action, argument]) => window.igCommand(action, argument)", [action, argument])


def test_instagram_play_starts_without_toggling_back_to_pause(page):
    page.evaluate('''() => {
      const v = document.querySelector('#v1');
      v.testPaused = true;
      Object.defineProperty(v, 'paused', {get: () => v.testPaused});
      v.play = async () => { v.testPaused = false; };
      v.pause = () => { v.testPaused = true; };
    }''')
    assert command(page, 'play') == {'ok': True, 'paused': False}
    assert command(page, 'play') == {'ok': True, 'paused': False}


def test_instagram_reads_only_active_reel_metadata(page):
    info = command(page, "refresh_info")
    assert info["ok"] is True
    assert info["author"] == "@ana"
    assert info["description"] == "Descrição correta"
    assert info["link"] == "https://www.instagram.com/reel/ABC_123/"


def test_instagram_like_and_save_verify_state_and_target_inner_button(page):
    assert command(page, "toggle_like") == {"ok": True, "state": True}
    assert command(page, "toggle_like") == {"ok": True, "state": False}
    assert command(page, "toggle_favorite") == {"ok": True, "state": True}
    assert page.evaluate("window.igClicks") == ["like", "like", "save"]


def test_instagram_audio_preferences_are_separate_from_tiktok(page):
    result = command(page, "volume_down")
    assert result["volume"] == pytest.approx(0.95)
    stored = page.evaluate("window.igStorage")
    assert stored == {"accessibleReelsInstagramVolume": pytest.approx(0.95), "accessibleReelsInstagramMuted": False}
    assert command(page, "toggle_mute")["muted"] is True


@pytest.mark.parametrize("page", [
    {"muted": True, "volume": 1},
    {"muted": False, "volume": 0},
    {"storage": {"accessibleReelsInstagramVolume": 0.85, "accessibleReelsInstagramMuted": True}},
], indirect=True)
def test_instagram_first_increase_from_silence_is_five_percent(page):
    assert command(page, "volume_up") == {"ok": True, "volume": 0.05, "muted": False}
    assert page.evaluate("document.querySelector('#v1').volume") == pytest.approx(0.05)
    assert page.evaluate("document.querySelector('#v1').muted") is False
    assert command(page, "volume_up")["volume"] == 0.1


@pytest.mark.parametrize("page", [{"volume": 0}], indirect=True)
def test_instagram_volume_moves_by_five_with_exact_bounds(page):
    for step in range(1, 23):
        assert command(page, "volume_up")["volume"] == min(step * 5, 100) / 100
    for step in range(1, 23):
        assert command(page, "volume_down")["volume"] == max(100 - step * 5, 0) / 100


@pytest.mark.parametrize("page", [{"muted": True, "volume": 1}], indirect=True)
def test_instagram_decrease_from_silence_does_not_make_sound(page):
    assert command(page, "volume_down")["volume"] == 0


@pytest.mark.parametrize("page", [{"muted": True, "volume": 1}], indirect=True)
def test_instagram_five_percent_survives_reel_change_and_site_reset(page):
    command(page, "volume_up")
    assert command(page, "next")["ok"] is True
    page.evaluate('''() => {
      const video = document.querySelector('#v2');
      video.volume = 1;
      video.muted = true;
    }''')
    assert page.evaluate("document.querySelector('#v2').volume") == pytest.approx(0.05)
    assert page.evaluate("document.querySelector('#v2').muted") is False
    assert page.evaluate("window.igStorage.accessibleReelsInstagramVolume") == 0.05


def test_instagram_comments_and_explicit_post(page):
    result = command(page, "comments")
    assert result["ok"] is True
    assert len(result["comments"]) == 2
    assert "Comentário de teste" in result["comments"][0]
    assert command(page, "post_comment", "Comentário fictício")["ok"] is True
    assert "Publicar" in page.evaluate("window.igClicks")
    assert command(page, "close_comments")["ok"] is True
    assert not page.locator('[role="dialog"]').is_visible()


def test_instagram_does_not_overwrite_unsent_comment(page):
    command(page, "comments")
    page.locator("input").fill("Rascunho do usuário")
    result = command(page, "post_comment", "Outro texto")
    assert result["ok"] is False
    assert page.locator("input").input_value() == "Rascunho do usuário"
    assert "Publicar" not in page.evaluate("window.igClicks")


def test_instagram_post_rejects_different_reel(page):
    command(page, "comments")
    page.evaluate("document.querySelector('#active').style.display='none'")
    result = command(page, "post_comment", "Não enviar")
    assert result["ok"] is False
    assert "Publicar" not in page.evaluate("window.igClicks")


def test_instagram_plain_letters_do_not_intercept_comment_typing(page):
    command(page, "comments")
    page.locator("input").fill("")
    page.locator("input").press_sequentially("clf")
    assert page.locator("input").input_value() == "clf"
    assert "like" not in page.evaluate("window.igClicks")


def test_instagram_next_and_previous_change_active_reel(page):
    assert command(page, "next")["author"] == "@errado"
    assert command(page, "previous")["author"] == "@ana"


def test_instagram_navigates_by_scrolling_when_responsive_layout_hides_arrows(page):
    page.locator('[aria-label="Navegar para o próximo reel"]').evaluate("element => element.parentElement.remove()")
    assert command(page, "next")["author"] == "@errado"
    assert command(page, "previous")["author"] == "@ana"


def test_instagram_failed_social_state_is_reported_as_error(page):
    page.evaluate("document.querySelector('#like').onclick=null")
    result = command(page, "toggle_like")
    assert result["ok"] is False
    assert "não confirmou" in result["error"]
    assert page.evaluate("window.igClicks") == ["like"]


def test_instagram_serializes_rapid_social_shortcuts(page):
    results = page.evaluate("Promise.all([window.igCommand('toggle_like'),window.igCommand('toggle_like')])")
    assert [result["state"] for result in results] == [True, False]


def test_instagram_playback_toggle_uses_current_video(page):
    page.evaluate('''() => {
      const video=document.querySelector('#v1');
      let paused=true;
      Object.defineProperty(video,'paused',{get:()=>paused});
      video.play=async()=>{paused=false;};
      video.pause=()=>{paused=true;};
    }''')
    assert command(page, "toggle")["paused"] is False
    assert command(page, "toggle")["paused"] is True
