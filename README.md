# Accessible Reels — segunda etapa

## Protótipo com navegador dentro do aplicativo

Durante um vídeo, **Alt+Shift+Esquerda/Direita** volta/avança 15 segundos;
**Alt+Esquerda/Direita** volta/avança 30 segundos. Os mesmos controles estão
na guia Vídeo. A posição fica limitada ao início e ao fim do vídeo, e o
aplicativo anuncia a nova posição. Funciona no TikTok e no Instagram.

Execute `.\.venv\Scripts\python.exe main.py --webview` para testar TikTok e
Instagram em WebView2, sem extensão e sem janela externa de navegador.
O instalador Windows x64 inclui o WebView2 Fixed Version **152.0.4191.62** completo.
A instalação do runtime funciona offline e não altera o WebView2 do Windows.
O aplicativo usa `runtime/152.0.4191.62` ao lado do executável, configurado antes do wxPython.
Se houver falha, use **Alt+J, Verificar runtime incluído...** e consulte os logs.
Ao executar pelo código sem a pasta `runtime`, continua sendo usado o runtime do sistema.

### Atualização do runtime e build

`webview2-runtime.json` fixa versão, arquitetura x64, URL oficial e SHA256 do CAB.
Para atualizar, baixe o pacote Fixed Version oficial, confira sua assinatura e atualize esses campos juntos.
O build verifica hash, assinatura Microsoft, versão e arquitetura; uma divergência interrompe a geração.
Mantenha uma cópia do CAB: a Microsoft pode retirar versões antigas do download.
O cache local fica em `.runtime-cache/webview2.cab` (não versionado).
Execute `scripts/build_windows_release.ps1`; o resultado é `dist/Accessible-Reels-Setup.exe`.
A primeira geração precisa de internet; a instalação do pacote pronto não precisa.
O wxPython também está fixado em `4.3.1` para manter o loader testado. Atualizações de segurança do runtime
precisam ser incorporadas nas próximas releases do aplicativo.
O instalador configura as permissões de leitura/execução exigidas pelo runtime no Windows 10.
O build executa `"Accessible Reels.exe" --check-runtime` antes de compilar o instalador.
Esse teste usa um perfil temporário, carrega uma página local e executa JavaScript; retorna 0 no sucesso.
Os resultados ficam em `%LOCALAPPDATA%\Accessible Reels\logs\accessible-reels.log`.
Antes de publicar, valide em Windows 10/11 sem WebView2 global, offline, além de login e navegação.

O app inicia sem abrir nenhuma plataforma. Ele segue o modelo de player por atalhos:
**Ctrl+1** abre TikTok e **Ctrl+2** abre Instagram. Use **F6** para alternar entre
a página e o painel do player; faça login quando necessário. **F1** abre a ajuda rápida.
A área superior informa a plataforma ativa e quais já foram abertas nesta sessão,
sem afirmar que o site aceitou o login — a página sempre pode pedir autenticação
outra vez.
F6 não abre redes: após abrir uma plataforma, aguarda o carregamento quando necessário
antes de focar um elemento da página. O atalho é reservado no Windows somente enquanto o
protótipo está ativo.

O perfil persistente fica em `%LOCALAPPDATA%\Accessible Reels\webview_profile`.
Versões de desenvolvimento migram automaticamente o perfil antigo de
`data/webview_profile/` na primeira execução, sem apagar o original.
Na guia **Vídeo**, use **Abrir link a partir de uma URL...**, cole o link e
pressione **Abrir vídeo**. A rede é selecionada automaticamente e o vídeo abre
no mesmo perfil, aproveitando o login salvo. Links curtos `vm.tiktok.com`,
`vt.tiktok.com` e `tiktok.com/t/` também são aceitos. Após carregar, o aplicativo
inicia a reprodução; os controles de próximo e anterior continuam disponíveis
quando a página da rede oferece navegação. Se o site pedir login, use F6.

Ele é independente dos perfis existentes. Não é necessário importar cookies.
Feche e reabra o protótipo para conferir se cada site manteve a sessão.
O site ainda pode pedir novo login. Este teste usa Microsoft Edge WebView2 SDK/runtime.

