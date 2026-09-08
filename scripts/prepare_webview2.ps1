param([string]$Destination = "dist\Accessible Reels")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$lock = Get-Content -Raw (Join-Path $root 'webview2-runtime.json') | ConvertFrom-Json
$cache = Join-Path $root '.runtime-cache'
New-Item -ItemType Directory -Force $cache | Out-Null
$cab = Join-Path $cache 'webview2.cab'
if (!(Test-Path $cab) -or (Get-FileHash $cab -Algorithm SHA256).Hash -ne $lock.sha256) {
    Invoke-WebRequest -Uri $lock.url -OutFile $cab
}
if ((Get-FileHash $cab -Algorithm SHA256).Hash -ne $lock.sha256) {
    throw 'O SHA256 do runtime difere da versão fixada.'
}
$extract = Join-Path $cache $lock.version
New-Item -ItemType Directory -Force $extract | Out-Null
& expand.exe $cab '-F:*' $extract | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Falha ao extrair o runtime.' }
$executables = @(Get-ChildItem $extract -Filter msedgewebview2.exe -Recurse)
if ($executables.Count -ne 1) { throw 'Estrutura inesperada no pacote do runtime.' }
$exe = $executables[0]
$signature = Get-AuthenticodeSignature $exe.FullName
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*CN=Microsoft Corporation*') {
    throw 'O runtime não possui uma assinatura Microsoft válida.'
}
if ($exe.VersionInfo.ProductVersion -ne $lock.version) { throw 'Versão incorreta do runtime.' }
$bytes = [System.IO.File]::ReadAllBytes($exe.FullName)
$pe = [BitConverter]::ToInt32($bytes, 60)
if ([BitConverter]::ToUInt16($bytes, $pe + 4) -ne 0x8664) { throw 'Runtime não é x64.' }
$target = Join-Path $Destination "runtime\$($lock.version)"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item -Path (Join-Path $exe.DirectoryName '*') -Destination $target -Recurse -Force
Copy-Item (Join-Path $root 'webview2-runtime.json') $Destination -Force
