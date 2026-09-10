param([string]$PythonExe = ".\.venv\Scripts\python.exe", [string]$AppVersion = "1.0.7")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if (Test-Path -LiteralPath $PythonExe) {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
} elseif (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python do ambiente virtual não encontrado: $PythonExe"
}

& $PythonExe -m pip install --upgrade pip pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar ferramentas de build." }
& $PythonExe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências." }
$architecture = & $PythonExe -c "import platform; print(platform.machine())"
if ($architecture -ne "AMD64") { throw "O build requer Python x64." }
$loader = & $PythonExe -c "import wx; from pathlib import Path; print(Path(wx.__file__).parent / 'WebView2Loader.dll')"
if (!(Test-Path -LiteralPath $loader)) { throw "WebView2Loader.dll ausente no wxPython." }
$ytDlp = Join-Path $root 'yt-dlp.exe'
if (!(Test-Path -LiteralPath $ytDlp -PathType Leaf)) { throw "yt-dlp.exe ausente na raiz do projeto." }
& $PythonExe -m PyInstaller --noconfirm --clean --windowed --name "Accessible Reels" --collect-all accessible_output2 --add-binary "$loader;." --add-binary "$ytDlp;." --add-data "ui\web_scripts;ui\web_scripts" main.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável." }
& $PythonExe scripts\verify_web_scripts.py
if (!(Test-Path -LiteralPath 'dist\Accessible Reels\yt-dlp.exe' -PathType Leaf)) { throw "yt-dlp.exe ausente no pacote gerado." }
if ($LASTEXITCODE -ne 0) { throw "Os scripts WebView não foram empacotados corretamente." }

& "$PSScriptRoot\prepare_webview2.ps1" -Destination "dist\Accessible Reels"

$probe = Start-Process -FilePath (Join-Path $root 'dist\Accessible Reels\Accessible Reels.exe') -ArgumentList '--check-runtime' -WindowStyle Hidden -PassThru
if (!$probe.WaitForExit(30000)) {
    $probe.Kill()
    throw 'O teste do runtime empacotado excedeu 30 segundos.'
}
if ($probe.ExitCode -ne 0) { throw 'O executavel nao conseguiu carregar o runtime empacotado. Consulte os logs.' }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado. Instale-o para gerar o instalador." }
& $iscc "/DAppVersion=$AppVersion" "installer\accessible-reels.iss"
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador." }
$setup = "dist\Accessible-Reels-Setup.exe"
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$setup.sha256" -Value "$hash  Accessible-Reels-Setup.exe" -Encoding ascii