Reprodução, pausa e volume têm botões nativos. Navegação entre vídeos, curtidas,
salvos e comentários ainda usam os controles da própria página. A troca de rede
solicita pausa na anterior. Janelas HTTPS solicitadas pela página abrem na mesma
área; logins que exigem popups separados podem não funcionar neste protótipo.
Valide login nas duas redes, áudio/vídeo, retorno do foco com NVDA, troca de rede
e persistência após reiniciar. A execução sem `--webview` também usa a janela incorporada.

Aplicativo desktop para Windows com interface nativa wxPython acessível ao NVDA. Ele controla uma janela real do Chromium pelo Playwright, usando o perfil persistente `data/browser_profile`.

O aplicativo abre o TikTok, importa cookies JSON, navega pelos vídeos, controla a reprodução, apresenta autor, descrição e comentários, permite curtir e favoritar e copia o link atual. A guia Instagram controla os Reels pela extensão do Chrome ou Brave, com os mesmos atalhos. Os comentários estão disponíveis somente para leitura.

Também existe um modo opcional para usar uma sessão já autenticada no Chrome ou
Brave. Nesse modo, uma extensão local executa as ações na aba do TikTok e devolve
os resultados para esta mesma interface acessível; cookies e senhas não são
copiados para o aplicativo.

## Requisitos

- Windows 10 ou 11;
- Python 3.13 ou uma versão compatível mais recente;
- acesso à internet para instalar as dependências e abrir o TikTok.

## Instalação no Windows

No PowerShell, dentro da pasta do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

No Prompt de Comando (`cmd.exe`), a ativação pode ser feita exatamente assim:

```cmd
.venv\scripts\activate
```

Se a política do PowerShell impedir a ativação, execute uma vez na sessão:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Execução

```powershell
.\.venv\Scripts\python.exe main.py
```

## Modo atual: janela única, sem extensão

O aplicativo agora abre TikTok e Instagram dentro da própria janela usando
Microsoft Edge WebView2. A extensão do navegador e as pontes locais não são mais
necessárias. Execute `python main.py`, escolha a plataforma e aguarde o carregamento.
Faça login uma vez na página incorporada; a sessão fica em
`%LOCALAPPDATA%\Accessible Reels\webview_profile`, tanto ao executar pelo código
quanto ao usar a versão instalada. Use F1 para a lista de atalhos e F6 para alternar
entre a página e os controles acessíveis. O painel **Player**
mantém autor e descrição juntos em uma única caixa somente leitura. A reprodução é
controlada pelos atalhos; comentários e pesquisa abrem como telas secundárias, sem
abas permanentes. Os menus **Plataforma**, **Player** e **Ações** servem para
descobrir os comandos e os atalhos continuam sendo o caminho rápido. A plataforma
pode pedir login novamente quando invalidar a sessão.

## Compatibilidade histórica da extensão

As instruções abaixo descrevem a arquitetura anterior e não fazem parte do fluxo
atual. A pasta da extensão foi removida do aplicativo.

1. Abra `chrome://extensions` no Chrome ou `brave://extensions` no Brave.
2. Ative o **Modo do desenvolvedor**.
3. Escolha **Carregar sem compactação** e selecione a pasta
   `browser_extension` deste projeto.
4. Recarregue qualquer aba do TikTok ou Instagram que já estava aberta.
5. No Accessible Reels, em **Modo do navegador**, escolha
   **Chrome ou Brave com extensão** e pressione **Conectar à aba do TikTok**.
6. Continue usando os botões e atalhos normalmente. Os atalhos de vídeo também
   funcionam quando o foco está na página do TikTok no Chrome ou Brave.

Com a opção de janela minimizada desmarcada, o modo local não abre outro navegador
nem outra aba: ele mantém e controla a aba já autenticada. Depois de atualizar os
arquivos da extensão, pressione
**Recarregar** no cartão da extensão e recarregue também a aba do TikTok.
Quando a comunicação estiver ativa, o ícone da extensão exibirá o indicador
verde **ON** e o nome acessível informará “interface conectada”.

