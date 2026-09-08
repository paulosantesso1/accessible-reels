param([string]$PythonExe = ".\.venv\Scripts\python.exe", [string]$AppVersion = "0.1.0")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
if (Test-Path -LiteralPath $PythonExe) {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
} elseif (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python do ambiente virtual não encontrado: $PythonExe"
}

& $PythonExe -m pip install --upgrade pip pyinstaller
& $PythonExe -m pip install -r requirements.txt
& $PythonExe -m PyInstaller --noconfirm --clean --windowed --name "Accessible Reels" --collect-all accessible_output2 main.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável." }

$webViewBootstrapper = "dist\MicrosoftEdgeWebView2Setup.exe"
Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $webViewBootstrapper
$signature = Get-AuthenticodeSignature -FilePath $webViewBootstrapper
if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notlike "*CN=Microsoft Corporation*") {
    throw "O bootstrapper do Microsoft Edge WebView2 não possui uma assinatura Microsoft válida."
}

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado. Instale-o para gerar o instalador." }
& $iscc "/DAppVersion=$AppVersion" "installer\accessible-reels.iss"
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador." }
$setup = "dist\Accessible-Reels-Setup.exe"
$hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$setup.sha256" -Value "$hash  Accessible-Reels-Setup.exe" -Encoding ascii
