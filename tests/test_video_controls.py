from __future__ import annotations

import re

import pytest

from tiktok.video_controls import (
    ACTIVE_VIDEO_SNAPSHOT_SCRIPT,
    NAVIGATION_MARKER_SCRIPT,
    TikTokVideoController,
    TikTokSelectors,
    VideoCandidate,
    VideoControlError,
    _is_action_mutation_response,
    _server_accepted_mutation,
    choose_video_candidate,
    clamp_volume,
    normalize_author,
    normalize_description,
    select_current_url,
    volume_message,
)


class FakeMutationResponse:
    def __init__(self, url: str, *, ok: bool = True, payload=None) -> None:
        self.url = url
        self.ok = ok
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_account_mutation_response_requires_write_endpoint_and_server_success():
    like = FakeMutationResponse(
        "https://www.tiktok.com/api/commit/item/digg/?aweme_id=123",
        payload={"status_code": 0},
    )
    rejected = FakeMutationResponse(
        "https://www.tiktok.com/api/collect/item/", payload={"status_code": 8}
    )
    reading = FakeMutationResponse(
        "https://www.tiktok.com/api/user/collect/item_list/", payload={}
    )

    assert _is_action_mutation_response(like, ("/digg/",))
    assert _server_accepted_mutation(like)
    assert not _server_accepted_mutation(rejected)
    assert not _is_action_mutation_response(reading, ("/collect/",))


def test_account_mutation_accepts_successful_empty_response_only():
    empty = FakeMutationResponse(
        "https://www.tiktok.com/api/collect/item/", payload=ValueError()
    )
    failed_http = FakeMutationResponse(
        "https://www.tiktok.com/api/collect/item/", ok=False, payload=None
    )

    assert _server_accepted_mutation(empty)
    assert not _server_accepted_mutation(failed_http)


FAKE_FEED_HTML = """
<main>
  <article id="fora-da-tela">
    <a href="/@errado">@errado</a>
    <div data-e2e="video-desc">descrição errada</div>
    <a href="/@errado/video/111">link errado</a>
    <video src="preload.mp4"></video>
  </article>
  <article id="ativo">
    <a href="/@correto"> @correto </a>
    <div data-e2e="video-desc"> descrição correta </div>
    <a href="/@correto/video/222?utm_source=teste">link correto</a>
    <video src="ativo.mp4"></video>
  </article>
</main>
"""


class FakePage:
    def __init__(
        self,
        snapshot=None,
        *,
        wait_error: Exception | None = None,
        play_blocked: bool = False,
        play_timed_out: bool = False,
    ) -> None:
        self.url = "https://www.tiktok.com/"
        self.snapshot = snapshot
        self.wait_error = wait_error
        self.wait_calls = []
        self.scripts: list[str] = []
        self.volume = 1.0
        self.muted = False
        self.paused = False
        self.play_blocked = play_blocked
        self.play_timed_out = play_timed_out
        self.mouse = FakeMouse()
        self.installed_volume = None

    def evaluate(self, script: str, argument=None):
        self.scripts.append(script)
        if "__tiktokAccessibleVolumeState" in script:
            self.installed_volume = float(argument)
            self.volume = float(argument)
            return True
        if script == ACTIVE_VIDEO_SNAPSHOT_SCRIPT:
            return self.snapshot
        if script == NAVIGATION_MARKER_SCRIPT:
            if self.snapshot is None:
                return None
            return {
                "fingerprint": self.snapshot.get("fingerprint", "video-atual"),
                "videoMarker": "elemento-video-1",
                "containerMarker": "item-feed-1",
                "mediaGeneration": 0,
                "pageUrl": self.url,
                "probeToken": "sonda-1",
            }
        if "const effectivelyMuted" in script:
            effectively_muted = self.muted or self.volume == 0
            self.muted = not effectively_muted
            if not self.muted and self.volume == 0:
                self.volume = 0.1
            return {"volume": self.volume, "muted": self.muted}
        match = re.search(r"(?:active\.)?video\.volume = ([0-9.]+)", script)
        if match:
            self.volume = float(match.group(1))
            self.muted = False
            return {"volume": self.volume, "muted": self.muted}
        if "video.play()" in script:
            if self.play_blocked:
                return {"blocked": True, "paused": True}
            if self.play_timed_out:
                return {"blocked": False, "timedOut": True, "paused": True}
            self.paused = not self.paused
            return {"blocked": False, "paused": self.paused}
        if "document.documentElement.clientHeight" in script:
            return 600
        if "document.documentElement.clientWidth" in script:
            return 800
        return True

    def wait_for_function(
        self, script: str, arg: object = None, timeout: int = 30_000
    ) -> None:
        self.wait_calls.append((script, arg, timeout))
        if self.wait_error:
            raise self.wait_error