Se a interface disser que a extensão não respondeu, pressione uma vez o ícone
**Accessible Reels** na barra do navegador. Ele abre ou ativa uma aba do TikTok,
o que também desperta a extensão; depois pressione **Conectar à aba do TikTok**
novamente.

Se **Abrir TikTok em janela minimizada exclusiva** estiver marcado, a extensão
primeiro procura uma aba do TikTok que já esteja aberta e reutiliza a aba ativa ou
acessada mais recentemente, minimizando sua janela. Uma nova janela só é criada
quando não existe nenhuma aba do TikTok. A janela minimizada continua aparecendo
na barra de tarefas, pois extensões não podem criar janelas de navegador
completamente invisíveis.

Ao usar **Desconectar navegador local**, a aba do TikTok permanece aberta. Ao
fechar o Accessible Reels pelo botão Sair, pelo atalho ou pelo X, a extensão fecha
somente a aba do TikTok que estava sendo controlada; as demais abas e o Chrome ou
Brave permanecem abertos. As pontes aceitam conexões somente no endereço local `127.0.0.1`; a extensão
tem permissão para páginas do TikTok e Instagram e para essas pontes locais. Se Chrome e
Brave estiverem abertos ao mesmo tempo com a extensão instalada, use somente um
deles durante a sessão para evitar que os dois tentem receber o mesmo comando.

A extensão também solicita a permissão **Depurador**. Ela é usada apenas durante
o instante de cada clique para o navegador produzir uma interação real, aceita
pelo TikTok; a conexão é removida logo após o clique. O aplicativo não abre o
DevTools, não lê cookies e não envia dados para servidores próprios.

Para voltar ao comportamento original, desconecte o navegador local e selecione
**Chromium integrado**. A importação de cookies permanece disponível apenas nesse
modo.

## Instagram pela extensão

1. Atualize a extensão para a versão **1.3.1**: em `chrome://extensions` ou
   `brave://extensions`, localize **Accessible Reels — ponte local** e pressione
   **Recarregar**. Se solicitado, permita o acesso ao Instagram.
2. Recarregue também a aba do Instagram. Abra os **Reels** e faça login no próprio
   navegador, se necessário.
3. Reinicie o aplicativo, selecione a guia **Instagram** e pressione Enter para
   acessar **Conectar Instagram** (`Alt+I`). A conexão reutiliza uma aba existente;
   se não encontrar nenhuma, abre o Instagram.
4. Use `F5` para atualizar autor e descrição. Os atalhos de reprodução, volume,
   navegação, comentários, curtida, copiar link e pesquisa são os mesmos do TikTok.
   No Instagram, `F` salva ou remove o Reel dos salvos.

O Instagram também oferece **Chromium integrado** no seletor de navegador da guia.
Nesse modo, use **Abrir Instagram** (`Alt+G`) para fazer login ou **Importar cookies
do Instagram** (`Alt+I`) para selecionar um arquivo JSON ou Netscape cookies.txt.
Somente cookies do domínio Instagram são importados; o arquivo original não é alterado.
O perfil persistente fica em `data/instagram_profile`, separado do TikTok, e o volume
fica em `data/instagram_preferences.json`. A aceitação da sessão depende do Instagram;
se solicitado, complete o login no navegador. Fechar navegador encerra esse Chromium.
Os controles de Reels e os passos de volume de 5% funcionam nos dois modos.

O modo Chrome ou Brave com extensão continua selecionado por padrão. A janela fica visível
por padrão para permitir login; a opção de minimizá-la pode ser marcada antes
de conectar. Ao reutilizar uma aba, essa opção minimiza a janela que a contém.

Cada guia mantém seus próprios campos, conexão e preferências de volume. Os
atalhos da interface são enviados apenas à plataforma selecionada. Resultados
que chegam após uma troca de guia aguardam o retorno à guia correspondente.
Os atalhos de vídeo também funcionam na página do Instagram e não interceptam
a digitação nos campos de comentário ou pesquisa.

