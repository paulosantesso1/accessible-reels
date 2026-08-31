from __future__ import annotations

import json
from pathlib import Path

from tiktok.preferences import VolumePreferences


def test_preferences_store_only_volume():
    path = Path("tests/.preferences-save-test.json")
    try:
        preferences = VolumePreferences(path)
        preferences.save(0.7)
        assert json.loads(path.read_text(encoding="utf-8")) == {"volume": 0.7}
        assert preferences.load() == 0.7
    finally:
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)


def test_invalid_preferences_fall_back_to_full_volume():
    path = Path("tests/.preferences-invalid-test.json")
    try:
        path.write_text('{"volume": "segredo-ou-valor-inválido"}', encoding="utf-8")
        assert VolumePreferences(path).load() == 1.0
    finally:
        path.unlink(missing_ok=True)
