import pytest

from updater import UpdateError, is_newer_version, release_from_payload


def release_payload(*assets):
    return {"tag_name": "v0.2.0", "body": "Novidades", "assets": list(assets)}


def asset(name):
    return {"name": name, "browser_download_url": f"https://example.test/{name}", "size": 42}


def test_accepts_new_release_with_installer_and_checksum():
    info = release_from_payload(
        release_payload(asset("Accessible-Reels-Setup.exe"), asset("Accessible-Reels-Setup.exe.sha256")),
        current_version="0.1.0",
    )
    assert info and info.latest_version == "0.2.0"


def test_rejects_release_without_checksum():
    with pytest.raises(UpdateError, match="checksum"):
        release_from_payload(
            release_payload(asset("Accessible-Reels-Setup.exe")),
            current_version="0.1.0",
        )


def test_version_comparison_handles_v_prefix():
    assert is_newer_version("v1.0.0", "0.9.9")
    assert not is_newer_version("1.0.0", "1.0.0")


def test_update_prompt_is_offered_once_per_version(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import ui.app_frame as app_frame
    from updater import UpdateInfo

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(app_frame, "can_self_update", lambda: True)
    prompt = Mock(return_value=app_frame.wx.NO)
    monkeypatch.setattr(app_frame.wx, "MessageBox", prompt)
    info = UpdateInfo("1.0.9", "1.0.10", "Changelog", "https://x/s.exe", 1, "https://x/s.sha256")
    frame = SimpleNamespace(_update_checking=True, status=Mock())

    app_frame.MainFrame._finish_update_check(frame, False, info, "")
    assert prompt.call_count == 1 and "Changelog" not in prompt.call_args.args[0]

    app_frame.MainFrame._finish_update_check(frame, False, info, "")  # next launch
    assert prompt.call_count == 1 and "1.0.10" in frame.status.call_args.args[0]

    app_frame.MainFrame._finish_update_check(frame, True, info, "")  # explicit check
    assert prompt.call_count == 2

    newer = UpdateInfo("1.0.9", "1.0.11", "Changelog", "https://x/s.exe", 1, "https://x/s.sha256")
    app_frame.MainFrame._finish_update_check(frame, False, newer, "")
    assert prompt.call_count == 3


def test_whats_new_is_shown_once_after_the_update_is_installed(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import ui.app_frame as app_frame
    from updater import UpdateInfo, remember_whats_new, take_whats_new

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    info = UpdateInfo("1.0.9", "1.0.10", "Corrige o player", "https://x/s.exe", 1, "https://x/s.sha256")
    assert take_whats_new("1.0.9") is None
    remember_whats_new(info)
    assert take_whats_new("1.0.9") is None  # still the old version: install has not happened
    assert take_whats_new("1.0.10") == ("1.0.10", "Corrige o player")
    assert take_whats_new("1.0.10") is None  # never again

    remember_whats_new(info)
    box = Mock()
    monkeypatch.setattr(app_frame.wx, "MessageBox", box)
    monkeypatch.setattr(app_frame, "take_whats_new", lambda: take_whats_new("1.0.10"))
    frame = SimpleNamespace()
    app_frame.MainFrame.show_whats_new(frame)
    app_frame.MainFrame.show_whats_new(frame)
    assert box.call_count == 1 and "Corrige o player" in box.call_args.args[0]


def test_stale_whats_new_for_a_skipped_version_is_discarded(monkeypatch, tmp_path):
    from updater import UpdateInfo, remember_whats_new, take_whats_new

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    remember_whats_new(UpdateInfo("1.0.9", "1.0.10", "x", "u", 1, "c"))
    assert take_whats_new("1.0.11") is None
    assert take_whats_new("1.0.10") is None