No TikTok e no Instagram, aumentar ou diminuir volume usa passos de **5 pontos percentuais**.
Se o vídeo estiver silenciado ou com volume zero, o primeiro aumento define **5%**
e desativa o mudo; os seguintes passam para 10%, 15% e assim por diante. Diminuir
partindo do silêncio mantém o volume em zero. A preferência continua sendo salva
e aplicada aos próximos vídeos.

`Alt+E` na interface abre a pesquisa acessível do Instagram, com até 50 Reels ou
posts carregados. Quando o Instagram não oferece uma descrição na miniatura,
o resultado recebe um número; abra-o e use `Alt+A` e `Alt+D` para ler os detalhes.
A navegação anterior/próximo requer o feed **Reels**; posts de foto e páginas
sem vídeo não respondem aos comandos de reprodução. No navegador, `Alt+E` abre
a pesquisa do próprio Instagram.

Comentários são lidos do painel do Reel atual. A publicação e as respostas estão
temporariamente desativadas; a interface apresenta somente a lista e os detalhes
em modo de leitura.

**Fechar conexão do Instagram** (`Alt+F`) desconecta sem fechar a aba. Sair do
aplicativo fecha somente as abas controladas pelas conexões ainda ativas. TikTok
e Instagram utilizam as portas locais 43119 e 43120, respectivamente; uma conexão
pode ser encerrada sem interromper a outra.

O perfil do navegador é criado automaticamente em `data/browser_profile`. Para importar uma sessão, use um `.json` contendo uma lista de cookies ou um `.txt` no formato Netscape; arquivos `.txt` contendo JSON também continuam aceitos. O arquivo escolhido não é alterado, movido ou removido.

Arquivos `.txt` no formato Netscape `cookies.txt` também são aceitos diretamente; não é necessário convertê-los para JSON. Linhas `#HttpOnly_` são importadas como cookies HttpOnly. Antes de cada importação, o aplicativo remove do contexto persistente somente os cookies TikTok antigos, adiciona o novo conjunto e confere os cookies no contexto antes e depois de abrir o site.

### Exportar e importar uma nova sessão

1. No navegador em que a extensão Get cookies.txt está instalada, abra `https://www.tiktok.com/` e faça login normalmente.
2. Recarregue o site e confirme no próprio navegador que a conta continua conectada.
3. Exporte os cookies do domínio TikTok no formato Netscape `cookies.txt`, incluindo subdomínios quando a extensão oferecer essa opção.
4. Não encerre a sessão nem use a opção “Sair” do TikTok depois da exportação, pois isso pode invalidar os cookies no servidor.
5. No Accessible Reels, escolha “Importar cookies” e selecione diretamente o `.txt` exportado. Não edite nem converta o arquivo.
6. Aguarde o status começar com “Cookies verificados e TikTok recarregado”. O restante da mensagem informa somente contagens, motivos de linhas ignoradas e domínios normalizados.

Se nenhum cookie TikTok for encontrado, nenhum cookie aparecer no contexto ou os cookies desaparecerem após a navegação, a importação falhará sem anunciar valores ou nomes. Cookies expirados, revogados pelo logout ou invalidados pelo TikTok precisam ser exportados novamente a partir de uma sessão ativa.

## Atalhos e acessibilidade

O aplicativo possui as guias **TikTok** e **Instagram**. A guia TikTok contém os
controles existentes; a guia Instagram contém os controles dos Reels, com Chromium integrado ou extensão.
Trocar de guia mantém as sessões abertas.

- Com o foco nos títulos das guias, as setas alternam entre elas;
- `Tab` ou `Enter` acessa os controles da guia selecionada;
- `Ctrl+Tab` e `Ctrl+Shift+Tab` trocam de guia a partir dos controles;
- Dentro de cada guia, `Tab` e `Shift+Tab` percorrem os controles normalmente.

Os comandos controlam a plataforma da guia selecionada.
O botão Sair e `Alt+S` estão disponíveis nas duas guias.

Os controles com atalhos informam separadamente o nome, o tipo nativo e a tecla
à acessibilidade do Windows. Assim, o NVDA pode anunciar, por exemplo,
“Curtir ou descurtir, botão, Alt+L” e “Próximo vídeo, botão, Alt+Seta para baixo”.
A palavra “botão” não faz parte dos rótulos. A ordem da fala e o anúncio das
teclas dependem das configurações do leitor de tela. Esse comportamento também
se aplica às opções de janela minimizada e aos controles de pesquisa e comentários.

