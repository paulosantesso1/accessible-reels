(() => {
    // Evita carregar múltiplas vezes e travar a página
    if (globalThis.__accessibleReelsInstalled) return;
    globalThis.__accessibleReelsInstalled = true;
    const transport = globalThis.__accessibleTransport;
    let preferredVolume = null;
    let preferredMuted = null;
    const watchedVideos = new WeakSet();
    const applyingAudio = new WeakSet();
    const audioKeys = {
        volume: "accessibleReelsYouTubeVolume",
        muted: "accessibleReelsYouTubeMuted"
    };

    // Helper para checar visibilidade (relaxado para não barrar botões ocultos do YT)
    const visible = (element) => {
        if (!element) return false;
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
    };

    // Descobre o vídeo principal ativo na tela
    function activeVideo() {
        const videos = [...document.querySelectorAll('video')];
        const width = Math.max(document.documentElement.clientWidth, innerWidth || 0);
        const height = Math.max(document.documentElement.clientHeight, innerHeight || 0);
        
        let bestVideo = null;
        let maxArea = 0;
        
        for (const video of videos) {
            const rect = video.getBoundingClientRect();
            const intersectionWidth = Math.max(0, Math.min(rect.right, width) - Math.max(rect.left, 0));
            const intersectionHeight = Math.max(0, Math.min(rect.bottom, height) - Math.max(rect.top, 0));
            const area = intersectionWidth * intersectionHeight;
            
            if (area > maxArea) {
                maxArea = area;
                bestVideo = video;
            }
        }
        return bestVideo;
    }

    function publishAudio() {
        document.dispatchEvent(new CustomEvent("accessible-reels-volume-preference", {
            detail: JSON.stringify({volume: preferredVolume, muted: preferredMuted})
        }));
    }

    function applyAudioPreference(video) {
        if (!video || preferredVolume === null || applyingAudio.has(video)) return;
        applyingAudio.add(video);
        try {
            if (Math.abs(video.volume - preferredVolume) > 0.005) video.volume = preferredVolume;
            if (preferredMuted !== null && video.muted !== preferredMuted) video.muted = preferredMuted;
        } finally {
            applyingAudio.delete(video);
        }
    }

    function stabilizeAudio() {
        for (const video of document.querySelectorAll("video")) {
            if (!watchedVideos.has(video)) {
                watchedVideos.add(video);
                for (const eventName of ["volumechange", "play", "playing", "loadedmetadata", "canplay"]) {
                    video.addEventListener(eventName, () => applyAudioPreference(video));
                }
            }
            applyAudioPreference(video);
        }
    }

    const audioReady = transport.storage.local.get(Object.values(audioKeys))
        .then(values => {
            if (Number.isFinite(values[audioKeys.volume])) {
                preferredVolume = Math.max(0, Math.min(1, values[audioKeys.volume]));
            }
            if (typeof values[audioKeys.muted] === "boolean") preferredMuted = values[audioKeys.muted];
        })
        .catch(() => {})
        .finally(() => {
            publishAudio();
            stabilizeAudio();
        });
    new MutationObserver(stabilizeAudio).observe(document, {childList: true, subtree: true});
    setInterval(stabilizeAudio, 250);

    function ancestorsFor(node) {
        const ancestors = [];
        let current = node;
        while (current && current.parentElement) {
            current = current.parentElement;
            ancestors.push(current);
        }
        return ancestors;
    }

    function followState(element) {
        if (!element) return null;
        const pressed = element.getAttribute('aria-pressed');
        if (pressed === 'true') return true;
        if (pressed === 'false') return false;
        const value = [
            element.getAttribute('aria-label'), element.getAttribute('title'), element.textContent
        ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim().toLowerCase();
        if (/cancelar inscri[cç][aã]o|\bunsubscribe\b|\binscrito\b|\bsubscribed\b/.test(value)) return true;
        if (/inscrever-se|\bsubscribe\b/.test(value)) return false;
        return null;
    }

    // Tira a "foto" da tela capturando os dados
    function snapshot() {
        const video = activeVideo();
        if (!video) throw new Error("Não foi possível localizar o vídeo atual.");
        
        const ancestors = ancestorsFor(video);
        
        const query = (selectors) => {
            for (const root of ancestors) {
                for (const sel of selectors) {
                    const elements = root.querySelectorAll(sel);
                    for (const el of elements) {
                        const candidate = el.getAttribute("aria-label") || el.getAttribute("alt") || el.innerText || el.textContent || "";
                        const text = candidate.replace(/\s+/g, " ").trim();
                        if (text) return text;
                    }
                }
            }
            return null;
        };

        let author = query([
            'ytd-channel-name a',
            '[id="channel-name"] a',
            'ytd-channel-name',
            '[id="channel-name"]'
        ]);
        
        let description = query([
            'ytd-reel-player-header-renderer h2.title',
            'ytd-reel-player-header-renderer .title',
            'ytd-reel-player-header-renderer yt-formatted-string[class*="title"]',
            'ytd-reel-player-header-renderer .yt-core-attributed-string',
            '[id="caption-text"]',
            '[id="video-title"]'
        ]);
        
        // Tática matadora para a descrição: o YouTube atualiza o nome da aba com o título do vídeo
        if (!description) {
            let docTitle = document.title || "";
            docTitle = docTitle.replace(/\s*-\s*YouTube$/i, "").trim();
            if (docTitle && docTitle.toLowerCase() !== "youtube") {
                description = docTitle;
            } else {
                description = "Descrição não encontrada";
            }
        }
        const channelProfile = (() => {
            for (const root of ancestors) {
                for (const anchor of root.querySelectorAll(
                    'ytd-channel-name a[href], [id="channel-name"] a[href], a[href^="/@"]'
                )) {
                    try {
                        const raw = anchor.getAttribute('href') || '';
                        const candidate = raw.startsWith('/') ? null : new URL(anchor.href, location.href);
                        const pathname = candidate ? candidate.pathname : raw;
                        const trustedHost = !candidate || candidate.hostname === 'youtube.com' ||
                            candidate.hostname.endsWith('.youtube.com');
                        const match = pathname.match(/^\/(\@[A-Za-z0-9._-]+)(?:\/shorts)?\/?$/);
                        if (trustedHost && match) {
                            return {
                                handle: match[1],
                                url: `https://www.youtube.com/${match[1]}/shorts`
                            };
                        }
                    } catch (_error) {
                    }
                }
            }
            return null;
        })();
        if (!author) author = channelProfile?.handle || "Autor não encontrado";
        const profile_url = channelProfile?.url || "";

        return { author: author, description: description, link: location.href, profile_url: profile_url };
    }

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // Best-effort: YouTube's own Shorts player already advances on a real
    // ArrowDown/ArrowUp key press, independent of whichever nav-button
    // markup is in the DOM at the moment (that markup is what the
    // click/scroll fallback below depends on). Never throws.
    async function trustedKeyPress(key) {
        try {
            await transport.runtime.sendMessage({type: "accessible-reels-trusted-key", key});
        } catch (_) {}
    }

    const NOT_INTERESTED = /^(não tenho interesse|não me interessa|não estou interessado|not interested)\b/i;
    function findNotInterestedItem() {
        const matches = [...document.querySelectorAll(
            "[role=menuitem], button, [role=button], li, a, tp-yt-paper-item, ytd-menu-service-item-renderer, yt-list-item-view-model")]
            .filter(el => visible(el) &&
                NOT_INTERESTED.test((el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim()));
        return matches.find(el => !matches.some(other => other !== el && el.contains(other))) || null;
    }
    // Text of every open menu or dialog; a change means the click moved the page to its next step.
    function openPanelsText() {
        return [...document.querySelectorAll("[role=menu], [role=dialog], tp-yt-paper-listbox, yt-dialog, tp-yt-paper-dialog")]
            .filter(visible).map(el => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 300)).join(" ¦ ");
    }
    // Close the reason panel YouTube opens after a mark, trying a close button, Escape and the backdrop.
    async function closePanels(baseline) {
        const attempts = [
            () => {
                const button = [...document.querySelectorAll("[role=dialog] button, yt-dialog button, tp-yt-paper-dialog button, [role=dialog] [role=button]")]
                    .filter(visible).find(el => /^(fechar|close|cancelar|cancel)$/i.test((el.getAttribute("aria-label") || el.textContent || "").trim()));
                if (button) button.click();
                return Boolean(button);
            },
            () => {
                for (const target of [document.activeElement, document.body, document]) {
                    target?.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true}));
                }
                return true;
            },
            () => {
                const backdrop = document.querySelector("tp-yt-iron-overlay-backdrop");
                if (backdrop) backdrop.click();
                return Boolean(backdrop);
            }
        ];
        for (const attempt of attempts) {
            if (!attempt()) continue;
            await sleep(400);
            if (openPanelsText() === baseline) return true;
        }
        return openPanelsText() === baseline;
    }
    // Only ask for a skip when the same Short is still on screen after the mark.
    async function afterMark(video, link, extra = {}) {
        const deadline = Date.now() + 1500;
        while (Date.now() < deadline) {
            await sleep(150);
            if (activeVideo() !== video || snapshot().link !== link) return extra;
        }
        return {...extra, advance: true};
    }
    async function markNotInterested() {
        const video = activeVideo();
        if (!video) throw new Error("Vídeo não encontrado.");
        const container = video.closest('ytd-reel-video-renderer') || video.parentElement;
        const trace = {};
        const baseline = openPanelsText();
        try {
            let item = findNotInterestedItem();
            if (!item) {
                const more = container.querySelector(
                    '#menu-button button, ytd-menu-renderer button, button[aria-label*="Mais ações" i], ' +
                    'button[aria-label*="More actions" i], button[aria-label*="Mais opções" i], button[aria-label*="More options" i]');
                if (!more) throw new Error("Botão de mais opções não encontrado na tela.");
                more.click();
                const deadline = Date.now() + 3000;
                while (!item && Date.now() < deadline) {
                    await sleep(150);
                    item = findNotInterestedItem();
                }
            }
            if (!item) throw new Error("Este vídeo não oferece a opção Não tenho interesse. Use F6 para acessar a página.");
            trace.clicked = `${item.tagName.toLowerCase()}|${(item.getAttribute("aria-label") || item.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60)}`;
            trace.before = openPanelsText();
            const link = snapshot().link;
            item.click();
            const deadline = Date.now() + 3000;
            while (Date.now() < deadline) {
                await sleep(150);
                if (!item.isConnected || !visible(item)) return afterMark(video, link);
                // YouTube may keep a panel open asking for a reason after registering the choice.
                if (openPanelsText() !== trace.before) {
                    const closed = await closePanels(baseline);
                    return afterMark(video, link, closed ? {} : {follow_up: true});
                }
            }
            throw new Error("O YouTube não confirmou a marcação. Confira na página (F6).");
        } catch (error) {
            trace.after = openPanelsText();
            error.details = {trace, controls: [...container.querySelectorAll("button, [role=button], [role=menuitem]")]
                .slice(0, 60).map(el => `${el.tagName.toLowerCase()}|${el.id}|${el.getAttribute("aria-label") || ""}`),
                popups: [...document.querySelectorAll("[role=menu], [role=dialog], tp-yt-paper-listbox")]
                    .filter(visible).map(el => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120))};
            document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
            throw error;
        }
    }

    // Liked Shorts. The "Vídeos com Gostei" playlist mixes every liked video and
    // YouTube's own Shorts filter only covers its first ~50 items, so the whole
    // playlist is scanned: videos of up to three minutes are candidates, and a
    // HEAD request to /shorts/ID tells a real Short (200) from a regular video
    // (redirect). One short step per call; the page keeps the state, so the
    // caller can poll while the list is already in use.
    const LIBRARY_LIMIT = 500;
    const LIBRARY_SCAN_LIMIT = 6000;
    const SHORT_MAX_SECONDS = 180;
    const CLASSIFY_PER_STEP = 24;
    const CLASSIFY_PARALLEL = 6;

    function durationSeconds(text) {
        const parts = (text || "").split(":").map(Number);
        if (parts.some(Number.isNaN)) return null;
        return parts.length === 2 ? parts[0] * 60 + parts[1]
            : parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : null;
    }

    async function isShort(id) {
        try {
            const response = await fetch(`/shorts/${id}`, {method: "HEAD", redirect: "manual", credentials: "include"});
            return response.type === "basic" && response.status === 200;
        } catch (_error) {
            return null;
        }
    }

    async function libraryStep(kind) {
        if (kind !== "liked") throw new Error("Lista desconhecida.");
        let state = window.__accessibleLibrary;
        if (!state || state.kind !== kind) {
            state = window.__accessibleLibrary = {
                kind, seen: new Set(), order: 0, queue: [], shorts: new Map(), idle: 0, started: Date.now()
            };
        }
        const rows = () => [...document.querySelectorAll("yt-lockup-view-model, ytd-playlist-video-renderer")];
        // The playlist may need a moment to render; no cards at all means no access to it.
        while (!rows().length && Date.now() - state.started < 20000) await sleep(250);
        if (!rows().length) throw new Error("Não encontrei os vídeos que você curtiu. Verifique se está logado no YouTube (F6).");
        const before = state.seen.size;
        for (const row of rows()) {
            const href = (row.querySelector('a[href*="watch?v="]') || {getAttribute: () => ""}).getAttribute("href") || "";
            const id = (href.match(/[?&]v=([A-Za-z0-9_-]{11})/) || [])[1];
            if (!id || state.seen.has(id)) continue;
            state.seen.add(id);
            const seconds = durationSeconds(((row.innerText || "").match(/\b\d{1,2}:\d{2}(?::\d{2})?\b/) || [""])[0]);
            const heading = row.querySelector("h3, #video-title");
            const title = (heading ? heading.innerText || heading.getAttribute("title") : "").trim();
            const index = state.order++;
            if (seconds !== null && seconds <= SHORT_MAX_SECONDS) state.queue.push({index, id, title, tries: 0});
        }
        const batch = state.queue.splice(0, CLASSIFY_PER_STEP);
        for (let at = 0; at < batch.length; at += CLASSIFY_PARALLEL) {
            const group = batch.slice(at, at + CLASSIFY_PARALLEL);
            const verdicts = await Promise.all(group.map(item => isShort(item.id)));
            group.forEach((item, position) => {
                if (verdicts[position] === true) {
                    state.shorts.set(item.index, {
                        url: `https://www.youtube.com/shorts/${item.id}`, author: "", description: item.title
                    });
                } else if (verdicts[position] === null && ++item.tries < 3) {
                    state.queue.push(item);
                }
            });
        }
        if (state.seen.size > before || state.queue.length) state.idle = 0; else state.idle += 1;
        const done = state.shorts.size >= LIBRARY_LIMIT || state.seen.size >= LIBRARY_SCAN_LIMIT ||
            (state.idle >= 5 && !state.queue.length);
        if (!done) {
            // The playlist loads its next page when the last card reaches the viewport.
            const all = rows();
            if (all.length) all[all.length - 1].scrollIntoView({block: "end"});
            window.scrollBy(0, window.innerHeight);
            await sleep(700);
        }
        const results = [...state.shorts.entries()].sort((a, b) => a[0] - b[0])
            .map(entry => entry[1]).slice(0, LIBRARY_LIMIT);
        return {results, library: kind, done, scanned: state.seen.size};
    }

    async function execute(action, argument) {
        if (action === "library_step") return libraryStep(argument);
        if (action === "play" || action === "toggle") {
            let video = activeVideo();
            if (action === "play") {
                const deadline = Date.now() + 8000;
                while (!video && Date.now() < deadline) {
                    await sleep(150);
                    video = activeVideo();
                }
            }
            if (!video) throw new Error("Vídeo não encontrado.");
            if (video.paused) await video.play();
            else if (action === "toggle") video.pause();
            // CORREÇÃO 1: Retorna o estado real de pausa para o Python anunciar corretamente!
            return { paused: video.paused };
        } 
        else if (action === "seek") {
            // CORREÇÃO 2: Implementada a ação de avançar/voltar no tempo (Alt+Setas)
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            video.currentTime += argument;
            return { position: video.currentTime };
        }
        else if (action === "volume_up" || action === "volume_down") {
            await audioReady;
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            if (preferredVolume === null) preferredVolume = video.volume;
            const silent = video.muted || preferredMuted === true || preferredVolume === 0;
            const base = silent ? 0 : preferredVolume;
            preferredVolume = Math.max(0, Math.min(100,
                Math.round(base * 100) + (action === "volume_up" ? 5 : -5))) / 100;
            preferredMuted = false;
            applyAudioPreference(video);
            publishAudio();
            await transport.storage.local.set({
                [audioKeys.volume]: preferredVolume,
                [audioKeys.muted]: preferredMuted
            });
            return { volume: preferredVolume, muted: preferredMuted };
        }
        else if (action === "toggle_mute") {
            await audioReady;
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            if (preferredVolume === null) preferredVolume = video.volume;
            const effectivelyMuted = preferredMuted === null ?
                (video.muted || video.volume === 0) : preferredMuted;
            preferredMuted = !effectivelyMuted;
            if (!preferredMuted && preferredVolume === 0) preferredVolume = 0.05;
            applyAudioPreference(video);
            publishAudio();
            await transport.storage.local.set({
                [audioKeys.volume]: preferredVolume,
                [audioKeys.muted]: preferredMuted
            });
            return { muted: preferredMuted };
        }
        else if (action === "speed_up" || action === "speed_down") {
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            const speeds = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
            const current = Number.isFinite(video.playbackRate) ? video.playbackRate : 1;
            const index = speeds.findIndex(speed => speed >= current - 0.001);
            const base = index === -1 ? speeds.length - 1 : index;
            const next = Math.max(0, Math.min(speeds.length - 1, base + (action === "speed_up" ? (speeds[base] <= current + 0.001 ? 1 : 0) : -1)));
            video.playbackRate = speeds[next];
            return { playbackRate: video.playbackRate };
        }
        else if (action === "comments") {
            try {
                const btn = document.querySelector('ytd-button-renderer#comments-button button, [aria-label*="coment" i], [aria-label*="comment" i]');
                if (!btn) throw new Error("Não foi possível localizar o botão de comentários.");
                btn.click();
                
                // Espera abrir
                let deadline = Date.now() + 3000;
                while (Date.now() < deadline) {
                    await sleep(300);
                    if (document.querySelector('ytd-comment-thread-renderer')) break;
                }
                
                const seen = new Set();
                const results = [];
                const threads = document.querySelectorAll('ytd-comment-thread-renderer, ytd-comment-renderer');
                for (const item of threads) {
                    const authorEl = item.querySelector('#author-text');
                    const contentEl = item.querySelector('#content-text');
                    const text = (authorEl ? authorEl.innerText.trim() + ": " : "") + (contentEl ? contentEl.innerText.trim() : "");
                    if (text && !seen.has(text)) {
                        seen.add(text);
                        const id = "yt-comment-" + seen.size;
                        results.push({id: id, text: text.replace(/\s+/g, " ")});
                    }
                }
                return { comments: results.slice(0, 100) };
            } finally {
                const closeBtn = document.querySelector('ytd-engagement-panel-section-list-renderer[visibility="ENGAGEMENT_PANEL_VISIBILITY_EXPANDED"] #visibility-button button, [aria-label*="fechar" i], [aria-label*="close" i]');
                if (closeBtn) closeBtn.click();
            }
        }
        else if (action === "close_comments") {
            const closeBtn = document.querySelector('ytd-engagement-panel-section-list-renderer[visibility="ENGAGEMENT_PANEL_VISIBILITY_EXPANDED"] #visibility-button button, [aria-label*="fechar" i], [aria-label*="close" i]');
            if (closeBtn) closeBtn.click();
            return {};
        }
        else if (action === "collect_search_results") {
            const deadline = Date.now() + 12000;
            const collected = new Map();
            let firstResultAt = 0;
            let lastGrowthAt = 0;
            let profileScrolls = 0;
            const collectingProfile = argument === "profile";
            const collectingMore = argument?.mode === "more";
            const requiredSearchScrolls = collectingMore ? 12 : 8;
            do {
                const results = [];
                const seen = new Set();
                // Current Shorts cards may use relative or absolute links.
                const anchors = document.querySelectorAll('a[href]');
                for (const anchor of anchors) {
                    let url;
                    try { url = new URL(anchor.href, location.href); } catch (e) { continue; }
                    const match = url.pathname.match(/^\/shorts\/([a-zA-Z0-9_-]{11})/);
                    if (!match || seen.has(match[1])) continue;
                    seen.add(match[1]);
                    
                    const container = anchor.closest('ytd-video-renderer, ytd-reel-item-renderer, ytd-rich-item-renderer, ytd-rich-grid-media, ytd-compact-video-renderer, ytm-shorts-lockup-view-model') || anchor.parentElement;
                    const titleEl = container && (container.querySelector('#video-title') || container.querySelector('.title') || container.querySelector('[id="video-title"]') || container.querySelector('h3 a[title]'));
                    const authorEl = container && (container.querySelector('ytd-channel-name') || container.querySelector('.ytd-channel-name') || container.querySelector('#channel-name'));
                    
                    const titleStr = titleEl ? (titleEl.getAttribute('title') || titleEl.innerText || titleEl.textContent || "").trim() : "";
                    const authorStr = authorEl ? (authorEl.innerText || authorEl.textContent || "").trim() : "";
                    const descFallback = anchor.getAttribute('title') || anchor.getAttribute('aria-label') || "";
                    
                    results.push({
                        url: `https://www.youtube.com/shorts/${match[1]}`,
                        author: authorStr,
                        description: titleStr || descFallback || "Sem título"
                    });
                    if (results.length >= 50) break;
                }
                const before = collected.size;
                for (const item of results) collected.set(item.url, item);
                const now = Date.now();
                if (collected.size && !firstResultAt) firstResultAt = now;
                if (collected.size > before) lastGrowthAt = now;
                const settledSearch = firstResultAt && profileScrolls >= requiredSearchScrolls && now - lastGrowthAt >= 1200;
                const settledProfile = firstResultAt && profileScrolls >= 5 && now - lastGrowthAt >= 1200;
                if (collected.size >= 50 || (collectingProfile ? settledProfile : settledSearch)) {
                    return { results: [...collected.values()] };
                }
                if (collected.size) {
                    window.scrollBy(0, window.innerHeight);
                    profileScrolls += 1;
                }
                await sleep(300);
            } while (Date.now() < deadline);
            return { results: [...collected.values()] };
        }
        else if (action === "author" || action === "description" || action === "copy_link" || action === "refresh_info" || action === "download_link") {
            const info = snapshot();
            if (action === "author") {
                let followStatus = " (Não foi possível verificar se você segue)";
                const videoForAuthor = activeVideo();
                if (videoForAuthor) {
                    const container = videoForAuthor.closest('ytd-reel-video-renderer') || videoForAuthor.parentElement;
                    if (container) {
                        const subBtn = container.querySelector('#subscribe-button button, ytd-subscribe-button-renderer button');
                        if (subBtn) {
                            const state = followState(subBtn);
                            if (state === true) followStatus = " (Você já segue)";
                            else if (state === false) followStatus = " (Não segue)";
                        }
                    }
                }
                info.author += followStatus;
            }
            return info;
        }
        else if (action === "diagnostics") {
            return { message: "Página do YouTube conectada." };
        }
        else if (action === "next" || action === "previous") {
            const video = activeVideo();
            const source = video ? (video.currentSrc || video.getAttribute("src")) : null;
            const link = snapshot().link;

            const isNext = action === "next";
            const btnSelectors = isNext
                ? ['#navigation-button-down button', '#navigation-button-down', '[aria-label="Próximo vídeo"]']
                : ['#navigation-button-up button', '#navigation-button-up', '[aria-label="Vídeo anterior"]'];

            const triggerNavClick = () => {
                for (const selector of btnSelectors) {
                    const btn = document.querySelector(selector);
                    if (btn) {
                        btn.click(); // CORREÇÃO 3: Retirada a trava de "visibilidade" para clicar no botão oculto do YT
                        return;
                    }
                }
                // Alternativa infalível: rola a tela se o botão não for encontrado
                window.scrollBy({ top: isNext ? window.innerHeight : -window.innerHeight, behavior: 'smooth' });
            };
            const moved = candidate => candidate && (candidate !== video ||
                (candidate.currentSrc || candidate.getAttribute("src")) !== source ||
                snapshot().link !== link);

            // Try a real key press first -- YouTube's own Shorts player
            // already advances on ArrowDown/ArrowUp, independent of the
            // nav-button markup the click/scroll fallback below depends on.
            await trustedKeyPress(isNext ? "ArrowDown" : "ArrowUp");
            let triedClick = false;
            // CORREÇÃO 4: Lógica de espera do TikTok para garantir que os dados atualizem na interface
            const deadline = Date.now() + 4500;
            while (Date.now() < deadline) {
                await sleep(150);
                const current = activeVideo();
                if (!moved(current)) {
                    if (!triedClick && Date.now() >= deadline - 3000) {
                        triedClick = true;
                        triggerNavClick();
                    }
                    continue;
                }
                // A rolagem pode ainda estar animando; espera o feed parar
                // e o DOM do YouTube renderizar os novos textos.
                let previous = null, steady = 0;
                const settleBy = deadline + 1500;
                while (Date.now() < settleBy && steady < 3) {
                    await sleep(150);
                    const active = activeVideo();
                    const state = active && {active, top: Math.round(active.getBoundingClientRect().top),
                        source: active.currentSrc || active.getAttribute("src")};
                    steady = state && previous && state.active === previous.active &&
                        state.top === previous.top && state.source === previous.source ? steady + 1 : 0;
                    previous = state;
                }
                if (moved(activeVideo())) return snapshot();
            }
            throw new Error("O YouTube não mudou de vídeo a tempo. Tente novamente ou use F6 para acessar a página.");
        }

        else if (action === "toggle_follow") {
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            const container = video.closest('ytd-reel-video-renderer') || video.parentElement;
            const btn = container.querySelector('#subscribe-button button, ytd-subscribe-button-renderer button');
            if (!btn) throw new Error("Botão de Inscrever-se não encontrado na tela.");
            
            const beforeIsFollowing = followState(btn);
            if (beforeIsFollowing === null) {
                throw new Error("Não foi possível verificar o estado do botão Inscrever-se. Use F6 para confirmar na página.");
            }
            btn.click();
            
            const deadline = Date.now() + 3500;
            let afterIsFollowing = beforeIsFollowing;
            while (Date.now() < deadline) {
                await sleep(150);
                const state = followState(btn);
                if (state !== null) afterIsFollowing = state;
                
                if (afterIsFollowing !== beforeIsFollowing) break;
            }
            if (afterIsFollowing === beforeIsFollowing) {
                throw new Error("A rede não confirmou a alteração de inscrição. Tente novamente.");
            }
            return { state: afterIsFollowing };
        }
        else if (action === "toggle_like") {
            const video = activeVideo();
            if (!video) throw new Error("Vídeo não encontrado.");
            const container = video.closest('ytd-reel-video-renderer') || video.parentElement;
            
            const likeBtn = container.querySelector('#like-button button, [aria-label*="Gostei" i], [aria-label*="like" i]');
            if (likeBtn) {
                likeBtn.click();
                await sleep(200); // Aguarda o YouTube atualizar o estado do botão
                const isLiked = likeBtn.getAttribute('aria-pressed') === 'true' || likeBtn.classList.contains('style-default-active');
                // CORREÇÃO 5: Retorna o estado correto para o Python falar "Curtida adicionada"
                return { state: isLiked };
            }
            throw new Error("Botão de curtir não encontrado na tela.");
        }
        else if (action === "not_interested") {
            return markNotInterested();
        }
        else if (action === "toggle_favorite") {
            throw new Error("O YouTube Shorts não possui um botão de salvar rápido nativo na tela. Use F6 para abrir opções.");
        }
        
        throw new Error('Ação ainda não implementada no YouTube.');
    }

    transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
        execute(message.action, message.argument)
            .then(result => sendResponse({ok: true, ...result}))
            .catch(error => sendResponse({ok: false, error: error.message, details: error.details}));
        return true;
    });
})();
