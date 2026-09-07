from pathlib import Path

from ui.app_frame import webview_profile_path


def test_profile_is_shared_by_source_and_installed_runs(tmp_path):
    local = tmp_path / "local"
    source = tmp_path / "source"

    assert webview_profile_path(local_app_data=local, frozen=False, source_root=source) == \
        local / "Accessible Reels" / "webview_profile"
    assert webview_profile_path(local_app_data=local, frozen=True, source_root=source) == \
        local / "Accessible Reels" / "webview_profile"


def test_legacy_source_profile_is_migrated_without_removing_it(tmp_path):
    local = tmp_path / "local"
    source = tmp_path / "source"
    legacy = source / "data" / "webview_profile"
    legacy.mkdir(parents=True)
    (legacy / "session-marker").write_text("saved", encoding="utf-8")

    profile = webview_profile_path(local_app_data=local, frozen=False, source_root=source)

    assert (profile / "session-marker").read_text(encoding="utf-8") == "saved"
    assert (legacy / "session-marker").read_text(encoding="utf-8") == "saved"
