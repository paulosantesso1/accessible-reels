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
  const audioScheduleGeneration = new WeakMap();

  function applyAudioPreference(video) {
    if (!video || preferredVolume === null || applyingAudio.has(video)) return;
    applyingAudio.add(video);
    try {
      const targetVolume = Math.max(0, Math.min(1, preferredVolume));
      if (Math.abs(video.volume - targetVolume) > 0.005) video.volume = targetVolume;
      if (preferredMuted === false) {
        video.defaultMuted = false;
        video.removeAttribute("muted");
        if (video.muted) video.muted = false;
      } else if (preferredMuted === true) {
        if (!video.muted) video.muted = true;
      }
    } finally {
      // volumechange is queued by the browser. Releasing the guard now lets a
      // later TikTok reset be corrected instead of being mistaken for our own.
      applyingAudio.delete(video);
    }
  }

  function scheduleAudioPreference(video) {
    if (!video || preferredVolume === null) return;
    const generation = (audioScheduleGeneration.get(video) || 0) + 1;
    audioScheduleGeneration.set(video, generation);
    for (const delay of [0, 40, 120, 350, 900, 1800, 3200]) {
      setTimeout(() => {
        if (audioScheduleGeneration.get(video) !== generation) return;
        applyAudioPreference(video);
      }, delay);
    }
  }

  function stabilizeAudio() {
    if (preferredVolume === null) return;
    document.querySelectorAll("video").forEach(video => {
      applyAudioPreference(video);
      scheduleAudioPreference(video);
    });
  }

  function watchVideo(video) {
    if (!video || watchedVideos.has(video)) return;
    watchedVideos.add(video);
    video.addEventListener("volumechange", () => {
      if (preferredVolume === null) return;
      const wrongVolume = Math.abs(video.volume - preferredVolume) > 0.005;
      const wrongMute = preferredMuted !== null && video.muted !== preferredMuted;
      if (wrongVolume || wrongMute) applyAudioPreference(video);
    });
    for (const eventName of ["play", "playing", "loadedmetadata", "canplay", "emptied"]) {
      video.addEventListener(eventName, () => scheduleAudioPreference(video));
    }
    scheduleAudioPreference(video);
  }

  function watchAllVideos() {
    document.querySelectorAll("video").forEach(watchVideo);
  }

  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === "attributes" && record.target.tagName === "VIDEO") {
        watchVideo(record.target);
        scheduleAudioPreference(record.target);
      }
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.tagName === "VIDEO") watchVideo(node);
        node.querySelectorAll("video").forEach(watchVideo);
      }
    }
  }).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["muted", "src"]
  });
  watchAllVideos();
  // Events normally catch TikTok resets in the same task. This inexpensive
  // fallback repairs silent resets that the site performs without an event.
  setInterval(() => {
    if (preferredVolume === null) return;
    document.querySelectorAll("video").forEach(applyAudioPreference);
  }, 250);
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

  function shortcutAction(event) {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altGraphKey) return null;
    const key = event.key.toLowerCase();
    if (event.altKey && event.shiftKey) {
      if (event.key === "ArrowUp") return "volume_up";
      if (event.key === "ArrowDown") return "volume_down";
      if (key === "m") return "toggle_mute";
      return null;
    }
    if (event.altKey) {
      if (event.key === "ArrowDown") return "next";
      if (event.key === "ArrowUp") return "previous";
      return ({
        p: "toggle",
        a: "author",
        d: "description",
        c: "copy_link",
        f12: "diagnostics"
      })[key] || null;
    }
    if (event.shiftKey) return null;
    if (event.key === "F5") return "refresh_info";
    return ({c: "comments", l: "toggle_like", f: "toggle_favorite"})[key] || null;
  }

  function editableTarget(target) {
    return target instanceof Element && Boolean(target.closest(
      "input, textarea, select, [contenteditable=true], [role=textbox]"
    ));
  }

  function announceShortcut(message) {
    let status = document.getElementById("accessible-reels-shortcut-status");
    if (!status) {
      status = document.createElement("div");
      status.id = "accessible-reels-shortcut-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "assertive");
      status.setAttribute("aria-atomic", "true");
      Object.assign(status.style, {
        position: "fixed",
        width: "1px",
        height: "1px",
        overflow: "hidden",
        clipPath: "inset(50%)",
        whiteSpace: "nowrap"
      });
      (document.body || document.documentElement).appendChild(status);
    }
    status.textContent = "";
    setTimeout(() => { status.textContent = message; }, 0);
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
      stabilizeAudio();
      const selectors = action === "next" ?
        ["button[data-e2e=feed-navigation-next]", "button[data-e2e=arrow-down]"] :
        ["button[data-e2e=feed-navigation-prev]", "button[data-e2e=arrow-up]"];
      const button = [...document.querySelectorAll(selectors.join(","))].find(visible);
      if (button) await trustedClick(button);
      else window.scrollBy({top: (action === "next" ? 1 : -1) * innerHeight * 0.9, behavior: "smooth"});
      stabilizeAudio();
      await sleep(1400);
      stabilizeAudio();
      return snapshot();
    }
    if (action === "toggle") {
      if (video.paused) {
        applyAudioPreference(video);
        await video.play();
        scheduleAudioPreference(video);
      } else video.pause();
      return {paused: video.paused};
    }
    if (action === "volume_up" || action === "volume_down") {
      if (preferredVolume === null) preferredVolume = video.volume;
      preferredVolume = Math.max(0, Math.min(1,
        preferredVolume + (action === "volume_up" ? 0.1 : -0.1)));
      preferredMuted = false;
      watchVideo(video);
      stabilizeAudio();
      await sleep(100);
      return {volume: preferredVolume};
    }
    if (action === "toggle_mute") {
      if (preferredVolume === null) preferredVolume = video.volume;
      const effectivelyMuted = preferredMuted === null ?
        (video.muted || video.volume === 0) : preferredMuted;
      preferredMuted = !effectivelyMuted;
      if (effectivelyMuted && preferredVolume === 0) preferredVolume = 0.1;
      watchVideo(video);
      stabilizeAudio();
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

  document.addEventListener("keydown", event => {
    const action = shortcutAction(event);
    if (!action) return;
    if (editableTarget(event.target) && !event.altKey) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    execute(action)
      .then(async result => {
        if (action === "author") announceShortcut(`Autor: ${result.author}.`);
        else if (action === "description") announceShortcut(`Descrição: ${result.description}`);
        else if (action === "copy_link") {
          if (!result.link) throw new Error("Não foi possível identificar o link do vídeo atual.");
          await navigator.clipboard.writeText(result.link);
          announceShortcut("Link copiado.");
        }
        else if (action === "diagnostics") announceShortcut(result.message);
        else announceShortcut("Comando executado.");
      })
      .catch(error => announceShortcut(
        `Erro: ${error && error.message ? error.message : String(error)}`
      ));
  }, true);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "accessible-reels-command") return false;
    execute(message.action, message.argument)
      .then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error && error.message ? error.message : String(error)}));
    return true;
  });
})();