class FakeButton:
    def __init__(self):
        self.clicked = False

    def is_visible(self):
        return True

    def click(self):
        self.clicked = True


class FakeMouse:
    def __init__(self):
        self.wheels = []
        self.moves = []

    def move(self, x, y):
        self.moves.append((x, y))

    def wheel(self, x, y):
        self.wheels.append((x, y))


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    def count(self):
        return len(self.elements)

    def nth(self, index):
        return self.elements[index]


class LocatorPage(FakePage):
    def __init__(self, snapshot, button):
        super().__init__(snapshot)
        self.button = button

    def locator(self, selector):
        if 'arrow-down' in selector:
            return FakeLocator([self.button])
        return FakeLocator([])


def snapshot(**changes):
    value = {
        "author": "@correto",
        "description": "descrição correta",
        "url": "/@correto/video/222?utm_source=teste",
        "source": "ativo.mp4",
        "volume": 1.0,
        "muted": False,
    }
    value.update(changes)
    return value


def test_fake_feed_documents_two_different_video_containers():
    assert 'id="fora-da-tela"' in FAKE_FEED_HTML
    assert 'id="ativo"' in FAKE_FEED_HTML


def test_video_with_largest_visible_area_wins():
    result = choose_video_candidate(
        [
            VideoCandidate("menor", 400, 500, 400, 300, playing=True),
            VideoCandidate("maior", 400, 500, 400, 450),
        ]
    )
    assert result and result.identifier == "maior"


def test_video_outside_viewport_is_rejected_even_if_playing():
    result = choose_video_candidate(
        [
            VideoCandidate("preload", 1000, 1000, 0, 0, playing=True),
            VideoCandidate("ativo", 300, 400, 300, 400),
        ]
    )
    assert result and result.identifier == "ativo"


def test_intersection_ratio_playback_and_semantics_break_ties_in_order():
    result = choose_video_candidate(
        [
            VideoCandidate("parcial", 800, 800, 400, 200, playing=True),
            VideoCandidate("inteiro", 400, 200, 400, 200, semantic_container=True),
        ]
    )
    assert result and result.identifier == "inteiro"


def test_fallback_uses_playing_video_when_no_intersection_can_be_calculated():
    result = choose_video_candidate(
        [
            VideoCandidate("central", 300, 300, 0, 0, distance_to_center=10),
            VideoCandidate(
                "reproduzindo",
                300,
                300,
                0,
                0,
                playing=True,
                distance_to_center=500,
            ),
        ]
    )
    assert result and result.identifier == "reproduzindo"


def test_author_and_description_come_from_same_active_container_snapshot():
    info = TikTokVideoController(FakePage(snapshot())).get_info()
    assert info.author == "@correto"
    assert info.description == "descrição correta"


def test_missing_metadata_has_requested_accessible_fallbacks():
    info = TikTokVideoController(FakePage(snapshot(author="", description=""))).get_info()
    assert info.author == "Autor não encontrado para o vídeo atual"
    assert info.description == "Este vídeo não possui descrição"


def test_author_and_description_are_normalized():
    assert normalize_author("  @autor\n oficial  ") == "@autor oficial"
    assert normalize_description(" linha 1\n\tlinha 2 ") == "linha 1 linha 2"


def test_video_url_is_canonical_and_tracking_is_removed():
    assert select_current_url(
        "/@autor/video/123?utm_source=x&lang=pt#share",
        "https://www.tiktok.com/",
    ) == "https://www.tiktok.com/@autor/video/123"


@pytest.mark.parametrize(
    "candidate",
    [None, "", "https://www.tiktok.com/", "https://www.tiktok.com/foryou"],
)
def test_root_or_non_video_tiktok_url_is_rejected(candidate):
    with pytest.raises(VideoControlError, match="identificar o link"):
        select_current_url(candidate, "https://www.tiktok.com/")


def test_media_cdn_and_other_hosts_are_rejected():
    with pytest.raises(VideoControlError, match="identificar o link"):
        select_current_url("https://cdn.example/video/123.mp4", "https://www.tiktok.com/")


def test_controller_uses_active_container_video_link():
    page = FakePage(snapshot())
    assert TikTokVideoController(page).current_url() == "https://www.tiktok.com/@correto/video/222"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-0.5, 0.0), (0.0, 0.0), (0.46, 0.5), (1.0, 1.0), (2.0, 1.0)],
)
def test_volume_is_clamped_and_rounded_to_ten_percent(value, expected):
    assert clamp_volume(value) == expected


