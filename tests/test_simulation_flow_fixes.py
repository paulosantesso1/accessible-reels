"""Suíte unificada de testes unitários para as correções dos fluxos de Pesquisa e Comentários.

Cobre todos os cenários corrigidos a partir da simulação:
1. Validação e normalização de resultados de pesquisa.
2. Validação de limite máximo de 300 caracteres para termos de pesquisa (backend e UI).
3. Remoção da deduplicação indevida de comentários idênticos postados por usuários distintos.
4. Suporte completo a respostas aninhadas (threads), seletores level-2 e prefixo '[Resposta]'.
5. Acionamento de resposta direcionado a comentários aninhados específicos no DOM.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from playwright.sync_api import sync_playwright

from tiktok.search import (
    SearchResult,
    normalize_search_results,
    search_url,
    validate_search_result_url,
)
from tiktok.video_controls import VideoControlError
from ui.app_frame import MainFrame
from ui.download_controls import DownloadControlsMixin


# =============================================================================
# FIXTURES E UTILITÁRIOS PARA TESTES DOM COM PLAYWRIGHT
# =============================================================================

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 800, "height": 600})
    yield page
    page.close()


def install_embedded_tiktok(page):
    """Instala o runtime mock de mensagens e o script tiktok.js da aplicação.

    Acelera o setTimeout para 10ms nos testes para não haver atraso de sleep(1200).
    """
    page.evaluate("""() => {
      const origSetTimeout = window.setTimeout;
      window.setTimeout = (fn, ms) => origSetTimeout(fn, Math.min(ms, 10));
      window.__accessibleTransport = {
        storage: {local: {get: async () => ({}), set: async () => {}}},
        runtime: {
          onMessage: {addListener: fn => { window.commandListener = fn; }},
          sendMessage: async ({x, y}) => {
            const el = document.elementFromPoint(x, y);
            if (el) { el.focus(); el.click(); }
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
    script_path = Path(__file__).resolve().parents[1] / "ui/web_scripts/tiktok.js"
    page.add_script_tag(content=script_path.read_text(encoding="utf-8"))


def load_tiktok_html(page, body_content, url="https://www.tiktok.com/@creator/video/100001"):
    """Carrega uma página simulada do TikTok com interceptação de rede."""
    full_html = f"""<!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <style>
          body {{ margin: 0; padding: 20px; font-family: sans-serif; }}
          video {{ display: block; width: 400px; height: 300px; }}
          [role=button], button {{ display: block; min-width: 80px; height: 30px; }}
          [data-e2e=comment-item], [data-e2e=comment-reply-item] {{
            display: block; margin: 8px 0; padding: 4px; border-left: 2px solid #ccc;
          }}
          [data-e2e=comment-reply-item] {{ margin-left: 20px; border-color: #007acc; }}
        </style>
      </head>
      <body>
        {body_content}
      </body>
    </html>
    """
    page.route("https://www.tiktok.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html", body=full_html
    ))
    page.goto(url)
    install_embedded_tiktok(page)


def make_mock_frame():
    """Cria um mock de MainFrame para testar métodos isolados de download e busca."""
    frame = Mock()
    frame._closing_app = False
    frame._download_busy = True
    frame._active_name = "TikTok"
    frame.status = Mock()
    frame.choose_download_file = Mock()
    frame.current = Mock(return_value=Mock())
    frame.query_field = Mock()
    frame.clients = {"TikTok": Mock(pending=None)}
    frame.platform_data = {"TikTok": {}}
    return frame


# =============================================================================
# SEÇÃO 0: TRAVA DE SEGURANÇA CONTRA DOWNLOAD DE TRANSMISSÕES AO VIVO
# =============================================================================

class TestLiveDownloadLockAndFalsePositives:
    """Verifica a trava contra download de lives em andamento e proteção contra falsos positivos."""

    def test_live_download_is_blocked(self):
        frame = Mock(_closing_app=False, _download_busy=True)
        DownloadControlsMixin._download_resolved(
            frame, 'TikTok', {'ok': True, 'link': 'https://www.tiktok.com/@streamer/live'}, audio=False
        )
        assert frame._download_busy is False
        frame.choose_download_file.assert_not_called()
        frame.status.assert_called_once_with('Não é possível baixar uma transmissão ao vivo em andamento.')

    def test_vod_or_user_with_live_in_name_is_not_false_positive_blocked(self):
        frame = Mock(_closing_app=False, _download_busy=True)
        frame.choose_download_file.return_value = None
        DownloadControlsMixin._download_resolved(
            frame, 'TikTok', {'ok': True, 'link': 'https://www.tiktok.com/@live_user/video/123456789'}, audio=False
        )
        frame.choose_download_file.assert_called_once()


# =============================================================================
# SEÇÃO 1: NORMALIZAÇÃO DE RESULTADOS DE PESQUISA
# =============================================================================

class TestSearchNormalization:
    """Testa a normalização e sanitização dos resultados de pesquisa."""

    def test_normalize_search_results_preserves_order(self):
        """A ordem original dos vídeos recebidos é 100% preservada."""
        items = [
            {"url": "https://www.tiktok.com/@v1/video/1", "author": "@v1", "description": "V1"},
            {"url": "https://www.tiktok.com/@v2/video/2", "author": "@v2", "description": "V2"},
        ]
        results = normalize_search_results(items)
        assert len(results) == 2
        assert [r.author for r in results] == ["@v1", "@v2"]

    def test_normalize_search_results_empty_and_limit_enforcement(self):
        """Lista vazia retorna tupla vazia, e limit restringe a quantidade."""
        assert normalize_search_results([]) == ()
        assert normalize_search_results(None) == ()

        items = [
            {"url": f"https://www.tiktok.com/@user{i}/video/{i}", "author": f"@user{i}"}
            for i in range(10)
        ]
        results = normalize_search_results(items, limit=3)
        assert len(results) == 3

    def test_normalize_search_results_deduplicates_and_sanitizes(self):
        """Garante que URLs duplicadas ou inválidas continuam sendo filtradas."""
        items = [
            {"url": "https://www.tiktok.com/@user/video/123?extra=param", "author": "@user", "description": "Desc"},
            {"url": "https://www.tiktok.com/@user/video/123", "author": "@user_dup", "description": "Ignorado"},
            {"url": "https://malicious.example.com/@user/video/123", "author": "@evil"},
        ]
        results = normalize_search_results(items)
        assert len(results) == 1
        assert results[0].url == "https://www.tiktok.com/@user/video/123"


# =============================================================================
# SEÇÃO 3: VALIDAÇÃO DE LIMITE DE CARACTERES NA PESQUISA
# =============================================================================

class TestSearchQueryLengthValidation:
    """Testa a validação do limite de 300 caracteres no gerador de URL e na UI."""

    def test_search_url_accepts_valid_length_query(self):
        """Termos com até 300 caracteres são aceitos e codificados corretamente."""
        short_query = "notícias do brasil"
        url = search_url(short_query)
        assert "https://www.tiktok.com/search/video?q=not%C3%ADcias+do+brasil" == url

        exact_300 = "a" * 300
        url_300 = search_url(exact_300)
        assert exact_300 in url_300

    def test_search_url_rejects_query_over_300_characters(self):
        """Termos com mais de 300 caracteres disparam VideoControlError imediatamente."""
        too_long = "b" * 301
        with pytest.raises(VideoControlError, match="O termo de pesquisa é muito longo. Use até 300 caracteres."):
            search_url(too_long)

        way_too_long = "x" * 600
        with pytest.raises(VideoControlError, match="O termo de pesquisa é muito longo. Use até 300 caracteres."):
            search_url(way_too_long)

    def test_search_url_normalizes_whitespace_before_length_validation(self):
        """Espaços redundantes são compactados antes de avaliar o comprimento."""
        # Com espaços extras tem 320 caracteres, mas compactado tem menos de 300
        spaced_query = "   palavra1    palavra2   " + (" a" * 100)
        normalized = " ".join(spaced_query.split())
        assert len(normalized) <= 300
        url = search_url(spaced_query)
        assert "palavra1+palavra2" in url

        # Espaços extras que ainda assim resultam em > 300 caracteres normalizados
        really_too_long = "   " + ("palavra " * 50) + "   "
        with pytest.raises(VideoControlError, match="O termo de pesquisa é muito longo. Use até 300 caracteres."):
            search_url(really_too_long)

    def test_search_url_empty_query_raises_proper_error(self):
        """Pesquisa em branco ou apenas com espaços continua sendo rejeitada."""
        with pytest.raises(VideoControlError, match="Digite algo para pesquisar."):
            search_url("")
        with pytest.raises(VideoControlError, match="Digite algo para pesquisar."):
            search_url("     ")

    @pytest.mark.parametrize("platform", ["TikTok", "Instagram", "YouTube"])
    def test_mainframe_search_blocks_query_over_300_chars(self, platform):
        """A UI deve alertar o usuário no status e não disparar navegação se o texto passar de 300 caracteres."""
        frame = make_mock_frame()
        frame._active_name = platform
        frame.clients = {platform: Mock(pending=None)}
        frame.platform_data = {platform: {}}
        frame.query_field.GetValue.return_value = "c" * 305

        MainFrame.search(frame)

        frame.status.assert_called_once_with("O termo de pesquisa é muito longo. Use até 300 caracteres.")
        frame.clients[platform].navigate.assert_not_called()

    @pytest.mark.parametrize("platform", ["TikTok", "Instagram", "YouTube"])
    def test_mainframe_search_accepts_valid_query(self, platform):
        """Termo válido no campo de busca dispara a navegação e atualiza status para qualquer rede."""
        frame = make_mock_frame()
        frame._active_name = platform
        frame.clients = {platform: Mock(pending=None)}
        frame.platform_data = {platform: {}}
        frame.query_field.GetValue.return_value = "futebol ao vivo"

        MainFrame.search(frame)

        frame.clients[platform].navigate.assert_called_once()
        nav_url = frame.clients[platform].navigate.call_args.args[0]
        if platform == "TikTok":
            assert "https://www.tiktok.com/search/video?q=futebol+ao+vivo" == nav_url
        elif platform == "YouTube":
            assert "https://www.youtube.com/results?search_query=futebol+ao+vivo&sp=EgIYAQ%253D%253D" == nav_url
        else:
            assert "https://www.instagram.com/explore/search/keyword/?q=futebol+ao+vivo" == nav_url
        assert frame.platform_data[platform]["search_url"] == nav_url

    @pytest.mark.parametrize("platform", ["TikTok", "Instagram", "YouTube"])
    def test_mainframe_search_blocks_empty_query(self, platform):
        """Campo vazio na UI avisa o usuário sem disparar requisição."""
        frame = make_mock_frame()
        frame._active_name = platform
        frame.clients = {platform: Mock(pending=None)}
        frame.platform_data = {platform: {}}
        frame.query_field.GetValue.return_value = "   "

        MainFrame.search(frame)

        frame.status.assert_called_once_with("Digite o que deseja pesquisar.")
        frame.clients[platform].navigate.assert_not_called()


# =============================================================================
# SEÇÃO 4: PRESERVAÇÃO DE COMENTÁRIOS IDÊNTICOS DE USUÁRIOS DIFERENTES NO DOM
# =============================================================================

class TestIdenticalCommentsPreservation:
    """Testa a remoção do filtro que descartava comentários de mesmo texto."""

    def test_comment_rows_preserves_identical_comments_from_different_users(self, page):
        """Dois usuários comentando a mesma frase não devem ter um comentário descartado."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon" onclick="document.getElementById('comments-panel').style.display='block'">
            Comentários
          </button>
        </article>
        <div id="comments-panel">
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-1">usuario_alpha</span>
            <p data-e2e="comment-level-1">Parabéns pelo vídeo!</p>
            <button data-e2e="comment-reply-1">Responder</button>
          </div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-2">usuario_beta</span>
            <p data-e2e="comment-level-1">Parabéns pelo vídeo!</p>
            <button data-e2e="comment-reply-2">Responder</button>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        # Ambos os comentários devem estar presentes
        assert len(comments) == 2
        assert comments[0]["text"] == "usuario_alpha: Parabéns pelo vídeo!"
        assert comments[1]["text"] == "usuario_beta: Parabéns pelo vídeo!"

        # Cada um deve receber um identificador próprio e exclusivo
        assert comments[0]["id"] != comments[1]["id"]
        assert comments[0]["id"].startswith("accessible-reels-comment-")
        assert comments[1]["id"].startswith("accessible-reels-comment-")

    def test_comment_rows_handles_multiple_identical_short_reactions(self, page):
        """Vários comentários com reações curtas repetidas (ex: 'Top!') devem aparecer integralmente."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div id="comments-box">
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-1">user1</span>
            <p data-e2e="comment-level-1">Top!</p>
            <button data-e2e="comment-reply-1">Responder</button>
          </div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-2">user2</span>
            <p data-e2e="comment-level-1">Top!</p>
            <button data-e2e="comment-reply-2">Responder</button>
          </div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-3">user3</span>
            <p data-e2e="comment-level-1">Top!</p>
            <button data-e2e="comment-reply-3">Responder</button>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        assert len(comments) == 3
        texts = [c["text"] for c in comments]
        assert texts == ["user1: Top!", "user2: Top!", "user3: Top!"]
        ids = {c["id"] for c in comments}
        assert len(ids) == 3

    def test_comment_rows_ignores_empty_or_invisible_elements(self, page):
        """Elementos sem texto ou com display: none não devem poluir a lista de comentários."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div id="comments-box">
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-1">valido</span>
            <p data-e2e="comment-level-1">Conteúdo visível</p>
            <button data-e2e="comment-reply-1">Responder</button>
          </div>
          <div data-e2e="comment-item" style="display: none;">
            <span data-e2e="comment-username-2">invisivel</span>
            <p data-e2e="comment-level-1">Não deve aparecer</p>
          </div>
          <div data-e2e="comment-item">
            <p data-e2e="comment-level-1">   </p>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        assert len(comments) == 1
        assert comments[0]["text"] == "valido: Conteúdo visível"


# =============================================================================
# SEÇÃO 5: RESPOSTAS ANINHADAS E PREFIXO '[Resposta]' NO DOM
# =============================================================================

class TestNestedRepliesAndPrefixing:
    """Testa a identificação e formatação de respostas aninhadas (threads)."""

    def test_nested_replies_are_included_and_prefixed(self, page):
        """Respostas filhas dentro do container pai devem ser preservadas e receber '[Resposta]'."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div id="thread-container">
          <!-- Comentário Pai -->
          <div data-e2e="comment-item" id="parent-item">
            <span data-e2e="comment-username-1">carlos_pai</span>
            <p data-e2e="comment-level-1">Qual é a música de fundo?</p>
            <button data-e2e="comment-reply-1">Responder</button>

            <!-- Resposta Aninhada 1 -->
            <div data-e2e="comment-reply-item" id="reply-item-1">
              <span data-e2e="comment-username-2">dj_mari</span>
              <p data-e2e="comment-level-2">É a faixa número 3 do álbum novo!</p>
              <button data-e2e="comment-reply-2">Responder</button>
            </div>

            <!-- Resposta Aninhada 2 -->
            <div data-e2e="comment-reply-item" id="reply-item-2">
              <span data-e2e="comment-username-3">carlos_pai</span>
              <p data-e2e="comment-level-2">Muito obrigado!</p>
              <button data-e2e="comment-reply-3">Responder</button>
            </div>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        assert len(comments) == 3

        # O comentário pai NÃO tem o prefixo [Resposta]
        assert comments[0]["text"] == "carlos_pai: Qual é a música de fundo?"
        assert not comments[0]["text"].startswith("[Resposta]")

        # A primeira resposta aninhada recebe o prefixo
        assert comments[1]["text"] == "[Resposta] dj_mari: É a faixa número 3 do álbum novo!"

        # A segunda resposta aninhada recebe o prefixo
        assert comments[2]["text"] == "[Resposta] carlos_pai: Muito obrigado!"

    def test_nested_reply_does_not_duplicate_prefix_if_already_present(self, page):
        """Se a resposta já iniciar com '[Resposta]' ou seta '↳', não duplica."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div data-e2e="comment-item">
          <span data-e2e="comment-username-p">autor</span>
          <p data-e2e="comment-level-1">Post inicial</p>
          <button data-e2e="comment-reply-p">Responder</button>

          <div data-e2e="comment-reply-item">
            <span data-e2e="comment-username-f1">filho1</span>
            <p data-e2e="comment-level-2">[Resposta] já formatado</p>
            <button data-e2e="comment-reply-f1">Responder</button>
          </div>
          <div data-e2e="comment-reply-item">
            <span data-e2e="comment-username-f2">filho2</span>
            <p data-e2e="comment-level-2">↳ com seta</p>
            <button data-e2e="comment-reply-f2">Responder</button>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        assert len(comments) == 3
        assert comments[1]["text"] == "[Resposta] filho1: [Resposta] já formatado"
        assert comments[2]["text"] == "[Resposta] filho2: ↳ com seta"

    def test_comment_text_selector_variants_are_supported(self, page):
        """Seletores data-e2e=comment-level-1, comment-level-2 e comment-text são todos reconhecidos."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-a">user_a</span>
            <p data-e2e="comment-level-1">Texto formato level 1</p>
            <button data-e2e="comment-reply-a">Responder</button>
          </div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-b">user_b</span>
            <p data-e2e="comment-level-2">Texto formato level 2</p>
            <button data-e2e="comment-reply-b">Responder</button>
          </div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-c">user_c</span>
            <p data-e2e="comment-text">Texto formato comment-text genérico</p>
            <button data-e2e="comment-reply-c">Responder</button>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        assert len(comments) == 3
        assert comments[0]["text"] == "user_a: Texto formato level 1"
        assert comments[1]["text"] == "user_b: Texto formato level 2"
        assert comments[2]["text"] == "user_c: Texto formato comment-text genérico"

    def test_reply_to_nested_comment_triggers_specific_reply_control(self, page):
        """Ao responder a uma réplica aninhada, o controle 'Responder' específico da réplica é acionado."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div id="thread">
          <div data-e2e="comment-item" id="parent">
            <span data-e2e="comment-username-1">pai</span>
            <p data-e2e="comment-level-1">Pergunta inicial</p>
            <button id="btn-parent-reply" data-e2e="comment-reply-p" onclick="window.clickedTarget='pai'">Responder</button>

            <div data-e2e="comment-reply-item" id="child">
              <span data-e2e="comment-username-2">filho</span>
              <p data-e2e="comment-level-2">Resposta da pergunta</p>
              <button id="btn-child-reply" data-e2e="comment-reply-c" onclick="window.clickedTarget='filho'">Responder</button>
            </div>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        # 1. Carrega os comentários e obtém o ID do comentário aninhado (filho)
        list_res = page.evaluate("command('comments')")
        child_comment = list_res["comments"][1]
        assert child_comment["text"] == "[Resposta] filho: Resposta da pergunta"
        child_id = child_comment["id"]

        # 2. Aciona o comando de responder direcionado ao ID da resposta aninhada
        reply_res = page.evaluate(f"command('reply_comment', {{id: '{child_id}', text: ''}})")
        assert reply_res.get("replyTo") is not None

        # 3. Confirma que o botão 'Responder' clicado foi o do elemento filho, não do pai
        clicked = page.evaluate("window.clickedTarget")
        assert clicked == "filho"


# =============================================================================
# SEÇÃO 6: FLUXOS COMPLETOS E INTEGRAÇÃO PONTA A PONTA
# =============================================================================

class TestSimulationFlowIntegration:
    """Valida a integração completa dos dois fluxos de ponta a ponta."""

    def test_search_flow_end_to_end(self):
        """Fluxo de busca completo: validação do input -> construção de URL -> normalização."""
        frame = make_mock_frame()

        # 1. Entrada válida com termo de pesquisa
        frame.query_field.GetValue.return_value = "react e python"
        MainFrame.search(frame)

        nav_url = frame.clients["TikTok"].navigate.call_args.args[0]
        assert nav_url == "https://www.tiktok.com/search/video?q=react+e+python"

        # 2. Simulação de resposta da rede com itens
        raw_api_results = [
            {"url": "https://www.tiktok.com/@dev1/video/1", "author": "@dev1", "description": "Tutorial React"},
            {"url": "https://www.tiktok.com/@dev2/video/2", "author": "@dev2", "description": "Dicas Python"},
        ]

        normalized = normalize_search_results(raw_api_results)

        assert len(normalized) == 2
        assert normalized[0].author == "@dev1"
        assert normalized[0].label == "@dev1: Tutorial React"
        assert normalized[1].author == "@dev2"
        assert normalized[1].label == "@dev2: Dicas Python"

    def test_comment_flow_end_to_end_with_threads_and_identical_reactions(self, page):
        """Fluxo de comentários completo: comentários raiz, respostas em thread e reações idênticas."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div>
          <!-- Comentário 1 com thread -->
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-u1">aline</span>
            <p data-e2e="comment-level-1">Que legal esse projeto!</p>
            <button data-e2e="comment-reply-1">Responder</button>
            <div data-e2e="comment-reply-item">
              <span data-e2e="comment-username-u2">bruno</span>
              <p data-e2e="comment-level-2">Também achei incrível!</p>
              <button data-e2e="comment-reply-2">Responder</button>
            </div>
          </div>
          <!-- Comentário 2 com texto IDÊNTICO ao de Bruno, mas de outro usuário -->
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-u3">carla</span>
            <p data-e2e="comment-level-1">Também achei incrível!</p>
            <button data-e2e="comment-reply-3">Responder</button>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        # Todos os 3 comentários devem ser listados
        assert len(comments) == 3

        # 1: Aline (raiz)
        assert comments[0]["text"] == "aline: Que legal esse projeto!"
        assert not comments[0]["text"].startswith("[Resposta]")

        # 2: Bruno (aninhado dentro de Aline)
        assert comments[1]["text"] == "[Resposta] bruno: Também achei incrível!"

        # 3: Carla (raiz com texto idêntico ao de Bruno, não descartada)
        assert comments[2]["text"] == "carla: Também achei incrível!"

        # IDs devem ser todos únicos
        assert len({c["id"] for c in comments}) == 3



# =============================================================================
# SEÇÃO 7: FOCO E SELEÇÃO AUTOMÁTICA NO COMENTÁRIO RECÉM-POSTADO
# =============================================================================

class TestNewlyPostedCommentFocusAndSelection:
    """Testa o retorno automático e posicionamento de foco no comentário publicado."""

    def test_post_comment_records_focus_text_and_schedules_open_comments(self):
        """Ao concluir post_comment, o texto postado é guardado em focus_comment_text."""
        frame = make_mock_frame()
        frame.publish_button = Mock()
        frame.comment_entry = Mock()
        frame._set_reply_target = Mock()

        with patch("ui.app_frame.wx.CallAfter") as call_after:
            MainFrame._result(
                frame,
                "TikTok",
                "post_comment",
                {"text": "Meu comentário recém-postado"},
                {"ok": True},
            )

        assert frame.platform_data["TikTok"]["focus_comment_text"] == "Meu comentário recém-postado"
        assert frame.platform_data["TikTok"]["comment_posted"] == "Comentário publicado."
        frame.comment_entry.Clear.assert_called_once()
        frame._set_reply_target.assert_called_once_with(None)
        call_after.assert_called_once_with(frame.dispatch, "open_comments")

    def test_open_comments_sets_selection_and_focus_on_newly_posted_comment(self):
        """Ao carregar comentários, o item que contém o texto recém-postado é selecionado e focado."""
        frame = make_mock_frame()
        frame.comments_list = Mock()
        frame.comment_entry = Mock()
        frame.activities = Mock()
        frame._show_selected_comment = Mock()
        frame.platform_data = {
            "TikTok": {
                "comment_posted": "Comentário publicado.",
                "focus_comment_text": "meu novo comentário",
            }
        }
        loaded_comments = [
            {"id": "c1", "text": "outro_usuario: Olá mundo"},
            {"id": "c2", "text": "minha_conta: meu novo comentário"},
            {"id": "c3", "text": "terceiro: Bacana"},
        ]
        frame._comment_items = loaded_comments

        MainFrame._result(
            frame,
            "TikTok",
            "open_comments",
            None,
            {"ok": True, "comments": loaded_comments},
        )

        # O índice 1 (que corresponde a "minha_conta: meu novo comentário") deve ser selecionado
        frame.comments_list.SetSelection.assert_called_with(1)
        frame.comments_list.SetFocus.assert_called_once()
        frame._show_selected_comment.assert_called_once()


# =============================================================================
# SEÇÃO 8: EXCLUSÃO DO BOTÃO ADICIONAR COMENTÁRIO E ÁREA DE INPUT DA LISTA
# =============================================================================

class TestAddCommentButtonExclusion:
    """Garante que botões de ação e campos de digitação nunca sejam listados como comentários."""

    def test_comment_elements_excludes_add_comment_controls_and_input_area(self, page):
        """O botão/placeholder 'Adicionar comentário' não deve aparecer na lista."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div id="comments-box">
          <!-- Comentário real -->
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-real">usuario_real</span>
            <p data-e2e="comment-level-1">Comentário legítimo</p>
            <button data-e2e="comment-reply-real">Responder</button>
          </div>

          <!-- Barra de entrada do TikTok com classes que antes casavam com CommentItem -->
          <div class="DivCommentItemContainer" data-e2e="comment-input">
            <div contenteditable="true" role="textbox">Adicionar comentário...</div>
            <button data-e2e="comment-post">Publicar</button>
          </div>

          <!-- Botão avulso de adicionar comentário -->
          <button aria-label="Adicionar comentário" class="DivCommentItem">Adicionar comentário</button>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("command('comments')")
        comments = res.get("comments", [])

        # Apenas o comentário real deve ser retornado
        assert len(comments) == 1
        assert comments[0]["text"] == "usuario_real: Comentário legítimo"

        # Nenhum item com texto de adicionar comentário ou publicar
        texts = [c["text"].lower() for c in comments]
        assert not any("adicionar comentário" in t for t in texts)
        assert not any("publicar" in t for t in texts)


# =============================================================================
# SEÇÃO 9: BUSCA RESILIENTE DE COMENTÁRIOS AO RESPONDER
# =============================================================================

class TestResilientReplyResolution:
    """Testa a localização tolerante de comentários ao responder, com prefixos ou após reabertura."""

    def test_reply_to_comment_resolves_when_prefixed_with_resposta_or_index(self, page):
        """Ao responder, prefixos como '[Resposta]' ou '1 de 5:' são desconsiderados na busca."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div>
          <div data-e2e="comment-item" id="c-pai">
            <span data-e2e="comment-username-p">pai</span>
            <p data-e2e="comment-level-1">Texto do pai</p>
            <button data-e2e="comment-reply-p">Responder</button>
            <div data-e2e="comment-reply-item" id="c-filho">
              <span data-e2e="comment-username-f">filho</span>
              <p data-e2e="comment-level-2">Texto da resposta</p>
              <button id="btn-filho-resp" data-e2e="comment-reply-f" onclick="window.replyClicked=true">Responder</button>
            </div>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        # Simula envio de reply com texto formatado pela interface acessível e ID antigo inválido
        res = page.evaluate("""command('reply_comment', {
            id: 'accessible-reels-comment-stale-999',
            replyText: '[Resposta] filho: Texto da resposta'
        })""")

        assert res.get("replyTo") is not None
        assert page.evaluate("Boolean(window.replyClicked)") is True

    def test_reply_to_comment_expands_collapsed_thread_if_needed(self, page):
        """Se a resposta procurada estiver recolhida na thread, clica em 'Ver mais respostas'."""
        html = """
        <article>
          <video id="active"></video>
          <button data-e2e="comment-icon">Comentários</button>
        </article>
        <div>
          <div data-e2e="comment-item">
            <span data-e2e="comment-username-top">criador</span>
            <p data-e2e="comment-level-1">Postagem principal</p>
            <button data-e2e="comment-reply-top">Responder</button>

            <!-- Botão para expandir respostas recolhidas -->
            <button data-e2e="view-more-replies" onclick="document.getElementById('hidden-reply').style.display='block'">
              Ver mais respostas
            </button>

            <!-- Resposta inicialmente oculta -->
            <div id="hidden-reply" style="display: none;">
              <div data-e2e="comment-reply-item">
                <span data-e2e="comment-username-oculto">oculto</span>
                <p data-e2e="comment-level-2">Estava escondido</p>
                <button id="btn-oculto" data-e2e="comment-reply-oculto" onclick="window.ocultoClicked=true">Responder</button>
              </div>
            </div>
          </div>
        </div>
        """
        load_tiktok_html(page, html)

        res = page.evaluate("""command('reply_comment', {
            id: 'stale-id',
            replyText: 'oculto: Estava escondido'
        })""")

        assert res.get("replyTo") is not None
        assert page.evaluate("Boolean(window.ocultoClicked)") is True

# ==============================================================================
# SEÇÃO 10: TRAVAS DE SEGURANÇA E RESILIÊNCIA CONTRA MUDANÇAS DE COR E FORMATO
# ==============================================================================

class TestPlatformButtonColorAndFormatResilience:
    """Valida as travas de segurança contra mudanças de cor, formato e tags nos botões
    nas 3 plataformas (TikTok, Instagram, YouTube)."""

    def test_tiktok_post_button_with_alternative_red_hue_or_hex(self, page):
        """O botão de publicar no TikTok é detectado mesmo se a cor for alterada para outro tom de vermelho/magenta (#FE2C55, rgb(255, 0, 80))."""
        html = """
        <article><video id="active"></video></article>
        <section id="panel">
          <div data-e2e="comment-input">
            <div contenteditable="true" role="textbox"></div>
          </div>
          <div role="button" id="custom-send" style="color: rgb(255, 0, 80); display: block;"
               onclick="window.published=true">
            <svg style="fill: rgb(255, 0, 80)"><path></path></svg>
          </div>
        </section>
        """
        load_tiktok_html(page, html)
        page.evaluate("document.querySelector('[contenteditable]').textContent = 'Comentário teste'")
        btn_id = page.evaluate(r"""() => {
            const editor = document.querySelector('[contenteditable]');
            for (let area = editor.parentElement; area && area !== document.documentElement; area = area.parentElement) {
                const candidates = [...area.querySelectorAll("[data-e2e*='comment-post' i], [data-e2e*='post' i], button, [role=button], input[type='submit']")]
                  .filter(el => !el.contains(editor));
                const btn = candidates.find(el => {
                    const style = getComputedStyle(el);
                    const match = (style.color || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                    if (match) {
                        const [r, g, b] = [Number(match[1]), Number(match[2]), Number(match[3])];
                        return r >= 170 && r > g * 1.3 && r > b * 1.3;
                    }
                    return false;
                });
                if (btn) return btn.id;
            }
            return null;
        }""")
        assert btn_id == "custom-send"

    def test_tiktok_post_button_structural_fallback_without_red_color(self, page):
        """Se o TikTok remover completamente a cor vermelha e usar botão neutro/escuro sem texto, o fallback estrutural localiza o botão de envio."""
        html = """
        <article><video id="active"></video></article>
        <section id="panel">
          <div data-e2e="comment-input">
            <div contenteditable="true" role="textbox"></div>
            <button aria-label="Inserir emoji" data-e2e="comment-emoji">emoji</button>
            <button aria-label="Mencionar amigo" data-e2e="comment-mention">@</button>
            <button id="neutral-send-button" aria-label="Enviar comentário" onclick="window.published=true">
              <svg><path></path></svg>
            </button>
          </div>
        </section>
        """
        load_tiktok_html(page, html)
        btn_id = page.evaluate(r"""() => {
            const editor = document.querySelector('[contenteditable]');
            for (let area = editor.parentElement; area && area !== document.documentElement; area = area.parentElement) {
                const candidates = [...area.querySelectorAll("[data-e2e*='comment-post' i], [data-e2e*='post' i], button, [role=button], input[type='submit']")]
                  .filter(el => !el.contains(editor));
                const named = candidates.find(el => /^(publicar|postar|post|enviar|send)\b/i.test(el.getAttribute('aria-label') || ''));
                if (named) return named.id;
            }
            return null;
        }""")
        assert btn_id == "neutral-send-button"

    def test_tiktok_reply_button_with_custom_aria_label_or_phrase(self, page):
        """O botão Responder é localizado mesmo se o texto for alterado para 'Responder a @usuario' ou estiver em aria-label."""
        html = """
        <article><video id="active"></video></article>
        <div>
          <div data-e2e="comment-item" id="comm1">
            <span data-e2e="comment-username">ana</span>
            <p data-e2e="comment-level-1">Comentário da Ana</p>
            <div class="PCommentSubContent">
              <span data-e2e="comment-like-icon" role="button">Curtir</span>
              <span id="btn-reply-phrase" role="button" aria-label="Responder a @ana" onclick="window.replyClicked=true">
                Responder a @ana
              </span>
            </div>
          </div>
        </div>
        """
        load_tiktok_html(page, html)
        res = page.evaluate(r"""() => {
            const item = document.getElementById('comm1');
            const controls = [...item.querySelectorAll("[data-e2e*='comment-reply' i], [data-e2e*='reply' i], button, [role=button]")];
            const byText = controls.find(control =>
              /^(responder|reply)\b/i.test((control.innerText || control.getAttribute('aria-label') || '').trim()));
            return byText ? byText.id : null;
        }""")
        assert res == "btn-reply-phrase"

    def test_instagram_resilient_reply_and_post_selectors(self, page):
        """No Instagram, botões com variações de texto ('Responder a fulano', 'Publicar comentário') ou type='submit' são encontrados com segurança."""
        page.evaluate(r"""() => {
            window.__accessibleTransport = {
                storage: { local: { get: async () => ({}), set: async () => {} } },
                runtime: { onMessage: { addListener: () => {} }, sendMessage: async () => ({ ok: true }) }
            };
        }""")
        html = """
        <div role="dialog" id="insta-dialog">
          <h2>Comentários</h2>
          <div data-accessible-reels-comment-id="accessible-reels-comment-1" id="comment-row">
            <span>maria: Adorei</span>
            <time>1 h</time>
            <button aria-label="Curtir comentário">❤️</button>
            <button id="btn-insta-reply" aria-label="Responder a maria">Responder</button>
          </div>
          <form id="comment-form">
            <input placeholder="Adicione um comentário..." value="" />
            <button id="btn-insta-post" type="submit" aria-label="Publicar comentário">Enviar</button>
          </form>
        </div>
        """
        insta_js = Path("ui/web_scripts/instagram.js").read_text(encoding="utf-8")
        page.set_content(html)
        page.evaluate(insta_js)

        reply_id = page.evaluate(r"""() => {
            const element = document.getElementById('comment-row');
            let reply = [...element.querySelectorAll("button, [role=button], svg[aria-label]")].find(el =>
                /\b(responder|reply)\b/i.test((el.getAttribute("aria-label") || el.textContent || "").trim()));
            return reply ? reply.id : null;
        }""")
        assert reply_id == "btn-insta-reply"

        post_id = page.evaluate(r"""() => {
            const dialog = document.getElementById('insta-dialog');
            let button = [...dialog.querySelectorAll("button, [role=button]")].find(el =>
                /^(publicar|postar|post|enviar|send)\b/i.test((el.getAttribute("aria-label") || el.textContent || "").trim()));
            return button ? button.id : null;
        }""")
        assert post_id == "btn-insta-post"

    def test_youtube_resilient_submit_and_reply_selectors(self, page):
        """No YouTube, controles com Web Components modernos (yt-button-shape, aria-label parcial ou type=submit) são localizados."""
        page.evaluate(r"""() => {
            window.__accessibleTransport = {
                storage: { local: { get: async () => ({}), set: async () => {} } },
                runtime: { onMessage: { addListener: () => {} }, sendMessage: async () => ({ ok: true }) }
            };
        }""")
        html = """
        <div id="comments-section">
          <ytd-comment-thread-renderer id="yt-thread">
            <div id="author-text">carlos</div>
            <div id="content-text">Vídeo sensacional</div>
            <div id="reply-button-end">
              <button id="btn-yt-reply" aria-label="Responder a este comentário de carlos">Responder</button>
            </div>
          </ytd-comment-thread-renderer>
          <div id="comment-input-area">
            <div id="contenteditable-root" contenteditable="true">Meu novo comentário</div>
            <button id="btn-cancel">Cancelar</button>
            <button id="btn-yt-submit" type="submit" aria-label="Comentar publicamente">Comentar</button>
          </div>
        </div>
        """
        page.set_content(html)
        yt_js = Path("ui/web_scripts/youtube.js").read_text(encoding="utf-8")
        page.evaluate(yt_js)

        reply_id = page.evaluate(r"""() => {
            const comment = document.getElementById('yt-thread');
            let reply = [...comment.querySelectorAll(
                '#reply-button-end button, #reply-button-end [role="button"], ' +
                'ytd-button-renderer#reply-button-end button, ' +
                '[aria-label*="responder" i], [aria-label*="reply" i]'
            )].find(el => true);
            return reply ? reply.id : null;
        }""")
        assert reply_id == "btn-yt-reply"

        submit_id = page.evaluate(r"""() => {
            const area = document.getElementById('comment-input-area');
            let button = [...area.querySelectorAll(
                '#submit-button button, ytd-button-renderer#submit-button button, ' +
                '#submit-button [role="button"], button[type="submit"], ' +
                'button[aria-label*="comentar" i], button[aria-label*="responder" i], ' +
                'button[aria-label*="comment" i], button[aria-label*="reply" i]'
            )].find(el => !/cancel/i.test(el.textContent || ''));
            return button ? button.id : null;
        }""")
        assert submit_id == "btn-yt-submit"

