"""Histórico de versões e controle da leitura das novidades."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app_version import APP_VERSION


def changelog_path() -> Path:
    return Path(__file__).with_name("CHANGELOG.md")


def seen_notes_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Accessible Reels"
    return root / "release-notes.json"


def _accessible_text(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)]\(([^)]+)\)", r"\1 — \2", markdown)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*-\s+", "• ", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def load_release_history(path: Path | None = None) -> str:
    """Return the complete changelog, with the newest version first."""
    try:
        markdown = (path or changelog_path()).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OSError("O histórico de versões não foi encontrado.") from exc
    if not re.search(rf"^##\s+{re.escape(APP_VERSION)}(?:\s|$)", markdown, re.MULTILINE):
        raise OSError(f"A versão {APP_VERSION} não foi encontrada no histórico.")
    text = _accessible_text(markdown)
    if not text:
        raise OSError("O histórico de versões está vazio.")
    return text


def has_seen_current_release(path: Path | None = None) -> bool:
    try:
        value = json.loads((path or seen_notes_path()).read_text(encoding="utf-8"))
        return value.get("last_seen_version") == APP_VERSION
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def mark_current_release_seen(path: Path | None = None) -> None:
    destination = path or seen_notes_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"last_seen_version": APP_VERSION}), encoding="utf-8")
    temporary.replace(destination)