def test_volume_increment_reduction_and_unmute():
    page = FakePage(snapshot())
    controller = TikTokVideoController(page, 0.5)
    assert controller.set_volume(0.6) == 0.6
    assert page.muted is False
    assert controller.set_volume(0.5) == 0.5


def test_volume_boundary_messages():
    assert volume_message(0) == "Volume mínimo, 0%"
    assert volume_message(0.7) == "Volume 70%"
    assert volume_message(1) == "Volume máximo, 100%"


def test_mute_toggle():
    page = FakePage(snapshot())
    controller = TikTokVideoController(page)
    assert controller.toggle_mute() is True
    assert controller.toggle_mute() is False


def test_effectively_muted_zero_volume_is_activated_instead_of_disabled():
    page = FakePage(snapshot())
    page.volume = 0
    controller = TikTokVideoController(page, 0.6)
    assert controller.toggle_mute() is False
    assert page.muted is False
    assert page.volume > 0


def test_toggle_playback_awaits_play_and_confirms_result():
    page = FakePage(snapshot())
    page.paused = True
    controller = TikTokVideoController(page)
    assert controller.toggle_playback() is False
    assert controller.toggle_playback() is True


def test_rejected_play_promise_has_clear_accessible_error():
    page = FakePage(snapshot(), play_blocked=True)
    page.paused = True
    with pytest.raises(
        VideoControlError,
        match="Reprodução bloqueada pelo Chromium; interação inicial necessária",
    ):
        TikTokVideoController(page).toggle_playback()


def test_pending_play_promise_releases_queue_with_clear_error():
    page = FakePage(snapshot(), play_timed_out=True)
    page.paused = True
    with pytest.raises(VideoControlError, match="fila foi liberada"):
        TikTokVideoController(page).toggle_playback()


def test_preferred_volume_is_applied_after_video_change():
    page = FakePage(snapshot())
    controller = TikTokVideoController(page, 0.4)
    controller.next_video()
    assert page.volume == 0.4
    assert page.installed_volume == 0.4


def test_volume_preference_is_installed_before_navigation():
    button = FakeButton()
    page = LocatorPage(snapshot(), button)
    controller = TikTokVideoController(page, 0.7)
    controller.next_video()
    installation_index = next(
        index
        for index, script in enumerate(page.scripts)
        if "__tiktokAccessibleVolumeState" in script
    )
    snapshot_index = page.scripts.index(ACTIVE_VIDEO_SNAPSHOT_SCRIPT)
    assert installation_index < snapshot_index


def test_navigation_uses_playwright_wheel_instead_of_physical_keyboard():
    page = FakePage(snapshot())
    TikTokVideoController(page).next_video()
    assert page.mouse.moves == [(400, 300)]
    assert page.mouse.wheels == [(0, 510)]
    assert not hasattr(page, "keyboard")


def test_navigation_restores_playwright_click_for_visible_feed_button():
    button = FakeButton()
    page = LocatorPage(snapshot(), button)
    TikTokVideoController(page).next_video()
    assert button.clicked is True
    assert page.mouse.moves == []
    assert page.mouse.wheels == []


def test_current_tiktok_navigation_selectors_are_preferred():
    assert TikTokSelectors.NEXT_BUTTONS[0] == (
        'button[data-e2e="feed-navigation-next"]'
    )
    assert TikTokSelectors.PREVIOUS_BUTTONS[0] == (
        'button[data-e2e="feed-navigation-prev"]'
    )


def test_navigation_confirmation_observes_dom_identity_and_media_reload():
    page = FakePage(snapshot())
    TikTokVideoController(page).next_video()

    _script, previous, timeout = page.wait_calls[0]
    assert previous == {
        "fingerprint": "video-atual",
        "videoMarker": "elemento-video-1",
        "containerMarker": "item-feed-1",
        "mediaGeneration": 0,
        "pageUrl": "https://www.tiktok.com/",
        "probeToken": "sonda-1",
    }
    assert "videoMarker !== previous.videoMarker" in _script
    assert "mediaGeneration !== previous.mediaGeneration" in _script
    assert "probe.changed" in _script
    assert timeout == 6_000


def test_navigation_timeout_is_silent_when_command_was_sent():
    page = FakePage(snapshot(), wait_error=TimeoutError())
    info = TikTokVideoController(page).previous_video()
    assert info.description == "descrição correta"


def test_unexpected_navigation_verification_failure_is_also_silent():
    page = FakePage(snapshot(), wait_error=RuntimeError("falha inesperada"))
    info = TikTokVideoController(page).previous_video()
    assert info.description == "descrição correta"


def test_missing_active_video_fails_safely():
    with pytest.raises(VideoControlError, match="localizar o vídeo"):
        TikTokVideoController(FakePage(None)).get_info()
