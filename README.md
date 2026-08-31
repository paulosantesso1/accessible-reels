# Accessible Reels — segunda etapa

Aplicativo desktop para Windows com interface nativa wxPython acessível ao NVDA. Ele controla uma janela real do Chromium pelo Playwright, usando o perfil persistente `data/browser_profile`.

O aplicativo abre o TikTok, importa cookies JSON, navega pelos vídeos, controla a reprodução, apresenta autor, descrição e comentários, permite curtir e favoritar e copia o link atual. A publicação de comentários exige confirmação explícita no botão Publicar.

Também existe um modo opcional para usar uma sessão já autenticada no Chrome ou
Brave. Nesse modo, uma extensão local executa as ações na aba do TikTok e devolve
os resultados para esta mesma interface acessível; cookies e senhas não são
copiados para o aplicativo.

## Requisitos

- Windows 10 ou 11;
- Python 3.11 (uma versão compatível também pode funcionar);
- acesso à internet para instalar as dependências e abrir o TikTok.

## Instalação no Windows

No PowerShell, dentro da pasta do projeto:

```powershell
py -3.11 -m venv .venv
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
python main.py
```

## Usar a sessão do Chrome ou Brave

1. Abra `chrome://extensions` no Chrome ou `brave://extensions` no Brave.
2. Ative o **Modo do desenvolvedor**.
3. Escolha **Carregar sem compactação** e selecione a pasta
   `browser_extension` deste projeto.
4. Recarregue qualquer aba do TikTok que já estava aberta.
5. No Accessible Reels, em **Modo do navegador**, escolha
   **Chrome ou Brave com extensão** e pressione **Conectar à aba do TikTok**.
6. Continue usando os botões e atalhos da interface normalmente.

Com a opção de janela minimizada desmarcada, o modo local não abre outro navegador
nem outra aba: ele mantém e controla a aba já autenticada. Depois de atualizar os
arquivos da extensão, pressione
**Recarregar** no cartão da extensão e recarregue também a aba do TikTok.
Quando a comunicação estiver ativa, o ícone da extensão exibirá o indicador
verde **ON** e o nome acessível informará “interface conectada”.

Se **Abrir TikTok em janela minimizada exclusiva** estiver marcado, a extensão
cria e reutiliza uma janela separada do Chrome ou Brave, já minimizada e usando a
mesma sessão autenticada. Desmarque a opção antes de conectar para controlar uma
aba que você já abriu. A janela minimizada continua aparecendo na barra de tarefas,
pois extensões não podem criar janelas de navegador completamente invisíveis.

O Chrome ou Brave pode permanecer aberto ao desconectar ou fechar o Accessible
Reels. A ponte aceita conexões somente no endereço local `127.0.0.1`; a extensão
tem permissão somente para páginas do TikTok e para essa ponte local. Se Chrome e
Brave estiverem abertos ao mesmo tempo com a extensão instalada, use somente um
deles durante a sessão para evitar que os dois tentem receber o mesmo comando.

A extensão também solicita a permissão **Depurador**. Ela é usada apenas durante
o instante de cada clique para o navegador produzir uma interação real, aceita
pelo TikTok; a conexão é removida logo após o clique. O aplicativo não abre o
DevTools, não lê cookies e não envia dados para servidores próprios.

Para voltar ao comportamento original, desconecte o navegador local e selecione
**Chromium integrado**. A importação de cookies permanece disponível apenas nesse
modo.

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

- `Alt+T`: Abrir TikTok;
- `Alt+I`: Importar cookies;
- `Alt+Seta para baixo`: próximo vídeo;
- `Alt+Seta para cima`: vídeo anterior;
- `Alt+P`: reproduzir ou pausar;
- `Alt+A`: ler autor;
- `Alt+D`: ler descrição;
- `Alt+C`: copiar link;
- `C`: abrir a janela de comentários do vídeo atual;
- `L`: curtir ou descurtir o vídeo atual;
- `F`: favoritar ou desfavoritar o vídeo atual;
- `Esc`: fechar a janela de comentários;
- `F5`: atualizar autor e descrição;
- `Alt+Shift+Seta para cima`: aumentar o volume em 10%;
- `Alt+Shift+Seta para baixo`: diminuir o volume em 10%;
- `Alt+Shift+M`: ativar ou desativar o mudo;
- `Alt+F12`: anunciar diagnóstico seguro da página e do último comando;
- `Alt+F`: Fechar navegador;
- `Alt+S`: Sair;
- `Tab` e `Shift+Tab`: percorrer os controles em ordem.

