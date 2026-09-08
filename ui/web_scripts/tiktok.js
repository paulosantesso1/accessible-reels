(() => {
  if (globalThis.__accessibleReelsInstalled) return;
  globalThis.__accessibleReelsInstalled = true;

  const transport = globalThis.__accessibleTransport;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  let preferredVolume = null;
  let preferredMuted = null;
  let commentsVideo = null;
  let lastActiveVideo = null;
  let lastActiveSource = "";
  const applyingAudio = new WeakSet();
  const watchedVideos = new WeakSet();
  const audioScheduleGeneration = new WeakMap();

  function publishAudioPreference() {
    document.dispatchEvent(new CustomEvent("accessible-reels-volume-preference", {
      detail: JSON.stringify({volume: preferredVolume, muted: preferredMuted})
    }));
  }

  async function restoreAudioPreference() {
    try {
      const stored = await transport.storage.local.get([
        "accessibleReelsVolume", "accessibleReelsMuted"
      ]);
      if (Number.isFinite(stored.accessibleReelsVolume)) {
        preferredVolume = Math.max(0, Math.min(1, stored.accessibleReelsVolume));
      }
      if (typeof stored.accessibleReelsMuted === "boolean") {
        preferredMuted = stored.accessibleReelsMuted;
      }
    } catch (_error) {
      // Mesmo sem acesso ao armazenamento, libera a proteção no mundo da página
      // com o estado neutro para não interferir na reprodução.
    } finally {
      publishAudioPreference();
      stabilizeAudio();
    }
  }

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
  // Em document_start, documentElement ainda pode não existir. O próprio
  // Document já recebe todas as inserções posteriores, inclusive a raiz HTML.
  }).observe(document, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["muted", "src"]
  });
  watchAllVideos();
  restoreAudioPreference();
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

  async function trustedClick(element, scroll = true) {
    if (!element || !element.isConnected) throw new Error("O controle desapareceu da página.");
    if (scroll) element.scrollIntoView({block: "center", inline: "center"});
    await sleep(80);
    const rect = element.getBoundingClientRect();
    const response = await transport.runtime.sendMessage({
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
    const videos = [...document.querySelectorAll("video")];
    const candidates = videos.filter(visible).map((video, index) => {
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
    }).filter(candidate => candidate.area > 0);
    candidates.sort((a, b) => b.area - a.area || b.playing - a.playing ||
      a.distance - b.distance || a.index - b.index);
    // Some players render through a canvas while the media element itself has
    // no visible box. Keep controls connected to that media, including after
    // pause, but never fall back to an arbitrary preloaded video.
    const playing = videos.filter(video => !video.paused && !video.ended);
    const remembered = lastActiveVideo && lastActiveVideo.isConnected &&
      lastActiveVideo.currentSrc === lastActiveSource ? lastActiveVideo : null;
    const selected = candidates[0]?.video ||
      playing.find(video => !video.muted && video.volume > 0) || playing[0] || remembered;
    lastActiveVideo = selected || null;
    lastActiveSource = selected?.currentSrc || "";
    return lastActiveVideo;
  }
  let initialPlaybackReleased = false;
  function startInitialPlaybackWhenReady() {
    const deadline = Date.now() + 12000;
    const probe = () => {
      if (initialPlaybackReleased) return;
      const video = activeVideo();
      if (!video || !video.currentSrc || video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
        if (Date.now() < deadline) setTimeout(probe, 150);
        return;
      }
      const source = video.currentSrc;
      video.pause();
      setTimeout(() => {
        const current = activeVideo();
        if (current === video && current.currentSrc === source &&
            current.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
          initialPlaybackReleased = true;
          applyAudioPreference(video);
          video.play().catch(() => {});
        } else if (Date.now() < deadline) probe();
      }, 750);
    };
    probe();
  }
  setTimeout(startInitialPlaybackWhenReady, 0);

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

  async function copyLinkFromTikTok(video) {
    const share = findNearVideo([
      "[data-e2e=share-button]", "[data-e2e=browse-share-icon]", "[data-e2e*=share-icon i]",
      "[role=button][aria-label*='compartilhar' i]", "[role=button][aria-label*='share' i]"
    ]);
    if (!share) throw new Error("O TikTok não disponibilizou o botão Compartilhar deste vídeo.");
    await trustedClick(share);
    const copySelectors = [
      "[data-e2e=copy-link]", "[data-e2e*=copy-link i]",
      "[data-testid*=copy-link i]", "[title*='copiar' i][title*='link' i]",
      "[title*='copy' i][title*='link' i]", "[aria-label*='copiar' i][aria-label*='link' i]",
      "[aria-label*='copy' i][aria-label*='link' i]"
    ];
    const labelsCopyLink = value => /\b(copiar|copy)\b[\s\S]*\b(link|ligação)\b/i.test(normalizedText(value));
    const isCopyText = value => /^(copiar|copy)(?:\s+(?:o|the))?\s+(?:video\s+)?(link|ligação)(?:\s+.*)?$/i
      .test(normalizedText(value));
    const interactive = "button, [role=button], [role=menuitem], a[href], [tabindex]";
    const allElements = () => {
      const result = [];
      const collect = root => {
        for (const element of root.querySelectorAll("*")) {
          result.push(element);
          if (element.shadowRoot) collect(element.shadowRoot);
        }
      };
      collect(document);
      return result;
    };
    const itemLabel = element => normalizedText([
      element.getAttribute("aria-label"), element.getAttribute("title"),
      element.getAttribute("data-e2e"), element.getAttribute("data-testid"),
      element.innerText, element.textContent
    ].filter(Boolean).join(" "));
    const findCopy = () => allElements().find(element => visible(element) &&
      (element.matches(copySelectors.join(",")) ||
       (element.matches(interactive) && labelsCopyLink(itemLabel(element))))) || (() => {
        const textItem = allElements().find(element => visible(element) &&
          isCopyText(element.innerText || element.textContent));
        return textItem && (textItem.closest(interactive) || textItem);
      })();
    const scrollSharePanel = () => {
      let changed = false;
      const roots = [...document.querySelectorAll("[role=dialog], [role=menu], [data-e2e=share-group]")]
        .filter(visible);
      for (const root of roots) {
        for (const element of [root, ...root.querySelectorAll("*")]) {
          if (!visible(element) ||
            element.scrollHeight <= element.clientHeight + 4) continue;
          const next = Math.min(element.scrollTop + Math.max(120, element.clientHeight * 0.8),
            element.scrollHeight - element.clientHeight);
          if (next > element.scrollTop) {
            element.scrollTop = next;
            changed = true;
          }
        }
      }
      return changed;
    };
    const expandShareOptions = async () => {
      const group = [...document.querySelectorAll("[data-e2e=share-group]")].find(visible);
      if (!group) return false;
      let root = group.parentElement;
      for (let depth = 0; root && root !== document.body && depth < 8; depth++, root = root.parentElement) {
        if (root.querySelector("button[aria-label=close i]")) break;
      }
      if (!root || root === document.body) return false;
      const more = [...root.querySelectorAll("button")].find(button => visible(button) &&
        !/^close$/i.test(normalizedText(button.getAttribute("aria-label"))) &&
        !normalizedText(button.getAttribute("title")) && !normalizedText(button.getAttribute("data-testid")) &&
        !normalizedText(button.innerText || button.textContent));
      if (!more) return false;
      await trustedClick(more, false);
      await sleep(250);
      return [...document.querySelectorAll("[data-e2e=share-group]")].some(visible) ? "expanded" : "copied";
    };
    const deadline = Date.now() + 6000;
    let copy;
    let shareOptionsExpanded = false;
    while (Date.now() < deadline) {
      copy = findCopy();
      if (copy) break;
      if (!shareOptionsExpanded) {
        shareOptionsExpanded = true;
        const expansion = await expandShareOptions();
        if (expansion === "copied") return {nativeCopied: true};
        if (expansion === "expanded") {
          await sleep(150);
          continue;
        }
      }
      scrollSharePanel();
      await sleep(100);
    }
    if (!copy) throw new Error("O TikTok não mostrou a opção Copiar link.");
    await trustedClick(copy);
    // TikTok writes the address to the system clipboard itself. Do not read it
    // back: browser clipboard permissions are not consistently available here.
    return {nativeCopied: true};
  }

  function sharePanelDiagnostics() {
    const panels = [...document.querySelectorAll("[role=dialog], [role=menu], [data-e2e*=share i]")]
      .filter(visible);
    const controls = panels.flatMap(panel => [...panel.querySelectorAll(
      "button, [role=button], [role=menuitem], [data-e2e], [data-testid]"
    )]).filter(visible).slice(0, 20).map(element => {
      const role = element.getAttribute("role");
      const e2e = element.getAttribute("data-e2e");
      const testId = element.getAttribute("data-testid");
      return element.tagName.toLowerCase() + (role ? `[role=${role}]` : "") +
        (e2e ? `[data-e2e=${/^share-(?!group|avatar$)/.test(e2e) ? "recipient" : e2e}]` : "") +
        (testId ? `[data-testid=${testId}]` : "");
    });
    const buttons = panels.flatMap(panel => [...panel.querySelectorAll("button")]).filter(visible)
      .slice(0, 8).map(button => {
        const aria = normalizedText(button.getAttribute("aria-label"));
        const title = normalizedText(button.getAttribute("title"));
        const testId = normalizedText(button.getAttribute("data-testid"));
        return `button[aria=${aria || "vazio"}; title=${title || "vazio"}; data-testid=${testId || "vazio"}]`;
      });
    return `painel de compartilhamento ${panels.length ? "visível" : "não visível"}; ` +
      `${controls.length} controle(s) estrutural(is): ${controls.join(", ") || "nenhum"}; ` +
      `botões: ${buttons.join(", ") || "nenhum"}.`;
  }

  function canonicalLink(value) {
    try {
      const url = new URL(value, location.href);
      const match = url.pathname.match(/^\/@[^/?#]+\/video\/(\d+)\/?$/);
      if (url.protocol !== "https:" || !["www.tiktok.com", "tiktok.com"].includes(url.hostname) ||
          url.username || url.password || url.port || !match) return "";
      return `https://www.tiktok.com${url.pathname}`;
    } catch (_error) { return ""; }
  }

  function videoIdFromActiveCard(video, ancestors) {
    const dataValues = [
      video?.dataset?.videoId,
      ...ancestors.flatMap(root => [
        root.dataset.videoId,
        root.getAttribute("data-video-id")
      ])
    ];
    for (const value of dataValues) {
      if (/^\d+$/.test(value || "")) return value;
    }
    for (const root of ancestors) {
      const value = root.id;
      // O feed atual envolve o vídeo em, por exemplo,
      // #xgwrapper-0-7667796792532094209. Esse é o ID público do vídeo,
      // embora o card não exponha data-video-id nem uma âncora /video/.
      const match = String(value || "").match(/^xgwrapper-\d+-(\d{15,22})$/i);
      if (match) return match[1];
    }
    return "";
  }

  function stateVideoLink(author, description) {
    const handle = normalizedText(author).match(/@([A-Za-z0-9._-]{1,24})/)?.[1] ||
      normalizedText(author).match(/^([A-Za-z0-9._-]{1,24})$/)?.[1] || "";
    const expectedDescription = normalizedText(description);
    if (!handle || !expectedDescription || /^descrição não encontrada$/i.test(expectedDescription)) return "";
    const scripts = [...document.querySelectorAll(
      "script#__UNIVERSAL_DATA_FOR_REHYDRATION__, script#SIGI_STATE, script[type='application/json']"
    )];
    for (const script of scripts) {
      let root;
      try { root = JSON.parse(script.textContent || ""); } catch (_error) { continue; }
      const pending = [root];
      const visited = new WeakSet();
      while (pending.length) {
        const value = pending.pop();
        if (!value || typeof value !== "object" || visited.has(value)) continue;
        visited.add(value);
        if (Array.isArray(value)) {
          pending.push(...value);
          continue;
        }
        const videoId = String(value.id || value.itemId || value.aweme_id || "");
        const authorHandle = normalizedText(
          value.author?.uniqueId || value.author?.unique_id || value.authorUniqueId || ""
        ).replace(/^@/, "");
        const candidateDescription = normalizedText(value.desc || value.description || "");
        if (/^\d+$/.test(videoId) && authorHandle === handle && candidateDescription &&
            (candidateDescription === expectedDescription || candidateDescription.includes(expectedDescription) ||
             expectedDescription.includes(candidateDescription))) {
          return canonicalLink(`https://www.tiktok.com/@${authorHandle}/video/${videoId}`);
        }
        pending.push(...Object.values(value));
      }
    }
    return "";
  }

  function shortcutAction(event) {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altGraphKey) return null;
    const key = event.key.toLowerCase();
    if (event.altKey && event.shiftKey) {
      if (event.key === "ArrowUp") return "volume_up";
      if (event.key === "ArrowDown") return "volume_down";
      if (key === "m") return "toggle_mute";
      if (key === "c") return "comments";
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
    return ({l: "toggle_like", f: "toggle_favorite"})[key] || null;
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
      link = anchor ? canonicalLink(anchor.href) : "";
      if (link) break;
    }
    link ||= canonicalLink(location.href);
    if (!link) {
      const profile = ancestors.map(root => root.querySelector("a[href^='/@'], a[href*='tiktok.com/@']"))
        .find(Boolean);
      let handle = "";
      try {
        const profilePath = profile && new URL(profile.href, location.href).pathname;
        handle = profilePath?.match(/^\/@([A-Za-z0-9._-]+)\/?$/)?.[1] || "";
      } catch (_error) {}
      // O feed atual pode expor o @autor em texto acessível, sem um link de
      // perfil ao redor. Ele ainda pertence ao mesmo vídeo já selecionado.
      handle ||= author.match(/@([A-Za-z0-9._-]{1,24})/)?.[1] ||
        author.match(/^([A-Za-z0-9._-]{1,24})$/)?.[1] || "";
      const videoId = videoIdFromActiveCard(video, ancestors);
      if (handle && videoId) link = `https://www.tiktok.com/@${handle}/video/${videoId}`;
    }
    link ||= stateVideoLink(author, description);
    return {
      author: author || "Autor não encontrado",
      description: description || "Descrição não encontrada",
      link
    };
  }

  function collectSearchResults() {
    const results = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll("a[href*='/video/']")) {
      let url;
      try { url = new URL(anchor.href, location.href); } catch (_error) { continue; }
      const match = url.pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
      if (!match || seen.has(match[0])) continue;
      seen.add(match[0]);
      const container = anchor.closest(
        "[data-e2e=search-card-video-container], [data-e2e=user-post-item], li"
      ) || anchor.parentElement;
      const image = anchor.querySelector("img") || (container && container.querySelector("img"));
      const description = normalizedText(
        (image && (image.alt || image.getAttribute("aria-label"))) ||
        anchor.getAttribute("aria-label") || anchor.title ||
        (container && container.innerText) || ""
      );
      results.push({
        url: `https://www.tiktok.com/${match[1]}/video/${match[2]}`,
        author: decodeURIComponent(match[1]),
        description
      });
      if (results.length >= 50) break;
    }
    return {results};
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
  function commentRows() {
    const seen = new Set();
    return [...document.querySelectorAll(
      "[data-e2e=comment-item], [data-e2e=comment-level-1], [class*='CommentItem']"
    )].filter(visible).map(item => {
      const text = normalizedText(item.innerText);
      if (!text || seen.has(text)) return null;
      seen.add(text);
      const id = item.getAttribute("data-accessible-reels-comment-id") || `accessible-reels-comment-${seen.size}`;
      item.setAttribute("data-accessible-reels-comment-id", id);
      return {id, text};
    }).filter(Boolean).slice(0, 200);
  }
  async function openComments(video) {
    const button = findNearVideo(COMMENT_SELECTORS);
    if (!button) throw new Error("Não foi possível localizar o botão de comentários.");
    await trustedClick(button);
    await sleep(1200);
    commentsVideo = {video, source: video.currentSrc, link: snapshot().link};
    return commentRows();
  }
  async function closeComments() {
    const close = [...document.querySelectorAll(
      "button[aria-label='exit' i], button[data-e2e*='comment-close' i], " +
      "button[aria-label*='fechar' i], button[aria-label*='close' i]"
    )].find(visible);
    if (close) await trustedClick(close);
    commentsVideo = null;
  }
  async function replyToComment(identifier, text) {
    const rows = commentRows();
    const target = rows.find(item => item.id === String(identifier || "")) ||
      rows.find(item => item.text === normalizedText(text));
    if (!target) throw new Error("O comentário selecionado não está mais disponível.");
    const element = document.querySelector(`[data-accessible-reels-comment-id="${CSS.escape(target.id)}"]`);
    const reply = element && [...element.querySelectorAll("button, [role=button], [data-e2e*='reply' i]")]
      .find(button => visible(button) && /^(responder|reply)$/i.test(normalizedText(button.innerText || button.getAttribute("aria-label"))));
    if (!reply) throw new Error("Não foi possível localizar Responder neste comentário.");
    await trustedClick(reply);
    return normalizedText(element.innerText);
  }

  async function execute(action, argument) {
    if (action === "play") {
      const deadline = Date.now() + 8000;
      while (!activeVideo() && Date.now() < deadline) await sleep(150);
    }
    const video = activeVideo();
    if (!["diagnostics", "collect_search_results", "close_comments"].includes(action) && !video) {
      throw new Error("Não foi possível localizar o vídeo atual.");
    }
    if (action === "collect_search_results") return collectSearchResults();
    if (action === "seek") {
      if (![-30, -15, 15, 30].includes(argument)) throw new Error("Intervalo inválido.");
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        throw new Error("Este vídeo ainda não permite avançar ou voltar no tempo.");
      }
      video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + argument));
      return {position: video.currentTime};
    }
    if (["author", "description", "copy_link", "refresh_info"].includes(action)) {
      const info = snapshot();
      if (action === "copy_link" && !info.link) return copyLinkFromTikTok(video);
      return info;
    }
    if (action === "next" || action === "previous") {
      stabilizeAudio();
      const source = video.currentSrc || video.getAttribute("src");
      const link = snapshot().link;
      const selectors = action === "next" ?
        ["button[data-e2e=feed-navigation-next]", "button[data-e2e=arrow-down]"] :
        ["button[data-e2e=feed-navigation-prev]", "button[data-e2e=arrow-up]"];
      // O TikTok mantém controles de vários itens no DOM. Escolher o primeiro
      // botão visível globalmente pode acionar o item errado (e fazer “anterior”
      // parecer outro “próximo”). Primeiro restringimos ao vídeo ativo.
      const onScreen = element => {
        if (!visible(element)) return false;
        const rect = element.getBoundingClientRect();
        const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
        const target = document.elementFromPoint(x, y);
        return target && element.contains(target);
      };
      const nearby = findNearVideo(selectors);
      const button = (onScreen(nearby) && nearby) ||
        [...document.querySelectorAll(selectors.join(","))].find(onScreen);
      // Scrolling a navigation button into the center can move a scroll-snap
      // feed back onto the current item before the click even reaches TikTok.
      if (button) await trustedClick(button, false);
      else {
        let scroller = video.parentElement;
        while (scroller && !(scroller.scrollHeight > scroller.clientHeight &&
            /auto|scroll/.test(getComputedStyle(scroller).overflowY))) {
          scroller = scroller.parentElement;
        }
        scroller = scroller || document.scrollingElement;
        if (scroller) scroller.scrollBy({
          top: (action === "next" ? 1 : -1) * scroller.clientHeight,
          behavior: "smooth"
        });
      }
      const deadline = Date.now() + 4500;
      while (Date.now() < deadline) {
        await sleep(150);
        stabilizeAudio();
        const current = activeVideo();
        if (current && (current !== video ||
            (current.currentSrc || current.getAttribute("src")) !== source ||
            snapshot().link !== link)) return snapshot();
      }
      throw new Error("O TikTok não mudou de vídeo. Tente novamente ou use F6 para acessar a página.");
    }
    if (action === "toggle" || action === "play") {
      initialPlaybackReleased = true;
      if (video.paused) {
        applyAudioPreference(video);
        await Promise.race([video.play(), sleep(5000).then(() => {
          throw new Error("A reprodução não foi confirmada. Use Reproduzir ou pausar, ou F6 para verificar a página.");
        })]);
        scheduleAudioPreference(video);
      } else if (action === "toggle") video.pause();
      return {paused: video.paused};
    }
    if (action === "volume_up" || action === "volume_down") {
      if (preferredVolume === null) preferredVolume = video.volume;
      preferredVolume = Math.max(0, Math.min(1,
        preferredVolume + (action === "volume_up" ? 0.05 : -0.05)));
      preferredMuted = false;
      publishAudioPreference();
      watchVideo(video);
      stabilizeAudio();
      await transport.storage.local.set({
        accessibleReelsVolume: preferredVolume,
        accessibleReelsMuted: preferredMuted
      });
      await sleep(100);
      return {volume: preferredVolume};
    }
    if (action === "speed_up" || action === "speed_down") {
      const speeds = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
      const current = Number.isFinite(video.playbackRate) ? video.playbackRate : 1;
      const index = speeds.findIndex(speed => speed >= current - 0.001);
      const base = index === -1 ? speeds.length - 1 : index;
      const next = Math.max(0, Math.min(speeds.length - 1,
        base + (action === "speed_up" ? (speeds[base] <= current + 0.001 ? 1 : 0) : -1)));
      video.playbackRate = speeds[next];
      return {playbackRate: video.playbackRate};
    }
    if (action === "toggle_mute") {
      if (preferredVolume === null) preferredVolume = video.volume;
      const effectivelyMuted = preferredMuted === null ?
        (video.muted || video.volume === 0) : preferredMuted;
      preferredMuted = !effectivelyMuted;
      if (effectivelyMuted && preferredVolume === 0) preferredVolume = 0.05;
      publishAudioPreference();
      watchVideo(video);
      stabilizeAudio();
      await transport.storage.local.set({
        accessibleReelsVolume: preferredVolume,
        accessibleReelsMuted: preferredMuted
      });
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
      try {
        return {comments: await openComments(video)};
      } finally {
        await closeComments();
      }
    }
    if (action === "reply_comment") {
      await openComments(video);
      const identifier = typeof argument === "object" ? argument.replyTo || argument.id : argument;
      const text = typeof argument === "object" ? argument.replyText || argument.text : "";
      return {replyTo: await replyToComment(identifier, text)};
    }
    if (action === "post_comment") {
      const text = normalizedText(typeof argument === "object" ? argument.text : String(argument || ""));
      if (!text) throw new Error("Digite um comentário antes de publicar.");
      try {
        await openComments(video);
        const replyTo = typeof argument === "object" ? argument.replyTo : "";
        if (replyTo) await replyToComment(replyTo, argument.replyText);
        const sameVideo = () => commentsVideo && commentsVideo.video === activeVideo() &&
          commentsVideo.source === video.currentSrc && commentsVideo.link === snapshot().link;
        if (!sameVideo()) throw new Error("O vídeo mudou. O comentário não foi enviado.");
        const editor = [...document.querySelectorAll(
          "[data-e2e=comment-input] [contenteditable=true], [contenteditable=true][role=textbox]"
        )].find(visible);
        if (!editor) throw new Error("Não foi possível localizar o campo de comentário.");
        if (normalizedText(editor.textContent)) throw new Error("Há um rascunho na página. Revise-o antes de publicar.");
        editor.focus();
        editor.textContent = text;
        editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
        await sleep(150);
        const post = [...document.querySelectorAll(
          "button[data-e2e=comment-post], [data-e2e=comment-post], button"
        )].find(element => visible(element) && /publicar|post/i.test(normalizedText(element.textContent)));
        if (!post) throw new Error("Não foi possível localizar Publicar comentário.");
        if (!sameVideo()) throw new Error("O vídeo mudou. O comentário não foi enviado.");
        await trustedClick(post);
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          await sleep(200);
          if (sameVideo() && editor.isConnected && !normalizedText(editor.textContent) &&
              commentRows().some(row => normalizedText(row.text).includes(text))) return {};
        }
        throw new Error("O envio não foi confirmado. Confira os comentários antes de tentar novamente.");
      } finally {
        await closeComments();
      }
    }
    if (action === "close_comments") {
      await closeComments();
      return {};
    }
    if (action === "diagnostics") {
      return {message: `Extensão conectada; página ${location.hostname}; ` +
        `${document.querySelectorAll("video").length} vídeo(s); ` +
        `vídeo ativo ${activeVideo() ? "sim" : "não"}; ${sharePanelDiagnostics()}`};
    }
    throw new Error("Comando desconhecido recebido pela extensão.");
  }

  transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "accessible-reels-command") return false;
    execute(message.action, message.argument)
      .then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error && error.message ? error.message : String(error)}));
    return true;
  });
})();
