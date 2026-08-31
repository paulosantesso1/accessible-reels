(() => {
  if (globalThis.__accessibleReelsInstalled) return;
  globalThis.__accessibleReelsInstalled = true;

  const wakeBridge = () => {
    try {
      chrome.runtime.sendMessage({type: "accessible-reels-wake"}).catch(() => {});
    } catch (_error) {}
  };
  setInterval(wakeBridge, 1000);
  wakeBridge();

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  let preferredVolume = null;
  let preferredMuted = null;
  const applyingAudio = new WeakSet();
  const watchedVideos = new WeakSet();

  function applyAudioPreference(video) {
    if (!video || preferredVolume === null || applyingAudio.has(video)) return;
    applyingAudio.add(video);
    try {
      video.volume = Math.max(0, Math.min(1, preferredVolume));
      if (preferredMuted === false) {
        video.defaultMuted = false;
        video.removeAttribute("muted");
        video.muted = false;
      } else if (preferredMuted === true) {
        video.muted = true;
      }
    } finally {
      setTimeout(() => applyingAudio.delete(video), 0);
    }
  }

  function watchVideo(video) {
    if (!video || watchedVideos.has(video)) return;
    watchedVideos.add(video);
    video.addEventListener("volumechange", () => {
      if (preferredVolume === null || applyingAudio.has(video)) return;
      const wrongVolume = Math.abs(video.volume - preferredVolume) > 0.005;
      const wrongMute = preferredMuted !== null && video.muted !== preferredMuted;
      if (wrongVolume || wrongMute) queueMicrotask(() => applyAudioPreference(video));
    });
    applyAudioPreference(video);
  }

  function watchAllVideos() {
    document.querySelectorAll("video").forEach(watchVideo);
  }

  new MutationObserver(watchAllVideos).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  watchAllVideos();
  const visible = element => {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
  };

  async function trustedClick(element) {
    if (!element || !element.isConnected) throw new Error("O controle desapareceu da página.");
    element.scrollIntoView({block: "center", inline: "center"});
    await sleep(80);
    const rect = element.getBoundingClientRect();
    const response = await chrome.runtime.sendMessage({
      type: "accessible-reels-trusted-click",
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    });
    if (!response || response.ok !== true) {
      throw new Error(response && response.error ? response.error : "O navegador recusou o clique.");
    }
  }

  function activeVideo() {
    const width = Math.max(document.documentElement.clientWidth, innerWidth || 0);
    const height = Math.max(document.documentElement.clientHeight, innerHeight || 0);
    const candidates = [...document.querySelectorAll("video")].filter(visible).map((video, index) => {
      const rect = video.getBoundingClientRect();
      const intersectionWidth = Math.max(0, Math.min(rect.right, width) - Math.max(rect.left, 0));
      const intersectionHeight = Math.max(0, Math.min(rect.bottom, height) - Math.max(rect.top, 0));
      return {
        video,
        index,
        area: intersectionWidth * intersectionHeight,
        playing: !video.paused && !video.ended ? 1 : 0,
        distance: Math.hypot(rect.left + rect.width / 2 - width / 2,
          rect.top + rect.height / 2 - height / 2)
      };
    });
    candidates.sort((a, b) => b.area - a.area || b.playing - a.playing ||
      a.distance - b.distance || a.index - b.index);
    return candidates[0] ? candidates[0].video : null;
  }

  function ancestorsFor(video) {
    const result = [];
    let ancestor = video && video.parentElement;
    for (let depth = 0; ancestor && ancestor !== document.body && depth < 15; depth++) {
      const videos = [...ancestor.querySelectorAll("video")];
      if (videos.some(item => item !== video)) break;
      result.push(ancestor);
      ancestor = ancestor.parentElement;
    }
    return result;
  }

  function findNearVideo(selectors) {
    const video = activeVideo();
    if (!video) return null;
    for (const ancestor of ancestorsFor(video)) {
      for (const selector of selectors) {
        const match = [...ancestor.querySelectorAll(selector)].find(visible);
        if (match) return match.closest("button, [role=button], a[href], [tabindex]") || match;
      }
    }
    return null;
  }

  function normalizedText(value) {
    return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  }

  function snapshot() {
    const video = activeVideo();
    if (!video) throw new Error("Não foi possível localizar o vídeo atual.");
    const ancestors = ancestorsFor(video);
    const query = selectors => {
      for (const root of ancestors) {
        for (const selector of selectors) {
          const element = root.querySelector(selector);
          const text = normalizedText(element && (element.getAttribute("aria-label") || element.textContent));
          if (text) return text;
        }
      }
      return "";
    };
    let author = query([
      "[data-e2e=video-author-uniqueid]", "[data-e2e=browse-username]",
      "a[href^='/@']", "a[href*='tiktok.com/@']"
    ]);
    if (author && !author.startsWith("@")) author = `@${author}`;
    const description = query([
      "[data-e2e=video-desc]", "[data-e2e=browse-video-desc]",
      "[data-e2e=video-description]"
    ]);
    let link = "";
    for (const root of ancestors) {
      const anchor = root.querySelector("a[href*='/video/']");
      if (anchor) {
        try {
          const url = new URL(anchor.href, location.href);
          url.search = "";
          url.hash = "";
          link = url.href;
          break;
        } catch (_error) {}
      }
    }
    if (!link && location.pathname.includes("/video/")) {
      link = `${location.origin}${location.pathname}`;
    }
    return {
      author: author || "Autor não encontrado",
      description: description || "Descrição não encontrada",
      link
    };
  }

  function readState(button, undoPattern, inactivePattern) {
    if (!button || !button.isConnected) return null;
    const elements = [button, ...button.querySelectorAll(
      "[aria-pressed], [aria-checked], [data-state], [data-liked]"
    )];
    for (const element of elements) {
      for (const name of ["aria-pressed", "aria-checked", "data-liked"]) {
        const value = element.getAttribute(name);
        if (value === "true" || value === "false") return value === "true";
      }
      const state = (element.getAttribute("data-state") || "").toLowerCase();
      if (["on", "checked", "active", "selected"].includes(state)) return true;
      if (["off", "unchecked", "inactive", "unselected"].includes(state)) return false;
    }
    const label = normalizedText([
      button.getAttribute("aria-label") || "", button.getAttribute("title") || "",
      button.textContent || ""
    ].join(" "));
    if (undoPattern.test(label)) return true;
    if (inactivePattern.test(label)) return false;
    return null;
  }

  async function toggleAction(selectors, undoPattern, inactivePattern, missingMessage) {
    let button = findNearVideo(selectors);
    if (!button) throw new Error(missingMessage);
    const before = readState(button, undoPattern, inactivePattern);
    await trustedClick(button);
    const deadline = Date.now() + 3500;
    let after = before;
    while (Date.now() < deadline) {
      await sleep(150);
      button = findNearVideo(selectors) || button;
      after = readState(button, undoPattern, inactivePattern);
      if (typeof after === "boolean" && (typeof before !== "boolean" || after !== before)) break;
    }
    await sleep(1200);
    button = findNearVideo(selectors) || button;
    const stable = readState(button, undoPattern, inactivePattern);
    if (typeof stable !== "boolean" || (typeof before === "boolean" && stable === before)) {
      throw new Error("O TikTok não confirmou a alteração na conta.");
    }
    return stable;
  }

  const LIKE_SELECTORS = [
    "[data-e2e=like-button]", "[data-e2e=like-icon]", "[data-e2e=browse-like-icon]",
    "[role=button][aria-label*='curtir' i]", "[role=button][aria-label*='like' i]",
    "[role=button][aria-label*='descurtir' i]", "[role=button][aria-label*='unlike' i]"
  ];
  const FAVORITE_SELECTORS = [
    "[data-e2e=favorite-button]", "[data-e2e=favorite-icon]", "[data-e2e=collect-icon]",
    "[data-e2e*='collect-icon' i]", "[role=button][aria-label*='favorit' i]",
    "[role=button][aria-label*='favorite' i]"
  ];
  const COMMENT_SELECTORS = [
    "[data-e2e=comment-icon]", "[role=button][aria-label*='coment' i]",
    "[role=button][aria-label*='comment' i]"
  ];

  async function execute(action, argument) {
    const video = activeVideo();
    if (!["diagnostics"].includes(action) && !video) {
      throw new Error("Não foi possível localizar o vídeo atual.");
    }
    if (["author", "description", "copy_link", "refresh_info"].includes(action)) {
      return snapshot();
    }
    if (action === "next" || action === "previous") {
      const selectors = action === "next" ?
        ["button[data-e2e=feed-navigation-next]", "button[data-e2e=arrow-down]"] :
        ["button[data-e2e=feed-navigation-prev]", "button[data-e2e=arrow-up]"];
      const button = [...document.querySelectorAll(selectors.join(","))].find(visible);
      if (button) await trustedClick(button);
      else window.scrollBy({top: (action === "next" ? 1 : -1) * innerHeight * 0.9, behavior: "smooth"});
      await sleep(1400);
      return snapshot();
    }
    if (action === "toggle") {
      if (video.paused) await video.play(); else video.pause();
      return {paused: video.paused};
    }
    if (action === "volume_up" || action === "volume_down") {
      if (preferredVolume === null) preferredVolume = video.volume;
      preferredVolume = Math.max(0, Math.min(1,
        preferredVolume + (action === "volume_up" ? 0.1 : -0.1)));
      preferredMuted = false;
      watchVideo(video);
      applyAudioPreference(video);
      await sleep(100);
      return {volume: preferredVolume};
    }
    if (action === "toggle_mute") {
      if (preferredVolume === null) preferredVolume = video.volume;
      const effectivelyMuted = video.muted || video.volume === 0;
      preferredMuted = !effectivelyMuted;
      if (effectivelyMuted && preferredVolume === 0) preferredVolume = 0.1;
      watchVideo(video);
      applyAudioPreference(video);
      await sleep(100);
      return {muted: preferredMuted};
    }
    if (action === "toggle_like") {
      return {state: await toggleAction(LIKE_SELECTORS, /descurtir|unlike|remove like/i,
        /curtir|like/i, "Não foi possível localizar o botão Curtir.")};
    }
    if (action === "toggle_favorite") {
      return {state: await toggleAction(FAVORITE_SELECTORS,
        /remover dos favoritos|remove from favorites|unfavorite/i,
        /adicionar aos favoritos|favoritar|favorite/i,
        "Não foi possível localizar o botão Favoritar.")};
    }
    if (action === "comments") {
      const button = findNearVideo(COMMENT_SELECTORS);
      if (!button) throw new Error("Não foi possível localizar o botão de comentários.");
      await trustedClick(button);
      await sleep(1200);
      const items = [...document.querySelectorAll(
        "[data-e2e=comment-item], [data-e2e=comment-level-1], [class*='CommentItem']"
      )].filter(visible).map(item => normalizedText(item.innerText)).filter(Boolean);
      return {comments: [...new Set(items)].slice(0, 200)};
    }
    if (action === "post_comment") {
      const text = normalizedText(String(argument || ""));
      if (!text) throw new Error("Digite um comentário antes de publicar.");
      const editor = [...document.querySelectorAll(
        "[data-e2e=comment-input] [contenteditable=true], [contenteditable=true][role=textbox]"
      )].find(visible);
      if (!editor) throw new Error("Abra os comentários antes de escrever.");
      editor.focus();
      editor.textContent = text;
      editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
      await sleep(150);
      const post = [...document.querySelectorAll(
        "button[data-e2e=comment-post], [data-e2e=comment-post], button"
      )].find(element => visible(element) && /publicar|post/i.test(normalizedText(element.textContent)));
      if (!post) throw new Error("Não foi possível localizar o botão Publicar comentário.");
      await trustedClick(post);
      await sleep(900);
      return {};
    }
    if (action === "close_comments") {
      const close = [...document.querySelectorAll(
        "button[aria-label='exit' i], button[data-e2e*='comment-close' i], " +
        "button[aria-label*='fechar' i], button[aria-label*='close' i]"
      )].find(visible);
      if (close) await trustedClick(close);
      return {};
    }
    if (action === "diagnostics") {
      return {message: `Extensão conectada; página ${location.hostname}; ` +
        `${document.querySelectorAll("video").length} vídeo(s); ` +
        `vídeo ativo ${activeVideo() ? "sim" : "não"}.`};
    }
    throw new Error("Comando desconhecido recebido pela extensão.");
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "accessible-reels-command") return false;
    execute(message.action, message.argument)
      .then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error && error.message ? error.message : String(error)}));
    return true;
  });
})();
