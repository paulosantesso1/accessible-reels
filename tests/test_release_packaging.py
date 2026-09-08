from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_release_packages_the_signed_webview2_bootstrapper():
    build_script = (ROOT / 'scripts' / 'build_windows_release.ps1').read_text(encoding='utf-8')
    installer = (ROOT / 'installer' / 'accessible-reels.iss').read_text(encoding='utf-8')

    assert 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' in build_script
    assert 'Get-AuthenticodeSignature' in build_script
    assert 'MicrosoftEdgeWebView2Setup.exe' in installer
    assert 'Parameters: "/silent /install"' in installer
    assert 'function NeedsWebView2Runtime()' in installer
