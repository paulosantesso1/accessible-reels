"""Exercise the build's version checks without compiling an installer."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason='PowerShell is required')


@pytest.mark.parametrize('requested', ['', '1.3.0'])
def test_build_uses_the_application_version(tmp_path, requested):
    result = run_version_checks(tmp_path, '1.3.0', requested)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '1.3.0'


@pytest.mark.parametrize('requested', ['1.0.7', '1.3.1', 'invalid'])
def test_build_rejects_a_different_installer_version(tmp_path, requested):
    result = run_version_checks(tmp_path, '1.3.0', requested)
    assert result.returncode != 0
    assert 'APP_VERSION (1.3.0)' in result.stderr


@pytest.mark.parametrize('source', ['', '1.3.0alpha', '1.2.3.4.5'])
def test_build_rejects_an_invalid_application_version(tmp_path, source):
    result = run_version_checks(tmp_path, source, '')
    assert result.returncode != 0
    assert 'APP_VERSION' in result.stderr


def run_version_checks(tmp_path, source, requested):
    build = (ROOT / 'scripts/build_windows_release.ps1').read_text(encoding='utf-8-sig')
    # Run the actual preflight, stopping before pip or any packaging operation.
    preflight, separator, _ = build.partition('& $PythonExe -m pip install')
    assert separator, 'Could not locate the first build operation'
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'check-version.ps1'
    script.write_text(preflight + '\nWrite-Output $AppVersion\n', encoding='utf-8-sig')
    (tmp_path / 'app_version.py').write_text(f'APP_VERSION = {source!r}\n', encoding='utf-8')
    command = [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
               '-File', str(script), '-PythonExe', sys.executable]
    if requested:
        command += ['-AppVersion', requested]
    return subprocess.run(command, capture_output=True, text=True, timeout=30)
