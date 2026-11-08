"""Simulador Completo do Accessible Reels:
1. Instalador e ambiente empacotado fictício.
2. Ações manuais e atalhos de teclado do player.
3. Fluxo de publicação e resposta de comentários (TikTok, Instagram, YouTube).
4. Fluxo de transmissões ao vivo (TikTok Lives), busca, bloqueio de download e controle de chat.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wx
import wx.html2 as html2

from app_version import APP_NAME, APP_VERSION
import link_router
from tiktok.search import SearchResult, normalize_search_results, search_url
from tiktok.video_controls import select_current_url
from ui.app_frame import COMMENT_LIMITS, CANCEL_REPLY_LABEL, REPLY_LABEL, MainFrame, prepare_comment
from ui.shortcuts import DEFAULT_SHORTCUTS, SHORTCUT_DEFINITIONS
from ui.video_link import parse_video_link
from ui.webview_client import ACTIONS, PLATFORM_URLS, WebViewClient
from video_download import load_download_settings, save_download_settings


@dataclass
class SimulationReport:
    step_name: str
    passed: bool
    details: str
    errors: list[str] = field(default_factory=list)


class AppSimulator:
    def __init__(self):
        self.reports: list[SimulationReport] = []
        self.temp_dir = Path(tempfile.mkdtemp(prefix="accessible_reels_sim_"))
        self.app = wx.App(False)

    def log_step(self, name: str, passed: bool, details: str, errors: list[str] | None = None):
        report = SimulationReport(name, passed, details, errors or [])
        self.reports.append(report)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {details}")
        if errors:
            for err in errors:
                print(f"       -> Erro: {err}")

    def create_mocked_frame(self) -> MainFrame:
        """Cria e prepara um MainFrame com views e clients inicializados para simulação."""
        with patch("ui.app_frame.webview_profile_path", return_value=self.temp_dir / "profile"), \
             patch("ui.app_frame.can_self_update", return_value=False):
            frame = MainFrame()
            for platform in ("TikTok", "Instagram", "YouTube"):
                mock_view = Mock()
                mock_view.SetCanFocus = Mock()
                mock_view.Show = Mock()
                mock_view.Hide = Mock()
                mock_view.GetCurrentURL = Mock(return_value=PLATFORM_URLS[platform])
                frame.views[platform] = mock_view

                mock_client = Mock()
                mock_client.pending = None
                mock_client.alive = True
                mock_client.active = (platform == frame._active_name)
                mock_client.set_active = Mock()
                mock_client.execute = Mock()
                mock_client.navigate = Mock()
                mock_client.after_load = None
                frame.clients[platform] = mock_client

                frame.platform_data[platform] = {}

            frame.status = Mock()
            return frame

    # =========================================================================
    # 1. Simulação do Instalador Fictício e Estrutura de Pacote
    # =========================================================================
    def simulate_mock_installer(self):
        print("\n--- [ETAPA 1] Simulando Instalador Fictício e Integridade do Pacote ---")
        errors = []
        install_dir = self.temp_dir / "ProgramFiles" / "Accessible Reels"
        install_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1.1 Simular arquivos instalados pelo instalador
            (install_dir / "Accessible Reels.exe").write_text("MOCK_EXE", encoding="utf-8")
            (install_dir / "yt-dlp.exe").write_text("MOCK_YTDLP", encoding="utf-8")
            (install_dir / "CHANGELOG.md").write_text(f"## {APP_VERSION}\n- Teste de versão\n", encoding="utf-8")
            (install_dir / "runtime" / "152.0.4191.62").mkdir(parents=True, exist_ok=True)
            (install_dir / "runtime" / "152.0.4191.62" / "msedgewebview2.exe").write_text("MOCK_RUNTIME", encoding="utf-8")

            # 1.2 Conferir consistência de versões entre arquivos do projeto
            iss_text = (ROOT / "installer" / "accessible-reels.iss").read_text(encoding="utf-8")
            build_script = (ROOT / "scripts" / "build_windows_release.ps1").read_text(encoding="utf-8")
            changelog_text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

            if f"v{APP_VERSION}" not in changelog_text and f"{APP_VERSION}" not in changelog_text:
                errors.append(f"CHANGELOG.md não menciona a versão atual {APP_VERSION}")

            if "AppVersion" not in iss_text:
                errors.append("installer/accessible-reels.iss não contém a diretiva AppVersion")

            # 1.3 Simular roteamento e reconhecimento de URLs
            test_url_tiktok = "https://www.tiktok.com/@usuario/video/123456789"
            test_url_tiktok_live = "https://www.tiktok.com/@streamer/live"
            test_url_reels = "https://www.instagram.com/reel/C_xyz123/"
            test_url_shorts = "https://www.youtube.com/shorts/AbCdEfGhIjK"
            test_url_external = "https://www.google.com/search?q=acessibilidade"

            p_tt, u_tt = parse_video_link(test_url_tiktok)
            p_tt_live, u_tt_live = parse_video_link(test_url_tiktok_live)
            p_ig, u_ig = parse_video_link(test_url_reels)
            p_yt, u_yt = parse_video_link(test_url_shorts)
            is_ext_video = link_router.is_video_link(test_url_external)

            if p_tt != "TikTok" or "123456789" not in u_tt:
                errors.append(f"Falha ao reconhecer URL do TikTok: {test_url_tiktok}")
            if p_tt_live != "TikTok" or "/live" not in u_tt_live:
                errors.append(f"Falha ao reconhecer TikTok Live: {test_url_tiktok_live}")
            if p_ig != "Instagram" or "C_xyz123" not in u_ig:
                errors.append(f"Falha ao reconhecer Reel do Instagram: {test_url_reels}")
            if p_yt != "YouTube" or "AbCdEfGhIjK" not in u_yt:
                errors.append(f"Falha ao reconhecer Shorts do YouTube: {test_url_shorts}")
            if is_ext_video:
                errors.append(f"URL externa não deveria ser reconhecida como link de vídeo: {test_url_external}")

            # 1.4 Simulação de abertura em navegador externo para links externos
            with patch("subprocess.Popen") as mock_popen:
                link_router.open_in_default_browser(test_url_external)
                if not mock_popen.called:
                    errors.append("open_in_default_browser não disparou processo de abertura")

            passed = len(errors) == 0
            self.log_step("Instalador Fictício e Roteamento", passed,
                          f"Instalador simulado com APP_VERSION={APP_VERSION}, runtime, yt-dlp e roteamento de links.", errors)
        except Exception as exc:
            self.log_step("Instalador Fictício e Roteamento", False, f"Exceção inesperada: {exc}", [str(exc)])

    # =========================================================================
    # 2. Simulação de Ações Manuais e Atalhos de Teclado no Player
    # =========================================================================
    def simulate_manual_actions_and_shortcuts(self):
        print("\n--- [ETAPA 2] Simulando Ações Manuais e Teclas de Atalho do Player ---")
        errors = []
        try:
            frame = self.create_mocked_frame()

            # 2.1 Alternância de Redes
            for platform_name in ("TikTok", "Instagram", "YouTube"):
                frame.network.SetStringSelection(platform_name)
                frame.select_network()
                if frame._active_name != platform_name:
                    errors.append(f"Falha ao alternar para a rede {platform_name}")

            # Volta para TikTok
            frame.network.SetStringSelection("TikTok")
            frame.select_network()

            # 2.2 Simular reprodução/pausa (Alt+P -> toggle_playback)
            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("toggle_playback")
            frame.clients["TikTok"].execute.assert_called_once()
            called_action = frame.clients["TikTok"].execute.call_args[0][0]
            if called_action != "toggle":
                errors.append(f"Ação executada para toggle_playback foi '{called_action}'; esperado 'toggle'")

            # 2.3 Simular navegação de vídeos (Alt+Down -> next_video, Alt+Up -> previous_video)
            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("next_video")
            frame.clients["TikTok"].execute.assert_called_once()
            if frame.clients["TikTok"].execute.call_args[0][0] != "next":
                errors.append("Ação para next_video incorreta")

            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("previous_video")
            frame.clients["TikTok"].execute.assert_called_once()
            if frame.clients["TikTok"].execute.call_args[0][0] != "previous":
                errors.append("Ação para previous_video incorreta")

            # 2.4 Simular atalhos de volume (Alt+Shift+Up, Alt+Shift+Down, Alt+Shift+M)
            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("volume_up")
            frame._invoke_shortcut("volume_down")
            frame._invoke_shortcut("toggle_mute")
            if frame.clients["TikTok"].execute.call_count < 3:
                errors.append("Atalhos de volume/mudo não foram despachados corretamente")

            # 2.5 Simular leitura de autor e descrição (Alt+A e Alt+D)
            frame.platform_data["TikTok"] = {"author": "Criador Teste", "description": "Vídeo acessível de teste"}
            frame.status.reset_mock()
            frame._result("TikTok", "read_author", None, {"ok": True, "author": "Criador Teste"})
            frame.status.assert_called_with("Autor: Criador Teste")

            frame.status.reset_mock()
            frame._result("TikTok", "read_description", None, {"ok": True, "description": "Vídeo acessível de teste"})
            frame.status.assert_called_with("Descrição: Vídeo acessível de teste")

            # 2.6 Simular cópia de link limpo (Alt+C -> copy_link)
            with patch("ui.app_frame._copy_text_to_clipboard") as mock_clip:
                mock_clip.return_value = True
                frame._result("TikTok", "copy_link", None, {
                    "ok": True,
                    "link": "https://www.tiktok.com/@criador/video/987654321?is_from_webapp=1&sender_device=pc"
                })
                mock_clip.assert_called_once()
                copied_link = mock_clip.call_args[0][0]
                if "?" in copied_link:
                    errors.append(f"Link copiado ainda contém parâmetros de rastreamento: {copied_link}")
                if copied_link != "https://www.tiktok.com/@criador/video/987654321":
                    errors.append(f"Link limpo copiado incorreto: {copied_link}")

            # 2.7 Diagnóstico Acessível (Alt+F12)
            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("diagnostics")
            frame.clients["TikTok"].execute.assert_called_once()
            called_action = frame.clients["TikTok"].execute.call_args[0][0]
            if called_action != "diagnostics":
                errors.append(f"Ação para diagnostics foi '{called_action}'; esperado 'diagnostics'")

            frame.status.reset_mock()
            with patch("ui.app_frame._copy_text_to_clipboard", return_value=True):
                frame._result("TikTok", "diagnostics", None, {"ok": True, "message": "Página incorporada conectada."})
            frame.status.assert_called()

            frame.Close()

            passed = len(errors) == 0
            self.log_step("Ações Manuais e Atalhos", passed,
                          "Atalhos de navegação, volume, leitura de autor/descrição, cópia limpa de link e diagnóstico validados.", errors)
        except Exception as exc:
            self.log_step("Ações Manuais e Atalhos", False, f"Exceção durante simulação de ações: {exc}", [str(exc)])

    # =========================================================================
    # 3. Simulação Completa do Fluxo de Comentários
    # =========================================================================
    def simulate_comments_flow(self):
        print("\n--- [ETAPA 3] Simulando Fluxo Completo de Comentários ---")
        errors = []
        try:
            # 3.1 Validações de limites e texto
            try:
                prepare_comment("", "TikTok")
                errors.append("prepare_comment aceitou texto vazio")
            except ValueError:
                pass

            too_long_tiktok = "A" * (COMMENT_LIMITS["TikTok"] + 1)
            try:
                prepare_comment(too_long_tiktok, "TikTok")
                errors.append(f"prepare_comment aceitou texto com {len(too_long_tiktok)} caracteres no TikTok")
            except ValueError:
                pass

            valid_comment = prepare_comment("  Ótimo conteúdo sobre acessibilidade!  ", "TikTok")
            if valid_comment != "Ótimo conteúdo sobre acessibilidade!":
                errors.append(f"prepare_comment não normalizou espaços corretamente: '{valid_comment}'")

            # 3.2 Simulação de UI e envio com MainFrame
            frame = self.create_mocked_frame()
            frame.network.SetStringSelection("TikTok")
            frame.select_network()

            # 3.3 Listar comentários (open_comments)
            mock_comments = [
                {"id": "c1", "text": "maria: Adorei o vídeo!"},
                {"id": "c2", "text": "joao: Muito útil, parabéns!"}
            ]
            frame._result("TikTok", "open_comments", None, {"ok": True, "comments": mock_comments})
            if frame.comments_list.GetCount() != 2:
                errors.append(f"Lista de comentários possui {frame.comments_list.GetCount()} itens; esperado 2")

            # 3.4 Publicar Novo Comentário
            frame.comment_entry.SetValue("Parabéns pelo trabalho!")
            with patch.object(frame, "dispatch") as mock_dispatch, \
                 patch("ui.app_frame.wx.MessageBox", return_value=wx.YES):
                frame._publish_comment()
                mock_dispatch.assert_called_once_with("post_comment", {"text": "Parabéns pelo trabalho!"})

            # Simular retorno de sucesso da publicação de comentário
            frame.comment_entry.SetValue("Parabéns pelo trabalho!")
            with patch("ui.app_frame.wx.CallAfter"):
                frame._result("TikTok", "post_comment", {"text": "Parabéns pelo trabalho!"}, {"ok": True})
            if frame.comment_entry.GetValue() != "":
                errors.append("Campo de comentário não foi limpo após publicação bem-sucedida")

            # 3.5 Responder Comentário Selecionado
            frame.comments_list.SetSelection(1)  # Seleciona c2 (joao)
            frame._reply_to_selected()
            if frame._reply_target != {"id": "c2", "text": "joao: Muito útil, parabéns!", "index": 2}:
                errors.append(f"Alvo de resposta incorreto: {frame._reply_target}")
            if frame.reply_button.GetLabel() != CANCEL_REPLY_LABEL:
                errors.append(f"Rótulo do botão de resposta não mudou para '{CANCEL_REPLY_LABEL}': {frame.reply_button.GetLabel()}")

            # Digitar resposta e publicar
            frame.comment_entry.SetValue("Concordo plenamente!")
            with patch.object(frame, "dispatch") as mock_dispatch, \
                 patch("ui.app_frame.wx.MessageBox", return_value=wx.YES):
                frame._publish_comment()
                mock_dispatch.assert_called_once_with("post_comment", {
                    "text": "Concordo plenamente!",
                    "replyTo": "c2",
                    "replyText": "joao: Muito útil, parabéns!"
                })

            # Simular sucesso da resposta
            with patch("ui.app_frame.wx.CallAfter"):
                frame._result("TikTok", "post_comment", {
                    "text": "Concordo plenamente!",
                    "replyTo": "c2",
                    "replyText": "joao: Muito útil, parabéns!"
                }, {"ok": True})
            if frame._reply_target is not None:
                errors.append("Alvo de resposta não foi resetado após publicação")
            if frame.reply_button.GetLabel() != REPLY_LABEL:
                errors.append(f"Rótulo do botão não voltou para '{REPLY_LABEL}': {frame.reply_button.GetLabel()}")

            # 3.6 Cancelar resposta manualmente
            frame.comments_list.SetSelection(0)
            frame._toggle_reply()  # ativa resposta
            if frame._reply_target is None:
                errors.append("Falha ao ativar resposta via _toggle_reply")
            frame._toggle_reply()  # cancela resposta
            if frame._reply_target is not None:
                errors.append("Falha ao cancelar resposta via _toggle_reply")

            frame.Close()

            passed = len(errors) == 0
            self.log_step("Fluxo de Comentários", passed,
                          "Abertura de comentários, validação de limites, novo comentário, resposta direta a usuário e cancelamento validados.", errors)
        except Exception as exc:
            self.log_step("Fluxo de Comentários", False, f"Exceção no fluxo de comentários: {exc}", [str(exc)])

    # =========================================================================
    # 4. Simulação Completa do Fluxo de Lives (Transmissões ao Vivo)
    # =========================================================================
    def simulate_lives_flow(self):
        print("\n--- [ETAPA 4] Simulando Fluxo Completo de Transmissões ao Vivo (Lives) ---")
        errors = []
        try:
            # 4.1 Teste de busca com e sem inclusão de lives
            url_no_lives = search_url("acessibilidade", include_lives=False)
            url_with_lives = search_url("acessibilidade", include_lives=True)
            if "search/video" not in url_no_lives:
                errors.append(f"Busca sem lives deveria usar /search/video: {url_no_lives}")
            if url_with_lives != "https://www.tiktok.com/search?q=acessibilidade":
                errors.append(f"Busca com lives deveria usar /search?q=...: {url_with_lives}")

            # 4.2 Normalização de resultados de busca com lives
            raw_results = [
                {"url": "https://www.tiktok.com/@criador/video/111", "author": "criador", "description": "Vídeo normal"},
                {"url": "https://www.tiktok.com/@streamer/live", "author": "streamer", "description": "Jogando ao vivo", "is_live": True}
            ]
            normalized = normalize_search_results(raw_results)
            if len(normalized) != 2:
                errors.append(f"Quantidade de resultados normalizados: {len(normalized)}; esperado 2")
            else:
                live_item = normalized[1]
                if not live_item.is_live:
                    errors.append("Item de live não foi marcado com is_live=True")
                if "[AO VIVO]" not in live_item.label:
                    errors.append(f"Rótulo acessível da live não contém '[AO VIVO]': {live_item.label}")

            # 4.3 Trava de segurança contra download de Lives em andamento
            frame = self.create_mocked_frame()
            frame.network.SetStringSelection("TikTok")
            frame.select_network()

            # Simula tentativa de download do vídeo da live
            with patch("video_download.download_video") as mock_down:
                frame.status.reset_mock()
                # Simula retorno do link de download apontando para live
                frame._download_resolved("TikTok", {"ok": True, "link": "https://www.tiktok.com/@streamer/live"}, audio=False)
                mock_down.assert_not_called()
                frame.status.assert_called_with("Não é possível baixar uma transmissão ao vivo em andamento.")

            # Simula tentativa de download do áudio da live
            with patch("video_download.download_video") as mock_down_audio:
                frame.status.reset_mock()
                frame._download_resolved("TikTok", {"ok": True, "link": "https://www.tiktok.com/@streamer/live"}, audio=True)
                mock_down_audio.assert_not_called()
                frame.status.assert_called_with("Não é possível baixar uma transmissão ao vivo em andamento.")

            # 4.4 Controle de silenciamento e ocultação do chat ao vivo (Alt+Shift+T)
            if "toggle_live_chat" not in ACTIONS:
                errors.append("toggle_live_chat ausente em ACTIONS de WebViewClient")

            # Despachar via atalho oficial
            frame.clients["TikTok"].execute.reset_mock()
            frame._invoke_shortcut("toggle_live_chat")
            frame.clients["TikTok"].execute.assert_called_once()
            called_action = frame.clients["TikTok"].execute.call_args[0][0]
            if called_action != "toggle_live_chat":
                errors.append(f"Ação executada para toggle_live_chat foi '{called_action}'; esperado 'toggle_live_chat'")

            # Simular resposta do chat ocultado/silenciado
            frame.status.reset_mock()
            frame._on_live_chat_toggled({"ok": True, "hidden": True})
            frame.status.assert_called_with("Chat ao vivo da live desativado e silenciado.")

            # Simular resposta do chat reativado
            frame.status.reset_mock()
            frame._on_live_chat_toggled({"ok": True, "hidden": False})
            frame.status.assert_called_with("Chat ao vivo da live ativado.")

            # Testar tentativa de alternar chat no Instagram (deve avisar que só funciona no TikTok)
            frame.network.SetStringSelection("Instagram")
            frame.select_network()
            frame.status.reset_mock()
            frame.dispatch("toggle_live_chat")
            frame.status.assert_called_with("O chat ao vivo está disponível apenas em transmissões do TikTok.")

            frame.Close()

            passed = len(errors) == 0
            self.log_step("Fluxo de Transmissões ao Vivo (Lives)", passed,
                          "Detecção de lives, busca configurável, rótulo [AO VIVO], bloqueio de download de live e toggle de chat validados.", errors)
        except Exception as exc:
            self.log_step("Fluxo de Transmissões ao Vivo (Lives)", False, f"Exceção no fluxo de lives: {exc}", [str(exc)])

    # =========================================================================
    # Limpeza e Relatório Geral
    # =========================================================================
    def finish(self) -> bool:
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("RELATÓRIO CONSOLIDADO DO SIMULADOR E TESTES MANUAIS")
        print("=" * 70)
        all_passed = True
        for rep in self.reports:
            status = "PASS" if rep.passed else "FAIL"
            if not rep.passed:
                all_passed = False
            print(f"[{status}] {rep.step_name}: {rep.details}")
            if rep.errors:
                for e in rep.errors:
                    print(f"       -> Falha: {e}")

        print("-" * 70)
        total = len(self.reports)
        passed_cnt = sum(1 for r in self.reports if r.passed)
        failed_cnt = total - passed_cnt
        print(f"Total de módulos simulados: {total}")
        print(f"Aprovados: {passed_cnt}")
        print(f"Reprovados: {failed_cnt}")
        print("=" * 70)
        return all_passed


def main():
    sim = AppSimulator()
    sim.simulate_mock_installer()
    sim.simulate_manual_actions_and_shortcuts()
    sim.simulate_comments_flow()
    sim.simulate_lives_flow()
    success = sim.finish()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
