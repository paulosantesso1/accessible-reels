import json
import os
import pytest
from webview_runtime import configure_runtime


def prepare(root):
    (root / 'webview2-runtime.json').write_text(json.dumps({'version': '1.2.3.4', 'architecture': 'x64'}))
    folder = root / 'runtime' / '1.2.3.4'
    folder.mkdir(parents=True)
    (folder / 'msedgewebview2.exe').touch()
    return folder


def test_frozen_uses_own_runtime(tmp_path, monkeypatch):
    folder = prepare(tmp_path)
    monkeypatch.setenv('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER', 'wrong-folder')
    assert configure_runtime(root=tmp_path, frozen=True) == folder
    assert os.environ['WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'] == str(folder)


def test_missing_bundle_does_not_fall_back(tmp_path):
    folder = prepare(tmp_path)
    (folder / 'msedgewebview2.exe').unlink()
    with pytest.raises(RuntimeError, match='ausente'):
        configure_runtime(root=tmp_path, frozen=True)


def test_source_without_bundle_keeps_system_mode(tmp_path):
    assert configure_runtime(root=tmp_path, frozen=False) is None
