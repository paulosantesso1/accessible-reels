import json
import re

from app_version import APP_VERSION
from release_notes import (changelog_path, has_seen_current_release, load_release_history,
                           mark_current_release_seen)


def test_committed_changelog_starts_with_the_application_version():
    markdown = changelog_path().read_text(encoding="utf-8")
    first_release = re.search(r"^##\s+(\d+(?:\.\d+)*)(?:\s|$)", markdown, re.MULTILINE)
    assert first_release is not None, "CHANGELOG.md não contém uma seção de versão"
    assert first_release.group(1) == APP_VERSION, (
        f"A primeira versão do CHANGELOG.md ({first_release.group(1)}) "
        f"difere de APP_VERSION ({APP_VERSION})"
    )


def test_release_history_keeps_current_and_previous_versions(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Histórico\n\n"
        f"## {APP_VERSION} — hoje\n\n- Atalho `global`.\n\n"
        "## 1.0.9 — ontem\n\n- Novidade anterior.\n",
        encoding="utf-8",
    )

    notes = load_release_history(changelog)

    assert f"{APP_VERSION} — hoje" in notes
    assert "• Atalho global." in notes
    assert "1.0.9 — ontem" in notes
    assert "• Novidade anterior." in notes
    assert "#" not in notes
    assert "`" not in notes


def test_release_history_requires_the_current_version(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## 0.0.1\n\n- Antiga.\n", encoding="utf-8")

    try:
        load_release_history(changelog)
    except OSError as error:
        assert APP_VERSION in str(error)
    else:
        raise AssertionError("A versão atual ausente deveria falhar")


def test_seen_release_marker_is_specific_to_the_current_version(tmp_path):
    marker = tmp_path / "release-notes.json"
    assert not has_seen_current_release(marker)
    mark_current_release_seen(marker)
    assert has_seen_current_release(marker)
    assert json.loads(marker.read_text(encoding="utf-8"))["last_seen_version"] == APP_VERSION