No modo de extensão do TikTok, **Conectar ao TikTok** continua usando `Alt+T`,
e **Fechar conexão do navegador** usa `Alt+F`.

- `Alt+T`: Abrir TikTok;
- `Alt+I`: importar cookies no TikTok; conectar Instagram na guia Instagram;
- `Alt+Seta para baixo`: próximo vídeo;
- `Alt+Seta para cima`: vídeo anterior;
- `Alt+P`: reproduzir ou pausar;
- `Alt+A`: ler autor;
- `Alt+D`: ler descrição;
- `Alt+C`: copiar link;
- `Alt+Shift+C`: abrir os comentários nativos do vídeo atual;
- `Alt+L`: curtir ou descurtir o vídeo atual;
- `Alt+F`: favoritar ou desfavoritar no TikTok; salvar ou remover dos salvos no Instagram;
- `Esc`: voltar dos comentários ao player;
- `F5`: atualizar autor e descrição;
- `Alt+Shift+Seta para cima`: aumentar o volume em 5 pontos percentuais;
- `Alt+Shift+Seta para baixo`: diminuir o volume em 5 pontos percentuais;
- `Alt+E`: abrir a pesquisa de vídeos;
- `Alt+Shift+M`: ativar ou desativar o mudo;
- `Alt+F12`: anunciar diagnóstico seguro da página e do último comando;
- `Alt+F`: fechar navegador/conexão da plataforma;
- `Shift+<`: diminuir a velocidade do video;
- `Shift+>`: aumentar a velocidade do video;
- `Alt+S`: Sair;
- `Tab` e `Shift+Tab`: percorrer os controles em ordem.

## Logs para suporte

O aplicativo registra localmente inicialização, comandos, falhas de carregamento e erros inesperados em `%LOCALAPPDATA%\\Accessible Reels\\logs\\accessible-reels.log`. No menu **Ajuda**, escolha **Abrir pasta de logs para suporte** e envie esse arquivo ao suporte quando solicitado. Os arquivos são rotativos (até quatro arquivos de 1 MB) e não registram cookies, tokens, parâmetros de URL, descrições nem comentários.

Os comentários são carregados da plataforma e o painel web é fechado em seguida. A tela nativa é somente leitura: use as setas para escolher um comentário e `Tab` para acessar seus detalhes completos. A publicação e as respostas estão temporariamente desativadas.

O foco inicial fica no seletor de guias, com TikTok selecionado. Use as setas no seletor ou Ctrl+Tab (Ctrl+Shift+Tab para voltar) para trocar de plataforma. Tab acessa Abrir/Conectar e percorre as opções da guia selecionada; Shift+Tab retorna pelos controles. Enter no seletor também acessa Abrir/Conectar. Autor e descrição aparecem em campos nativos somente para leitura, sem receber foco automaticamente. Operações do Chromium são executadas fora da thread da interface, e mudanças importantes aparecem no texto de status acessível.

O volume escolhido é mantido e salvo pela extensão: novos elementos `video`,
recargas da aba e redefinições feitas durante o carregamento recebem a preferência
antes da reprodução. O estado de mudo continua independente do nível de volume.

Na pesquisa, digite um termo e pressione Enter ou o botão **Pesquisar**. A lista
mostra até 50 vídeos; pressione Enter no botão **Abrir vídeo** ou dê duplo clique
em um resultado. Depois de abrir o vídeo escolhido, use `Alt+Seta para baixo` e
`Alt+Seta para cima` para percorrer os vídeos seguintes e anteriores.

A opção “Mostrar janela do navegador” permanece marcada e desabilitada nesta versão. O ocultamento está temporariamente desativado para preservar reprodução, autenticação e o funcionamento básico enquanto a regressão é validada manualmente. O Chromium continua em modo headed e nenhuma chamada a `ShowWindow(..., SW_HIDE)` é feita pelo fluxo do aplicativo.

