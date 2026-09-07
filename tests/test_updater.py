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
