# Histórico de versões

## 1.3.1 — 2026-11-27

- TikTok: corrigida a captura de links durante a navegação para garantir que
  o aplicativo nunca pegue o link de outro vídeo presente no feed.
- TikTok: corrigida a navegação no feed para acompanhar com precisão o vídeo
  centralizado na tela.
- TikTok: a navegação por teclado agora pula automaticamente posts compostos
  apenas por fotos, evitando que a rolagem trave no meio do feed.
- TikTok: corrigida a interação com comentários para permitir cliques suficientes
  para responder e evitar cliques dispersos na página.
- TikTok: o leitor de telas agora avisa caso haja algum diálogo ou modal cobrindo
  o painel de comentários.
- TikTok: aprimorada a leitura de autor e descrição do vídeo através de atalhos de teclado.
- Instagram: corrigido o aviso de login para que só seja solicitado quando a conta
  estiver de fato desconectada.
- Instagram: corrigido o alerta para leitores de tela quando a visualização dos
  comentários exigir autenticação.
- Instagram: estabilizada a reprodução para não reiniciar o vídeo caso o elemento
  de mídia na página seja recriado.
- Janela no Windows: corrigida a restauração da posição da janela ao desminimizar
  o aplicativo.
- Login social: corrigida a vinculação de janelas de login social (como Google) para
  que permaneçam associadas à sessão principal.
- Volume inicial: padronizado para iniciar em 50% em todas as redes ao começar a
  reprodução, evitando picos de volume.
- Motor de downloads: atualizado o executável embutido do yt-dlp para a versão
  mais recente e compatível com as plataformas.
- Manutenção: compatibilidade de threads com o Python 3.14 e proteções no ambiente de build.

## 1.3.0 — 2026-10-07

- Meus vídeos curtidos e favoritos do TikTok: Alt+Shift+L lista os vídeos que
  você curtiu e Alt+Shift+F lista os favoritos, direto na aba de resultados.
  A lista abre assim que os primeiros 50 vídeos ficam prontos e continua
  carregando em segundo plano, até 500 vídeos. Dentro da lista, Enter abre o
  vídeo, Alt+seta passa para o próximo ou o anterior e Ctrl+R volta à lista.
  Alt+L descurte e Alt+F remove dos favoritos o vídeo aberto.
- Shorts curtidos no YouTube: com o YouTube Shorts aberto, Alt+Shift+L lista
  os Shorts que você curtiu.
- Download em lote: Ctrl+Shift+L baixa todos os vídeos da lista que está na
  tela, um por vez, pulando os que já estão na pasta. Pressione de novo para
  cancelar.
- Instagram: corrigido o vídeo que começava a tocar, parava e voltava do
  início ao abrir um Reel por link. Agora ele só começa depois de carregado
  e, se o Instagram recriar o player logo no começo, o vídeo continua de onde
  estava em vez de repetir o início.

## 1.2.2 — 2026-09-29

- Corrigida a navegação por Alt+seta (próximo/anterior vídeo), que no
  TikTok podia falhar repetidamente com "O TikTok não mudou de vídeo".
  Agora a troca de vídeo também tenta uma tecla de seta real, o que reage
  diretamente na própria plataforma e não depende de botões que podem
  mudar de marcação. Aplicado em TikTok, Instagram e YouTube.

## 1.2.1 — 2026-09-28

- Corrigido o empacotamento do instalador: o arquivo com o histórico de
  versões não estava incluído, e o diálogo de novidades falhava ao abrir
  logo após atualizar para a 1.2.0.

## 1.2.0 — 2026-09-28

- Rolagem automática dos vídeos: ativada, ela avança para o próximo vídeo
  sozinha quando o atual termina. Funciona com a janela do aplicativo em
  primeiro plano; em segundo plano, não funciona, por limitações do WebView2
  e das próprias plataformas — nesse caso, avance normalmente. Obrigado,
  @rafaela-sborges, pela contribuição e implementação.
- Controle de reprodução pelas teclas de mídia: pausar, retroceder e avançar
  os vídeos, tanto pelas teclas do teclado quanto pelas do fone de ouvido,
  quando disponíveis. Obrigado, @Davy, pela sugestão.
- Download de áudio: além do vídeo completo, agora também é possível baixar
  apenas o áudio. Obrigado, @Sasu, pela sugestão.
- Abertura de links direto pelo aplicativo: definindo o Accessible Reels
  como aplicativo padrão no Windows, links de TikTok, Instagram e YouTube
  Shorts abrem direto no app; qualquer outro tipo de link continua abrindo
  no seu navegador padrão.
- Corrigido o diálogo de atualizações: as novidades da versão aparecem uma
  única vez após atualizar, e essa mensagem não é exibida de novo depois.

Obrigado a todos pelas contribuições e sugestões!

## 1.1.1 — 2026-09-14

- Corrigido o empacotamento do motor de downloads para as versões atuais do
  PyInstaller. O instalador inclui o yt-dlp e o Accessible Reels o localiza
  corretamente após a instalação.

## 1.1.0 — 2026-09-14

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
