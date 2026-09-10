import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_lock_is_consistent():
    lock = json.loads((ROOT / 'webview2-runtime.json').read_text())
    assert f".{lock['version']}.{lock['architecture']}.cab" in lock['url']
    assert len(bytes.fromhex(lock['sha256'])) == 32


def test_installer_does_not_launch_an_online_runtime_installer():
    installer = (ROOT / 'installer/accessible-reels.iss').read_text(encoding='utf-8')
    assert 'MicrosoftEdgeWebView2Setup' not in installer
    assert 'S-1-15-2-2' in installer
    assert 'S-1-15-2-1' in installer


def test_release_build_verifies_embedded_web_scripts():
    build = (ROOT / 'scripts' / 'build_windows_release.ps1').read_text(encoding='utf-8')
    assert 'scripts\\verify_web_scripts.py' in build


def test_release_build_embeds_external_ytdlp_executable():
    build = (ROOT / 'scripts' / 'build_windows_release.ps1').read_text(encoding='utf-8')
    assert "Join-Path $root 'yt-dlp.exe'" in build
    assert '--add-binary "$ytDlp;."' in build
    assert "dist\\Accessible Reels\\yt-dlp.exe" in build
    assert '--collect-all yt_dlp' not in build
