from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

class VideoControlError(RuntimeError):
    """Falha controlada ao localizar ou comandar o vídeo atual."""


@dataclass(frozen=True)
class VideoInfo:
    author: str
    description: str


@dataclass(frozen=True)
class VideoCandidate:
    identifier: str
    width: float
    height: float
    intersection_width: float
    intersection_height: float
    displayed: bool = True
    visible: bool = True
    playing: bool = False
    semantic_container: bool = False
    distance_to_center: float = float("inf")


def choose_video_candidate(candidates: Iterable[VideoCandidate]) -> VideoCandidate | None:
    """Espelho testável da ordenação executada no DOM pelo Playwright."""
    usable: list[tuple[int, VideoCandidate]] = []
    ranked: list[tuple[float, float, int, int, int, VideoCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not candidate.displayed or not candidate.visible or candidate.width <= 0 or candidate.height <= 0:
            continue
        usable.append((index, candidate))
        area = max(0.0, candidate.intersection_width) * max(0.0, candidate.intersection_height)
        if area <= 0:
            continue
        ratio = area / (candidate.width * candidate.height)
        ranked.append(
            (
                area,
                ratio,
                int(candidate.playing),
                int(candidate.semantic_container),
                -index,
                candidate,
            )
        )
    if ranked:
        return max(ranked, key=lambda item: item[:-1])[-1]
    playing = [(index, candidate) for index, candidate in usable if candidate.playing]
    fallback = playing or usable
    if not fallback:
        return None
    return min(
        fallback,
        key=lambda item: (
            item[1].distance_to_center,
            -(item[1].width * item[1].height),
            item[0],
        ),
    )[1]


class TikTokSelectors:
    """Seletores de controles do feed, em ordem de preferência."""

    NEXT_BUTTONS = (
        'button[data-e2e="feed-navigation-next"]',
        'button[data-e2e="arrow-down"]',
        'button[aria-label*="próximo" i]',
        'button[aria-label*="next" i]',
    )
    PREVIOUS_BUTTONS = (
        'button[data-e2e="feed-navigation-prev"]',
        'button[data-e2e="arrow-up"]',
        'button[aria-label*="anterior" i]',
        'button[aria-label*="previous" i]',
    )
    COMMENT_BUTTONS = (
        '[data-e2e="comment-icon"]',
        '[role="button"][aria-label*="coment" i]',
        '[role="button"][aria-label*="comment" i]',
    )
    LIKE_BUTTONS = (
        '[data-e2e="like-button"]',
        '[data-e2e="like-icon"]',
        '[data-e2e="browse-like-icon"]',
        '[data-e2e*="like-icon" i]',
        '[role="button"][aria-label*="curtir" i]',
        '[role="button"][aria-label*="like" i]',
        '[role="button"][aria-label*="descurtir" i]',
        '[role="button"][aria-label*="unlike" i]',
    )
    FAVORITE_BUTTONS = (
        '[data-e2e="favorite-button"]',
        '[data-e2e="favorite-icon"]',
        '[data-e2e="collect-icon"]',
        '[data-e2e*="collect-icon" i]',
        '[role="button"][aria-label*="favorit" i]',
        '[role="button"][aria-label*="favorite" i]',
        '[role="button"][aria-label*="remover dos favoritos" i]',
    )


# Uma única rotina escolhe o vídeo. Todas as operações abaixo a reutilizam dentro
# da página, evitando que autor, descrição e link venham de itens diferentes.
ACTIVE_VIDEO_RESOLVER = r"""
const findActiveVideo = () => {
    const viewportWidth = Math.max(document.documentElement.clientWidth, innerWidth || 0);
    const viewportHeight = Math.max(document.documentElement.clientHeight, innerHeight || 0);
    const candidates = [...document.querySelectorAll('video')].map((video, index) => {
        const rect = video.getBoundingClientRect();
        const style = getComputedStyle(video);
        if (style.display === 'none' || style.visibility === 'hidden' ||
                Number(style.opacity || 1) === 0 || rect.width <= 0 || rect.height <= 0) {
            return null;
        }
        const width = Math.max(0, Math.min(rect.right, viewportWidth) - Math.max(rect.left, 0));
        const height = Math.max(0, Math.min(rect.bottom, viewportHeight) - Math.max(rect.top, 0));
        const visibleArea = width * height;
        const totalArea = rect.width * rect.height;
        const intersectionRatio = totalArea ? visibleArea / totalArea : 0;
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const distanceToCenter = Math.hypot(
            centerX - viewportWidth / 2,
            centerY - viewportHeight / 2
        );
        const semanticContainer = video.closest(
            'article, [data-e2e*="feed-item" i], [data-e2e*="browse-video" i], ' +
            '[data-e2e*="video-detail" i], [data-e2e*="recommend-list-item" i], ' +
            '[data-e2e*="feed-video" i], [role="article"]'
        );
        return {
            video,
            index,
            visibleArea,
            intersectionRatio,
            playing: !video.paused && !video.ended ? 1 : 0,
            semantic: semanticContainer ? 1 : 0,
            distanceToCenter,
            container: semanticContainer || video.parentElement
        };
    }).filter(Boolean);
    const intersecting = candidates.filter(candidate => candidate.visibleArea > 0);
    if (intersecting.length) {
        intersecting.sort((a, b) =>
            b.visibleArea - a.visibleArea ||
            b.intersectionRatio - a.intersectionRatio ||
            b.playing - a.playing ||
            b.semantic - a.semantic ||
            a.index - b.index
        );
        return intersecting[0];
    }
    const playing = candidates.filter(candidate => candidate.playing);
    if (playing.length) {
        playing.sort((a, b) => a.distanceToCenter - b.distanceToCenter || a.index - b.index);
        return playing[0];
    }
    candidates.sort((a, b) =>
        a.distanceToCenter - b.distanceToCenter ||
        b.visibleArea - a.visibleArea ||
        (b.video.getBoundingClientRect().width * b.video.getBoundingClientRect().height) -
        (a.video.getBoundingClientRect().width * a.video.getBoundingClientRect().height) ||
        b.semantic - a.semantic ||
        a.index - b.index
    );
    return candidates[0] || null;
};
"""


def _active_script(body: str, parameter: str = "") -> str:
    return (
        f"async ({parameter}) => {{ {ACTIVE_VIDEO_RESOLVER} "
        f"const active = findActiveVideo(); {body} }}"
    )


ACTIVE_VIDEO_SNAPSHOT_SCRIPT = _active_script(
    r"""
    if (!active) return null;
    const {video, container} = active;
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const visible = element => {
        if (!element) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0;
    };
    // Amplia a busca apenas enquanto o ancestral ainda pertence exclusivamente
    // ao vídeo ativo. Parar ao encontrar outro <video> impede que um item sem
    // descrição herde texto de outro item do feed.
    let scope = video.parentElement || container;
    let ancestor = video.parentElement;
    for (let depth = 0; ancestor && ancestor !== document.body && depth < 10; depth++) {
        const descendantVideos = [...ancestor.querySelectorAll('video')];
        if (descendantVideos.some(candidate => candidate !== video)) break;
        scope = ancestor;
        const hasVideoLink = Boolean(ancestor.querySelector('a[href*="/video/"]'));
        const hasProfileLink = Boolean(ancestor.querySelector('a[href*="/@"]'));
        const hasDescription = Boolean(ancestor.querySelector(
            '[data-e2e="video-desc"], [data-e2e="browse-video-desc"], [data-e2e*="video-caption" i]'
        ));
        if (hasVideoLink || (hasProfileLink && hasDescription)) {
            break;
        }
        ancestor = ancestor.parentElement;
    }
    const profileLinks = scope ? [...scope.querySelectorAll('a[href]')].filter(link => {
        try { return /^\/@[^/]+\/?$/.test(new URL(link.href, location.href).pathname); }
        catch (_) { return false; }
    }).filter(visible) : [];
    profileLinks.sort((a, b) =>
        Number(Boolean(b.matches('[data-e2e*="author" i], [data-e2e*="username" i]'))) -
        Number(Boolean(a.matches('[data-e2e*="author" i], [data-e2e*="username" i]')))
    );
    let author = '';
    let authorHandle = '';
    if (profileLinks.length) {
        const link = profileLinks[0];
        const path = new URL(link.href, location.href).pathname;
        authorHandle = decodeURIComponent(path.split('/')[1] || '');
        const candidate = clean(link.textContent) || clean(link.getAttribute('aria-label'));
        author = candidate.includes('@') ? candidate : authorHandle;
    }
    if (!author && scope) {
        const authorElements = [
            ...scope.querySelectorAll(
                '[data-e2e="video-author-uniqueid"], [data-e2e="browse-username"], ' +
                '[data-e2e*="author" i], [itemprop="author"], ' +
                '[aria-label*="criador" i], [aria-label*="creator" i]'
            )
        ];
        for (const element of authorElements) {
            if (!visible(element) && element.tagName !== 'META') continue;
            if (element.closest('button, [role="button"], [role="menu"], [data-e2e*="comment" i]')) continue;
            const candidate = clean(element.textContent) ||
                clean(element.getAttribute('aria-label')) ||
                clean(element.getAttribute('content'));
            if (!candidate || candidate.length > 100) continue;
            author = candidate;
            const handleMatch = candidate.match(/@[A-Za-z0-9._-]+/);
            if (handleMatch) authorHandle = handleMatch[0];
            break;
        }
    }
    const descriptions = scope ? [
        ...scope.querySelectorAll(
            '[data-e2e="video-desc"], [data-e2e="browse-video-desc"], ' +
            '[data-e2e*="video-caption" i], [aria-label*="descrição" i], ' +
            '[aria-label*="description" i], [itemprop="description"]'
        )
    ] : [];
    let description = '';
    for (const element of descriptions) {
        if ((!visible(element) && element.tagName !== 'META') || element.closest('button, [role="button"], [role="menu"], [data-e2e*="comment" i]')) continue;
        const candidate = clean(element.textContent) || clean(element.getAttribute('aria-label')) || clean(element.getAttribute('content'));
        if (candidate && candidate !== clean(author) && candidate !== clean(authorHandle)) {
            description = candidate;
            break;
        }
    }
    let videoLinks = scope ? [...scope.querySelectorAll('a[href*="/video/"]')] : [];
    if (!videoLinks.length) {
        const videoRect = video.getBoundingClientRect();
        const centerX = videoRect.left + videoRect.width / 2;
        const centerY = videoRect.top + videoRect.height / 2;
        videoLinks = [...document.querySelectorAll('a[href*="/video/"]')]
            .map(link => {
                let common = link.parentElement;
                let related = false;
                for (let depth = 0; common && common !== document.body && depth < 10; depth++) {
                    if (common.contains(video)) { related = true; break; }
                    common = common.parentElement;
                }
                const rect = link.getBoundingClientRect();
                const distance = Math.hypot(
                    rect.left + rect.width / 2 - centerX,
                    rect.top + rect.height / 2 - centerY
                );
                return {link, related, distance};
            })
            .sort((a, b) => Number(b.related) - Number(a.related) || a.distance - b.distance)
            .map(candidate => candidate.link);
    }
    let url = videoLinks.length ? videoLinks[0].href : '';
    if (!url && /\/video\//.test(location.pathname)) url = location.href;
    if (!url) {
        const idElement = scope && scope.querySelector('[data-video-id]');
        const videoId = video.dataset.videoId ||
            (scope && scope.dataset && scope.dataset.videoId) ||
            (idElement && idElement.dataset.videoId) || '';
        if (/^\d+$/.test(videoId) && /^@[A-Za-z0-9._-]+$/.test(authorHandle)) {
            url = '/' + authorHandle + '/video/' + videoId;
        }
    }
    const fingerprint = [
        video.currentSrc || video.src || video.poster || '',
        video.dataset.videoId || '',
        videoLinks.length ? videoLinks[0].getAttribute('href') || '' : '',
        scope ? (scope.textContent || '').replace(/\s+/g, ' ').trim() : ''
    ].join('|');
    return {
        author,
        description,
        url,
        source: video.currentSrc || video.src || video.poster || '',
        paused: video.paused,
        volume: video.volume,
        muted: video.muted,
        fingerprint,
        visibleArea: active.visibleArea,
        intersectionRatio: active.intersectionRatio
    };
    """
)


NAVIGATION_MARKER_SCRIPT = _active_script(
    r"""
    if (!active) return null;
    const markerKey = '__tiktokAccessibleNavigationMarker';
    const generationKey = '__tiktokAccessibleMediaGeneration';
    const probeKey = '__tiktokAccessibleNavigationProbe';
    const ensureMarker = element => {
        if (!element) return '';
        if (!element[markerKey]) {
            const sequenceKey = '__tiktokAccessibleNavigationSequence';
            window[sequenceKey] = (window[sequenceKey] || 0) + 1;
            Object.defineProperty(element, markerKey, {
                value: `${Date.now()}-${window[sequenceKey]}`,
                configurable: true
            });
        }
        return element[markerKey];
    };
    const {video, container} = active;
    if (typeof video[generationKey] !== 'number') {
        video[generationKey] = 0;
        const changed = () => { video[generationKey] += 1; };
        video.addEventListener('emptied', changed, {passive: true});
        video.addEventListener('loadstart', changed, {passive: true});
        video.addEventListener('loadedmetadata', changed, {passive: true});
    }
    const oldProbe = window[probeKey];
    if (oldProbe) {
        if (oldProbe.observer) oldProbe.observer.disconnect();
        if (oldProbe.abortController) oldProbe.abortController.abort();
    }
    const abortController = new AbortController();
    const probe = {
        token: `${Date.now()}-${Math.random()}`,
        changed: false,
        observer: null,
        abortController
    };
    const markChanged = () => { probe.changed = true; };
    probe.observer = new MutationObserver(markChanged);
    probe.observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        characterData: true
    });
    window.addEventListener('scroll', markChanged, {
        capture: true,
        passive: true,
        signal: abortController.signal
    });
    for (const eventName of ['emptied', 'loadstart', 'loadedmetadata', 'playing']) {
        document.addEventListener(eventName, markChanged, {
            capture: true,
            passive: true,
            signal: abortController.signal
        });
    }
    window[probeKey] = probe;
    const link = container && container.querySelector('a[href*="/video/"]');
    const fingerprint = [
        video.currentSrc || video.src || video.poster || '',
        video.dataset.videoId || '',
        link ? link.getAttribute('href') || '' : '',
        container ? (container.textContent || '').replace(/\s+/g, ' ').trim() : ''
    ].join('|');
    return {
        fingerprint,
        videoMarker: ensureMarker(video),
        containerMarker: ensureMarker(container),
        mediaGeneration: video[generationKey],
        pageUrl: location.href,
        probeToken: probe.token
    };
    """
)


NAVIGATION_PROBE_CLEANUP_SCRIPT = r"""() => {
    const probe = window.__tiktokAccessibleNavigationProbe;
    if (!probe) return;
    if (probe.observer) probe.observer.disconnect();
    if (probe.abortController) probe.abortController.abort();
}"""


VOLUME_PREFERENCE_INSTALLER = r"""target => {
    const key = '__tiktokAccessibleVolumeState';
    let state = window[key];
    const apply = video => {
        if (!(video instanceof HTMLVideoElement)) return;
        if (Math.abs(video.volume - window[key].target) > 0.001) {
            video.volume = window[key].target;
        }
    };
    if (!state) {
        state = {target, applying: false};
        window[key] = state;
        const reapply = event => {
            if (state.applying) return;
            const video = event.target;
            if (!(video instanceof HTMLVideoElement)) return;
            state.applying = true;
            try { apply(video); } finally { state.applying = false; }
        };
        document.addEventListener('volumechange', reapply, true);
        document.addEventListener('loadedmetadata', reapply, true);
        document.addEventListener('play', reapply, true);
        state.observer = new MutationObserver(records => {
            for (const record of records) {
                for (const node of record.addedNodes) {
                    if (!(node instanceof Element)) continue;
                    if (node instanceof HTMLVideoElement) apply(node);
                    for (const video of node.querySelectorAll('video')) apply(video);
                }
            }
        });
    }
    state.target = target;
    const connect = () => {
        if (!document.documentElement) return;
        if (state.root !== document.documentElement) {
            state.observer.disconnect();
            state.observer.observe(document.documentElement, {
                childList: true,
                subtree: true
            });
            state.root = document.documentElement;
        }
        for (const video of document.querySelectorAll('video')) apply(video);
    };
    connect();
    if (!document.documentElement) {
        document.addEventListener('readystatechange', connect, {once: true});
    }
    return true;
}"""


COMMENTS_SCRIPT = r"""() => {
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const visible = element => {
        if (!element) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
    };
    const panelSelectors = [
        '[data-e2e="comment-list"]',
        '[data-e2e*="comment-list" i]',
        '[class*="CommentListContainer"]',
        '[class*="CommentList"]',
        '[role="dialog"]'
    ];
    let panel = null;
    for (const selector of panelSelectors) {
        panel = [...document.querySelectorAll(selector)].find(visible) || null;
        if (panel) break;
    }
    if (!panel) return [];
    const itemSelectors = [
        '[data-e2e="comment-item"]',
        '[data-e2e="comment-level-1"]',
        '[data-e2e="comment-level-2"]',
        'li[class*="CommentItem"]',
        '[class*="DivCommentItemContainer"]'
    ];
    const seen = new Set();
    const comments = [];
    for (const selector of itemSelectors) {
        const items = [...panel.querySelectorAll(selector)];
        if (!items.length) continue;
        for (const item of items) {
            const text = clean(item.textContent || item.getAttribute('aria-label'));
            if (!text || seen.has(text)) continue;
            seen.add(text);
            comments.push(text);
            if (comments.length >= 100) return comments;
        }
        if (comments.length) break;
    }
    return comments;
}"""


POST_COMMENT_SCRIPT = r"""text => {
    const visible = element => {
        if (!element) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0;
    };
    const inputSelectors = [
        '[data-e2e="comment-input"] [contenteditable="true"]',
        '[data-e2e="comment-input"][contenteditable="true"]',
        '[contenteditable="true"][data-e2e*="comment" i]',
        'textarea[data-e2e*="comment" i]',
        'textarea[placeholder*="coment" i]',
        'textarea[placeholder*="comment" i]'
    ];
    let input = null;
    for (const selector of inputSelectors) {
        input = [...document.querySelectorAll(selector)].find(visible) || null;
        if (input) break;
    }
    if (!input) return {ok: false, reason: 'input'};
    input.focus();
    if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {
        const setter = Object.getOwnPropertyDescriptor(
            input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
            'value'
        ).set;
        setter.call(input, text);
    } else {
        input.textContent = text;
    }
    input.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        inputType: 'insertText',
        data: text
    }));
    input.dispatchEvent(new Event('change', {bubbles: true}));
    const form = input.closest('form, [data-e2e*="comment" i], [class*="CommentInput"]') ||
        input.parentElement;
    const submitSelectors = [
        'button[data-e2e="comment-post"]',
        'button[data-e2e*="post" i]',
        'button[type="submit"]',
        'button[aria-label*="publicar" i]',
        'button[aria-label*="post" i]'
    ];
    let button = null;
    for (const selector of submitSelectors) {
        button = (form && [...form.querySelectorAll(selector)].find(visible)) ||
            [...document.querySelectorAll(selector)].find(visible) || null;
        if (button) break;
    }
    if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') {
        return {ok: false, reason: 'button'};
    }
    button.click();
    return {ok: true};
}"""


def volume_preference_init_script(value: float) -> str:
    return f"({VOLUME_PREFERENCE_INSTALLER})({clamp_volume(value)!r});"


def normalize_author(value: Any) -> str:
    text = _normalize_text(value)
    return text or "Autor não encontrado para o vídeo atual"


def normalize_description(value: Any) -> str:
    text = _normalize_text(value)
    return text or "Este vídeo não possui descrição"


def select_current_url(video_url: Any, page_url: Any) -> str:
    """Retorna somente uma URL canônica de vídeo TikTok, sem rastreamento."""
    base = page_url.strip() if isinstance(page_url, str) else ""
    candidate = video_url.strip() if isinstance(video_url, str) else ""
    if not candidate:
        raise VideoControlError("Não foi possível identificar o link do vídeo atual")
    absolute = urljoin(base or "https://www.tiktok.com/", candidate)
    parsed = urlsplit(absolute)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        hostname == "tiktok.com" or hostname.endswith(".tiktok.com")
    ):
        raise VideoControlError("Não foi possível identificar o link do vídeo atual")
    match = re.search(r"/(@[^/?#]+)/video/(\d+)", parsed.path)
    if not match:
        raise VideoControlError("Não foi possível identificar o link do vídeo atual")
    path = f"/{match.group(1)}/video/{match.group(2)}"
    return urlunsplit(("https", "www.tiktok.com", path, "", ""))


def clamp_volume(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 1)


def volume_message(volume: float) -> str:
    percent = round(clamp_volume(volume) * 100)
    if percent == 100:
        return "Volume máximo, 100%"
    if percent == 0:
        return "Volume mínimo, 0%"
    return f"Volume {percent}%"


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _is_action_mutation_response(
    response: Any, url_patterns: tuple[str, ...]
) -> bool:
    """Reconhece respostas que alteram a conta, nunca listas de leitura."""
    try:
        path = (urlsplit(str(response.url)).path or "").lower()
    except Exception:
        return False
    if "item_list" in path or path.endswith("/list/"):
        return False
    return any(pattern.lower() in path for pattern in url_patterns)


def _server_accepted_mutation(response: Any) -> bool:
    """Confirma HTTP e, quando disponível, o código de negócio do TikTok."""
    try:
        if not bool(response.ok):
            return False
    except Exception:
        return False
    try:
        payload = response.json()
    except Exception:
        # Algumas variantes retornam corpo vazio apesar do HTTP 2xx.
        return True
    if not isinstance(payload, dict):
        return True
    for key in ("status_code", "statusCode", "code"):
        if key not in payload:
            continue
        return payload[key] in (0, "0", "success", "SUCCESS")
    return True


class TikTokVideoController:
    """Opera sobre o único vídeo com maior visibilidade na página Playwright."""

    def __init__(self, page: Any, preferred_volume: float = 1.0) -> None:
        self._page = page
        self._preferred_volume = clamp_volume(preferred_volume)

    def next_video(self) -> VideoInfo:
        self.close_comments()
        self.install_volume_preference()
        self._navigate(TikTokSelectors.NEXT_BUTTONS, "ArrowDown")
        self.set_volume(self._preferred_volume)
        return self.get_info()

    def previous_video(self) -> VideoInfo:
        self.close_comments()
        self.install_volume_preference()
        self._navigate(TikTokSelectors.PREVIOUS_BUTTONS, "ArrowUp")
        self.set_volume(self._preferred_volume)
        return self.get_info()

    def toggle_playback(self) -> bool:
        try:
            result = self._page.evaluate(
                _active_script(
                    """if (!active) return null;
                    const video = active.video;
                    if (video.paused) {
                        const outcome = await Promise.race([
                            video.play().then(() => 'played').catch(() => 'blocked'),
                            new Promise(resolve => setTimeout(() => resolve('timeout'), 3000))
                        ]);
                        if (outcome === 'blocked') return {blocked: true, timedOut: false, paused: video.paused};
                        if (outcome === 'timeout') return {blocked: false, timedOut: true, paused: video.paused};
                    } else {
                        video.pause();
                    }
                    return {blocked: false, timedOut: false, paused: video.paused};"""
                )
            )
        except Exception as exc:
            raise VideoControlError("Não foi possível reproduzir ou pausar o vídeo.") from exc
        if result is None:
            raise VideoControlError("Não foi possível localizar o vídeo atual.")
        if not isinstance(result, dict):
            raise VideoControlError("Não foi possível confirmar o estado da reprodução.")
        if result.get("blocked"):
            raise VideoControlError(
                "Reprodução bloqueada pelo Chromium; interação inicial necessária."
            )
        if result.get("timedOut"):
            raise VideoControlError(
                "O Chromium não respondeu ao comando de reprodução; a fila foi liberada."
            )
        return bool(result.get("paused"))

    def get_info(self) -> VideoInfo:
        snapshot = self._snapshot()
        return VideoInfo(
            author=normalize_author(snapshot.get("author")),
            description=normalize_description(snapshot.get("description")),
        )

    def current_url(self) -> str:
        snapshot = self._snapshot()
        return select_current_url(snapshot.get("url"), self._page.url)

    def set_volume(self, value: float) -> float:
        target = clamp_volume(value)
        self.install_volume_preference(target)
        try:
            result = self._page.evaluate(
                _active_script(
                    f"""if (!active) return null;
                    const video = active.video;
                    video.defaultMuted = false;
                    video.removeAttribute('muted');
                    video.muted = false;
                    video.volume = {target!r};
                    video.dispatchEvent(new Event('volumechange', {{bubbles: true}}));
                    return {{volume: video.volume, muted: video.muted}};"""
                )
            )
        except Exception as exc:
            raise VideoControlError("Não foi possível alterar o volume do vídeo atual.") from exc
        if result is None:
            raise VideoControlError("Não foi possível localizar o vídeo atual.")
        if not isinstance(result, dict) or result.get("muted"):
            raise VideoControlError("Não foi possível confirmar a alteração do volume.")
        self._preferred_volume = clamp_volume(float(result.get("volume", target)))
        return self._preferred_volume

    def install_volume_preference(self, value: float | None = None) -> None:
        target = clamp_volume(self._preferred_volume if value is None else value)
        try:
            installed = self._page.evaluate(
                VOLUME_PREFERENCE_INSTALLER,
                target,
            )
        except Exception as exc:
            raise VideoControlError(
                "Não foi possível manter a preferência de volume na página."
            ) from exc
        if installed is not True:
            raise VideoControlError(
                "Não foi possível manter a preferência de volume na página."
            )

    def toggle_mute(self) -> bool:
        try:
            result = self._page.evaluate(
                _active_script(
                    f"""if (!active) return null;
                    const video = active.video;
                    const effectivelyMuted = video.muted || video.defaultMuted ||
                        video.hasAttribute('muted') || video.volume === 0;
                    if (effectivelyMuted) {{
                        video.defaultMuted = false;
                        video.removeAttribute('muted');
                        video.muted = false;
                        if (video.volume === 0) video.volume = {max(self._preferred_volume, 0.1)!r};
                    }} else {{
                        video.muted = true;
                    }}
                    video.dispatchEvent(new Event('volumechange', {{bubbles: true}}));
                    return {{muted: video.muted, volume: video.volume}};"""
                )
            )
        except Exception as exc:
            raise VideoControlError("Não foi possível alterar o som do vídeo atual.") from exc
        if result is None:
            raise VideoControlError("Não foi possível localizar o vídeo atual.")
        if not isinstance(result, dict):
            raise VideoControlError("Não foi possível confirmar o estado do som.")
        if not result.get("muted"):
            self._preferred_volume = clamp_volume(float(result.get("volume", 0.1)))
        return bool(result.get("muted"))

    def read_comments(self) -> tuple[str, ...]:
        if not self._click_active_action(TikTokSelectors.COMMENT_BUTTONS):
            raise VideoControlError(
                "Não foi possível localizar o botão de comentários do vídeo atual."
            )
        try:
            self._page.wait_for_timeout(1_200)
            comments = self._page.evaluate(COMMENTS_SCRIPT)
        except Exception as exc:
            raise VideoControlError("Não foi possível carregar os comentários.") from exc
        if not isinstance(comments, list):
            raise VideoControlError("Não foi possível carregar os comentários.")
        normalized = tuple(
            text
            for text in (_normalize_text(comment) for comment in comments)
            if text
        )
        return normalized

    def post_comment(self, text: str) -> None:
        comment = _normalize_text(text)
        if not comment:
            raise VideoControlError("Digite um comentário antes de publicar.")
        try:
            result = self._page.evaluate(POST_COMMENT_SCRIPT, comment)
        except Exception as exc:
            raise VideoControlError("Não foi possível publicar o comentário.") from exc
        if not isinstance(result, dict) or not result.get("ok"):
            if isinstance(result, dict) and result.get("reason") == "input":
                raise VideoControlError(
                    "Abra os comentários antes de escrever um comentário."
                )
            raise VideoControlError(
                "Não foi possível localizar o botão Publicar comentário."
            )

    def close_comments(self) -> None:
        selectors = (
            'aside button[aria-label="exit" i]',
            '[class*="CommentSidebar"] button[aria-label="exit" i]',
            'button[aria-label="exit" i]',
            'button[data-e2e*="comment-close" i]',
            'button[aria-label*="fechar" i]',
            'button[aria-label*="close" i]',
        )
        try:
            self._click_visible_global(selectors)
        except Exception:
            pass

    def toggle_like(self) -> bool | None:
        found, state = self._click_active_action_with_state(
            TikTokSelectors.LIKE_BUTTONS,
            r"descurtir|unlike|remove like",
            r"curtir|like",
            ("/digg/", "/like/action/"),
        )
        if not found:
            raise VideoControlError(
                "Não foi possível localizar o botão Curtir do vídeo atual."
            )
        if state is None:
            raise VideoControlError(
                "O TikTok não manteve a curtida. Confira se a conta está conectada "
                "no navegador do aplicativo e reimporte cookies de uma sessão ativa."
            )
        return state

    def toggle_favorite(self) -> bool | None:
        found, state = self._click_active_action_with_state(
            TikTokSelectors.FAVORITE_BUTTONS,
            r"remover dos favoritos|remove from favorites|unfavorite",
            r"adicionar aos favoritos|favoritar|favorite",
            ("/collect/", "/favorite/action/"),
        )
        if not found:
            raise VideoControlError(
                "Não foi possível localizar o botão Favoritar do vídeo atual."
            )
        if state is None:
            raise VideoControlError(
                "O TikTok não confirmou o favorito na conta. Confira se a conta "
                "está conectada no navegador do aplicativo e reimporte cookies "
                "de uma sessão ativa."
            )
        return state

    def diagnostics(self) -> dict[str, Any]:
        try:
            result = self._page.evaluate(
                _active_script(
                    """const count = document.querySelectorAll('video').length;
                    if (!active) return {count, active: false};
                    return {
                        count,
                        active: true,
                        paused: active.video.paused,
                        volume: active.video.volume,
                        muted: active.video.muted || active.video.defaultMuted ||
                            active.video.hasAttribute('muted') || active.video.volume === 0,
                        visibility: document.visibilityState
                    };"""
                )
            )
        except Exception as exc:
            raise VideoControlError("Não foi possível inspecionar o vídeo atual.") from exc
        if not isinstance(result, dict):
            raise VideoControlError("Não foi possível inspecionar o vídeo atual.")
        return result

    def _navigate(self, button_selectors: Iterable[str], fallback_key: str) -> None:
        before = self._signature()
        selectors = list(button_selectors)
        try:
            button = self._first_visible(selectors)
            if button is not None:
                button.click()
            else:
                viewport_height = self._page.evaluate(
                    "() => Math.max(document.documentElement.clientHeight, innerHeight || 0, 600)"
                )
                viewport_width = self._page.evaluate(
                    "() => Math.max(document.documentElement.clientWidth, innerWidth || 0, 800)"
                )
                direction = 1 if fallback_key == "ArrowDown" else -1
                self._page.mouse.move(
                    int(float(viewport_width) / 2),
                    int(float(viewport_height) / 2),
                )
                self._page.mouse.wheel(0, direction * int(float(viewport_height) * 0.85))
        except Exception as exc:
            raise VideoControlError("Não foi possível enviar o comando ao vídeo.") from exc

        try:
            self._page.wait_for_function(
                _active_script(
                    r"""if (!active) return false;
                    const video = active.video;
                    const container = active.container;
                    const markerKey = '__tiktokAccessibleNavigationMarker';
                    const generationKey = '__tiktokAccessibleMediaGeneration';
                    const probeKey = '__tiktokAccessibleNavigationProbe';
                    const link = container && container.querySelector('a[href*="/video/"]');
                    const fingerprint = [
                        video.currentSrc || video.src || video.poster || '',
                        video.dataset.videoId || '',
                        link ? link.getAttribute('href') || '' : '',
                        container ? (container.textContent || '').replace(/\s+/g, ' ').trim() : ''
                    ].join('|');
                    const videoMarker = video[markerKey] || '';
                    const containerMarker = container ? container[markerKey] || '' : '';
                    const mediaGeneration = Number(video[generationKey] || 0);
                    const probe = window[probeKey];
                    const probeChanged = Boolean(
                        probe && probe.token === previous.probeToken && probe.changed
                    );
                    const changed = fingerprint !== previous.fingerprint ||
                        (previous.videoMarker && videoMarker !== previous.videoMarker) ||
                        (previous.containerMarker && containerMarker !== previous.containerMarker) ||
                        mediaGeneration !== previous.mediaGeneration ||
                        location.href !== previous.pageUrl || probeChanged;
                    if (changed && probe) {
                        if (probe.observer) probe.observer.disconnect();
                        if (probe.abortController) probe.abortController.abort();
                    }
                    return changed;""",
                    "previous",
                ),
                arg=before,
                timeout=6_000,
            )
        except Exception:
            # O TikTok pode trocar visualmente o vídeo reutilizando o mesmo DOM e
            # sem expor um sinal confiável ao Playwright. O timeout de confirmação
            # ou outra falha dessa checagem não deve transformar uma navegação
            # bem-sucedida em erro para o usuário.
            try:
                self._page.evaluate(NAVIGATION_PROBE_CLEANUP_SCRIPT)
            except Exception:
                pass
            return

    def _snapshot(self) -> dict[str, Any]:
        try:
            snapshot = self._page.evaluate(ACTIVE_VIDEO_SNAPSHOT_SCRIPT)
        except Exception as exc:
            raise VideoControlError("Não foi possível localizar o vídeo atual.") from exc
        if not isinstance(snapshot, dict):
            raise VideoControlError("Não foi possível localizar o vídeo atual.")
        return snapshot

    def _signature(self) -> dict[str, Any]:
        try:
            signature = self._page.evaluate(NAVIGATION_MARKER_SCRIPT)
        except Exception as exc:
            raise VideoControlError("Não foi possível localizar o vídeo atual.") from exc
        if not isinstance(signature, dict):
            raise VideoControlError("Não foi possível localizar o vídeo atual.")
        return {
            "fingerprint": str(signature.get("fingerprint") or ""),
            "videoMarker": str(signature.get("videoMarker") or ""),
            "containerMarker": str(signature.get("containerMarker") or ""),
            "mediaGeneration": int(signature.get("mediaGeneration") or 0),
            "pageUrl": str(signature.get("pageUrl") or ""),
            "probeToken": str(signature.get("probeToken") or ""),
        }

    def _first_visible(self, selectors: Iterable[str]) -> Any | None:
        for selector in selectors:
            try:
                matches = self._page.locator(selector)
                for index in range(matches.count()):
                    candidate = matches.nth(index)
                    if candidate.is_visible():
                        return candidate
            except Exception:
                continue
        return None

    def _click_active_action(self, selectors: Iterable[str]) -> bool:
        try:
            result = self._page.evaluate(
                _active_script(
                    r"""if (!active) return null;
                    const visible = element => {
                        if (!element) return false;
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                            Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
                    };
                    let ancestor = active.video.parentElement;
                    for (let depth = 0; ancestor && ancestor !== document.body && depth < 12; depth++) {
                        const videos = [...ancestor.querySelectorAll('video')];
                        if (videos.some(video => video !== active.video)) break;
                        for (const selector of selectors) {
                            const button = [...ancestor.querySelectorAll(selector)].find(visible);
                            if (button) {
                                button.click();
                                return true;
                            }
                        }
                        ancestor = ancestor.parentElement;
                    }
                    return false;""",
                    "selectors",
                ),
                list(selectors),
            )
        except Exception as exc:
            raise VideoControlError("Não foi possível acionar o controle do vídeo.") from exc
        return result is True

    def _click_active_action_with_state(
        self,
        selectors: Iterable[str],
        undo_label_pattern: str,
        inactive_label_pattern: str,
        mutation_url_patterns: tuple[str, ...] = (),
    ) -> tuple[bool, bool | None]:
        options = {
            "selectors": list(selectors),
            "undoLabelPattern": undo_label_pattern,
            "inactiveLabelPattern": inactive_label_pattern,
        }
        target_script = _active_script(
            r"""if (!active) return null;
            const visible = element => {
                if (!element) return false;
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                    Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
            };
            const clickable = element => element && (
                element.closest('button, [role="button"], input, a[href], [tabindex]') || element
            );
            let ancestor = active.video.parentElement;
            for (let depth = 0; ancestor && ancestor !== document.body && depth < 14; depth++) {
                const videos = [...ancestor.querySelectorAll('video')];
                if (videos.some(video => video !== active.video)) break;
                for (const selector of options.selectors) {
                    const match = [...ancestor.querySelectorAll(selector)].find(visible);
                    const button = clickable(match);
                    if (button && visible(button)) return button;
                }
                ancestor = ancestor.parentElement;
            }
            return null;""",
            "options",
        )

        state_script = r"""(button, options) => {
            if (!button || !button.isConnected) return null;
            const stateElements = [button, ...button.querySelectorAll(
                '[aria-pressed], [aria-checked], [data-state], [data-liked]'
            )];
            for (const element of stateElements) {
                for (const name of ['aria-pressed', 'aria-checked', 'data-liked']) {
                    const value = element.getAttribute(name);
                    if (value === 'true' || value === 'false') return value === 'true';
                }
                const dataState = (element.getAttribute('data-state') || '').toLowerCase();
                if (['on', 'checked', 'active', 'selected'].includes(dataState)) return true;
                if (['off', 'unchecked', 'inactive', 'unselected'].includes(dataState)) return false;
            }
            const label = [
                button.getAttribute('aria-label') || '',
                button.getAttribute('title') || '',
                button.textContent || ''
            ].join(' ').replace(/\s+/g, ' ').trim();
            if (new RegExp(options.undoLabelPattern, 'i').test(label)) return true;
            if (new RegExp(options.inactiveLabelPattern, 'i').test(label)) return false;
            return null;
        }"""

        raw_handle = None
        try:
            raw_handle = self._page.evaluate_handle(target_script, options)
            button = raw_handle.as_element()
            if button is None:
                return False, None
            before = button.evaluate(state_script, options)

            # A interface muda de forma otimista antes que a conta seja alterada.
            # Em uma página real, exija também a resposta da mutação enviada pelo
            # próprio TikTok; páginas sintéticas continuam verificadas pelo DOM.
            hostname = (
                urlsplit(str(getattr(self._page, "url", ""))).hostname or ""
            ).lower()
            require_server_confirmation = hostname == "tiktok.com" or hostname.endswith(
                ".tiktok.com"
            )
            server_confirmed: bool | None = None
            if require_server_confirmation and mutation_url_patterns:
                try:
                    with self._page.expect_response(
                        lambda response: _is_action_mutation_response(
                            response, mutation_url_patterns
                        ),
                        timeout=5_000,
                    ) as response_info:
                        button.click(timeout=3_000)
                    server_confirmed = _server_accepted_mutation(response_info.value)
                except Exception:
                    server_confirmed = False
            else:
                button.click(timeout=3_000)

            expected = not before if isinstance(before, bool) else None
            confirmation_options = {**options, "expected": expected}
            try:
                confirmation = self._page.wait_for_function(
                    _active_script(
                        r"""if (!active) return false;
                        const visible = element => {
                            if (!element) return false;
                            const style = getComputedStyle(element);
                            const rect = element.getBoundingClientRect();
                            return style.display !== 'none' && style.visibility !== 'hidden' &&
                                Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
                        };
                        const readState = button => {
                            const elements = [button, ...button.querySelectorAll(
                                '[aria-pressed], [aria-checked], [data-state], [data-liked]'
                            )];
                            for (const element of elements) {
                                for (const name of ['aria-pressed', 'aria-checked', 'data-liked']) {
                                    const value = element.getAttribute(name);
                                    if (value === 'true' || value === 'false') return value === 'true';
                                }
                                const value = (element.getAttribute('data-state') || '').toLowerCase();
                                if (['on', 'checked', 'active', 'selected'].includes(value)) return true;
                                if (['off', 'unchecked', 'inactive', 'unselected'].includes(value)) return false;
                            }
                            const label = [button.getAttribute('aria-label') || '',
                                button.getAttribute('title') || '', button.textContent || '']
                                .join(' ').replace(/\s+/g, ' ').trim();
                            if (new RegExp(options.undoLabelPattern, 'i').test(label)) return true;
                            if (new RegExp(options.inactiveLabelPattern, 'i').test(label)) return false;
                            return null;
                        };
                        let ancestor = active.video.parentElement;
                        for (let depth = 0; ancestor && ancestor !== document.body && depth < 14; depth++) {
                            const videos = [...ancestor.querySelectorAll('video')];
                            if (videos.some(video => video !== active.video)) break;
                            for (const selector of options.selectors) {
                                const match = [...ancestor.querySelectorAll(selector)].find(visible);
                                const button = match && (match.closest(
                                    'button, [role="button"], input, a[href], [tabindex]'
                                ) || match);
                                if (!button || !visible(button)) continue;
                                const state = readState(button);
                                const confirmed = options.expected === null ?
                                    state !== null : state === options.expected;
                                return confirmed ? {state} : false;
                            }
                            ancestor = ancestor.parentElement;
                        }
                        return false;""",
                        "options",
                    ),
                    arg=confirmation_options,
                    timeout=3_000,
                )
            except Exception:
                return True, None
            try:
                result = confirmation.json_value()
            finally:
                confirmation.dispose()
            after = result.get("state") if isinstance(result, dict) else None
            if isinstance(expected, bool) and after is not expected:
                return True, None
            confirmed = after if isinstance(after, bool) else expected

            # O TikTok pode atualizar o botão de forma otimista e desfazer a
            # alteração quando o servidor rejeita uma sessão expirada. Não
            # anuncie sucesso antes de dar tempo para essa resposta chegar.
            self._page.wait_for_timeout(1_500)
            stable_handle = self._page.evaluate_handle(target_script, options)
            try:
                stable_button = stable_handle.as_element()
                stable = (
                    stable_button.evaluate(state_script, options)
                    if stable_button is not None
                    else None
                )
            finally:
                stable_handle.dispose()
            if not isinstance(confirmed, bool) or stable is not confirmed:
                return True, None
            if require_server_confirmation and server_confirmed is not True:
                return True, None
            return True, confirmed
        except Exception as exc:
            raise VideoControlError("Não foi possível acionar o controle do vídeo.") from exc
        finally:
            if raw_handle is not None:
                try:
                    raw_handle.dispose()
                except Exception:
                    pass

    def _click_visible_global(self, selectors: Iterable[str]) -> bool:
        return bool(
            self._page.evaluate(
                r"""selectors => {
                    const visible = element => {
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                            rect.width > 0 && rect.height > 0;
                    };
                    for (const selector of selectors) {
                        const button = [...document.querySelectorAll(selector)].find(visible);
                        if (button) { button.click(); return true; }
                    }
                    return false;
                }""",
                list(selectors),
            )
        )
