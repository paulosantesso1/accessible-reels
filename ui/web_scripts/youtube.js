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
            'a[href^="/@"]', // Tática matadora: qualquer link com /@ no container do vídeo
            'ytd-channel-name',
            '[id="channel-name"]'
        ]);
        if (!author) author = "Autor não encontrado";
        
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
        const queryLink = (selectors) => {
            for (const root of ancestors) {
                for (const sel of selectors) {
                    const elements = root.querySelectorAll(sel);
                    for (const el of elements) {
                        if (el.href) return el.href;
                    }
                }
            }
            return null;
        };
        
        let profile_url = queryLink([
            'ytd-channel-name a',
            '[id="channel-name"] a',
            'a[href^="/@"]'
        ]);
        if (profile_url && !profile_url.endsWith('/shorts')) {
            profile_url = profile_url.replace(/\/$/, '') + '/shorts';
        }

        return { author: author, description: description, link: location.href, profile_url: profile_url };
    }

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    async function execute(action, argument) {
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
            return snapshot();
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
            
            let clicked = false;
            for (const selector of btnSelectors) {
                const btn = document.querySelector(selector);
                if (btn) {
                    btn.click(); // CORREÇÃO 3: Retirada a trava de "visibilidade" para clicar no botão oculto do YT
                    clicked = true;
                    break;
                }
            }

            if (!clicked) {
                // Alternativa infalível: rola a tela se o botão não for encontrado
                window.scrollBy({ top: isNext ? window.innerHeight : -window.innerHeight, behavior: 'smooth' });
            }

            // CORREÇÃO 4: Lógica de espera do TikTok para garantir que os dados atualizem na interface
            const deadline = Date.now() + 4500;
            while (Date.now() < deadline) {
                await sleep(150);
                const current = activeVideo();
                if (current && (current !== video ||
                    (current.currentSrc || current.getAttribute("src")) !== source ||
                    snapshot().link !== link)) {
                        await sleep(400); // Aguarda o DOM do YouTube renderizar os novos textos
                        return snapshot();
                }
            }
            throw new Error("O YouTube não mudou de vídeo a tempo. Tente novamente ou use F6 para acessar a página.");
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
        else if (action === "toggle_favorite") {
            throw new Error("O YouTube Shorts não possui um botão de salvar rápido nativo na tela. Use F6 para abrir opções.");
        }
        
        throw new Error('Ação ainda não implementada no YouTube.');
    }

    transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
        execute(message.action, message.argument)
            .then(result => sendResponse({ok: true, ...result}))
            .catch(error => sendResponse({ok: false, error: error.message}));
        return true;
    });
})();