Todos os atalhos de vídeo estão registrados explicitamente em uma única `AcceleratorTable` da janela principal e chegam por `EVT_MENU`, independentemente do controle interno com foco. Quando reconhecidos, o status anuncia “Comando recebido” antes de enviá-los à fila do navegador. Combinações não registradas continuam para o processamento normal dos controles.

## Testes

Os testes usam cookies fictícios e páginas Playwright falsas; não acessam a internet:

```powershell
python -m pytest tests -q -p no:cacheprovider
node --test tests/test_extension_routing.cjs
```

## Teste manual com NVDA

1. Inicie o NVDA e execute `python main.py` com o ambiente virtual ativado.
2. Confirme que o foco inicial está nas guias e que TikTok está selecionado. Use a seta para selecionar Instagram e confira o anúncio da guia. Pressione Tab para acessar Conectar Instagram.
3. Use `Ctrl+Tab` para voltar ao TikTok e Enter para acessar “Abrir TikTok”. Percorra os controles com `Tab`. Confira também `Shift+Tab`, `Ctrl+Shift+Tab`, a troca de guias com as setas e o botão Sair nas duas guias.
4. Abra o TikTok e confirme que o Chromium permanece visível. O status deve anunciar “Ocultamento temporariamente desativado para preservar a reprodução.” A caixa correspondente deve estar marcada e desabilitada.
5. Pressione `F5`. Autor e descrição devem ser preenchidos sem mudança automática do foco.
6. Use `Alt+A` e `Alt+D`. O status deve anunciar o autor e a descrição.
7. Com o foco em diferentes controles da janela wxPython, use `Alt+Seta para baixo` e `Alt+Seta para cima`. Primeiro deve ser anunciado “Comando recebido”; depois, a conclusão da troca do vídeo.
8. Ainda sem focar o Chromium, use `Alt+P` duas vezes e confirme os anúncios de vídeo pausado e reproduzindo. Se o Chromium bloquear o primeiro `play()`, o status deve pedir uma interação inicial explicitamente.
9. Use `Alt+C`, cole em um editor de texto e confirme que foi copiado um endereço no formato `https://www.tiktok.com/@usuario/video/ID`, sem parâmetros. Se o vídeo não puder ser identificado, confirme que a área de transferência anterior foi preservada.
10. Use `Alt+Shift+Seta para cima` e `Alt+Shift+Seta para baixo`, conferindo anúncios em passos de 5% e os limites de 0% e 100%. Troque de vídeo e confirme que o volume foi reaplicado. Use `Alt+Shift+M` duas vezes e confira “Som desativado” e “Som ativado”.
11. Use `Alt+F12` e confira página conectada, URL sem parâmetros, quantidade de vídeos, vídeo ativo, reprodução, volume e os últimos comandos/falha. O diagnóstico não deve conter cookies ou tokens.
12. Feche o navegador e abra-o novamente. Por fim, use `Alt+S` e depois teste o X em outra execução, verificando no Gerenciador de Tarefas que não restou processo Chromium iniciado pelo aplicativo.

13. Na guia Instagram, conecte à extensão atualizada e teste `F5`, `Alt+A`, `Alt+D`,
    `Alt+C`, reprodução, volume e navegação. Confirme que os campos do TikTok não
    mudam. Abra comentários com `C` e confira que a janela identifica Instagram.
14. Com as duas conexões ativas, alterne as guias durante um comando, desconecte
    uma plataforma e confirme que a outra continua funcionando. Ao sair, confira
    que outras abas do navegador permanecem abertas.

Os testes automatizados usam HTML fictício e mocks. Os seletores de leitura do
Instagram foram também conferidos em uma sessão real, mas ações de publicação,
curtida e salvar foram testadas apenas em páginas fictícias. A leitura pelo NVDA
e o fluxo completo da extensão atualizada precisam de validação manual. Mudanças
na estrutura de qualquer plataforma podem exigir atualização dos seletores.

## Privacidade

Valores de cookies e tokens não são exibidos nem registrados. Arquivos `cookies*.json`, `cookies*.txt` e o perfil persistente são ignorados pelo Git. Ainda assim, trate o arquivo exportado como um segredo e armazene-o em local seguro.
