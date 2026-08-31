from __future__ import annotations

import json
from pathlib import Path

from tiktok.video_controls import clamp_volume


class VolumePreferences:
    """Persiste somente o nível de volume, sem estado de conta ou navegação."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> float:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            value = data.get("volume") if isinstance(data, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return 1.0
            return clamp_volume(float(value))
        except (OSError, ValueError, TypeError):
            return 1.0

    def save(self, volume: float) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"volume": clamp_volume(volume)}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self._path)
