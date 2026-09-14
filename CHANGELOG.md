# Histórico de versões

## 1.0.10 — 2026-09-14

Esta versão amplia o Accessible Reels para YouTube Shorts, melhora o controle
dos perfis e torna os atalhos mais flexíveis para uso com leitor de telas.

### Plataformas e navegação

- Adicionado suporte a YouTube Shorts, inclusive pesquisa, reprodução,
  navegação entre vídeos, perfil e download.
- A pesquisa e a navegação por perfis foram reforçadas em TikTok, Instagram e
  YouTube para preservar o foco nos controles acessíveis do aplicativo.
- O controle de seguir no TikTok agora consulta o estado real do perfil e
  informa se a conta foi seguida ou deixada de seguir.

### Atalhos e reprodução

- As Configurações ganharam a guia Atalhos: todos os comandos podem ser
  alterados em uma única lista e marcados como globais.
- Atalhos globais continuam funcionando com a janela minimizada, e Próximo ou
  Anterior aguardam a página terminar um comando em vez de serem perdidos.
- Minimizar o aplicativo não interrompe o vídeo da plataforma ativa.

### Downloads e estabilidade

- O download usa a sessão já aberta no navegador e inclui o yt-dlp no pacote
  para os casos em que ele for necessário.
- Foram melhoradas as mensagens de carregamento, login e recuperação de falhas
  temporárias das plataformas.

## 1.0.9 — 2026-09-13

- O instalador passou a validar os scripts incorporados do WebView2 antes de
  gerar uma release.
- A base de atualização e o runtime do navegador receberam verificações de
  integridade adicionais.

## 1.0.8 — 2026-09-13

- Ajustes de estabilidade no runtime WebView2 e no processo de atualização.