Na janela de comentários, o foco começa na lista somente para leitura. Use as setas para ler, `Tab` para chegar a “Escrever comentário” e depois ao botão Fechar. O texto somente é enviado ao TikTok quando o botão Publicar é confirmado.

O foco inicial fica em “Abrir TikTok”. Autor e descrição aparecem em campos nativos somente para leitura, sem receber foco automaticamente. Operações do Chromium são executadas fora da thread da interface, e mudanças importantes aparecem no texto de status acessível.

O volume escolhido é mantido na página: novos elementos `video` e redefinições feitas durante o carregamento recebem novamente a preferência armazenada. O estado de mudo continua independente do nível de volume.

A opção “Mostrar janela do navegador” permanece marcada e desabilitada nesta versão. O ocultamento está temporariamente desativado para preservar reprodução, autenticação e o funcionamento básico enquanto a regressão é validada manualmente. O Chromium continua em modo headed e nenhuma chamada a `ShowWindow(..., SW_HIDE)` é feita pelo fluxo do aplicativo.

Todos os atalhos de vídeo estão registrados explicitamente em uma única `AcceleratorTable` da janela principal e chegam por `EVT_MENU`, independentemente do controle interno com foco. Quando reconhecidos, o status anuncia “Comando recebido” antes de enviá-los à fila do navegador. Combinações não registradas continuam para o processamento normal dos controles.

## Testes

Os testes usam cookies fictícios e páginas Playwright falsas; não acessam a internet:

```powershell
python -m pytest
```

## Teste manual com NVDA

1. Inicie o NVDA e execute `python main.py` com o ambiente virtual ativado.
2. Confirme que o foco inicial é anunciado como “Abrir TikTok”.
3. Percorra a janela com `Tab` e confira a ordem: abrir, importar, mostrar janela do navegador, autor, descrição, controles de vídeo e volume, fechar navegador e sair.
4. Abra o TikTok e confirme que o Chromium permanece visível. O status deve anunciar “Ocultamento temporariamente desativado para preservar a reprodução.” A caixa correspondente deve estar marcada e desabilitada.
5. Pressione `F5`. Autor e descrição devem ser preenchidos sem mudança automática do foco.
6. Use `Alt+A` e `Alt+D`. O status deve anunciar o autor e a descrição.
7. Com o foco em diferentes controles da janela wxPython, use `Alt+Seta para baixo` e `Alt+Seta para cima`. Primeiro deve ser anunciado “Comando recebido”; depois, a conclusão da troca do vídeo.
8. Ainda sem focar o Chromium, use `Alt+P` duas vezes e confirme os anúncios de vídeo pausado e reproduzindo. Se o Chromium bloquear o primeiro `play()`, o status deve pedir uma interação inicial explicitamente.
9. Use `Alt+C`, cole em um editor de texto e confirme que foi copiado um endereço no formato `https://www.tiktok.com/@usuario/video/ID`, sem parâmetros. Se o vídeo não puder ser identificado, confirme que a área de transferência anterior foi preservada.
10. Use `Alt+Shift+Seta para cima` e `Alt+Shift+Seta para baixo`, conferindo anúncios em passos de 10% e os limites de 0% e 100%. Troque de vídeo e confirme que o volume foi reaplicado. Use `Alt+Shift+M` duas vezes e confira “Som desativado” e “Som ativado”.
11. Use `Alt+F12` e confira página conectada, URL sem parâmetros, quantidade de vídeos, vídeo ativo, reprodução, volume e os últimos comandos/falha. O diagnóstico não deve conter cookies ou tokens.
12. Feche o navegador e abra-o novamente. Por fim, use `Alt+S` e depois teste o X em outra execução, verificando no Gerenciador de Tarefas que não restou processo Chromium iniciado pelo aplicativo.

Os testes automatizados usam HTML conceitual e mocks e não comprovam os seletores contra o TikTok real. Se o TikTok alterar sua estrutura, o status deve informar uma falha compreensível, e a janela deve continuar respondendo ao teclado.

## Privacidade

Valores de cookies e tokens não são exibidos nem registrados. Arquivos `cookies*.json`, `cookies*.txt` e o perfil persistente são ignorados pelo Git. Ainda assim, trate o arquivo exportado como um segredo e armazene-o em local seguro.
