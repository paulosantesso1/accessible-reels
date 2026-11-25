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
    if (preferredVolume !== null) {
      document.querySelectorAll("video").forEach(applyAudioPreference);
    }
    if (isLivePage()) {
      liveChatElements().forEach(el => {
        if (!el.getAttribute("aria-live")) el.setAttribute("aria-live", "polite");
      });
    }
  }, 250);

  const isLivePage = () => /^\/@[^/]+\/live\/?$/i.test(location.pathname) ||
    location.hostname.toLowerCase() === "live.tiktok.com" ||
    location.pathname.toLowerCase() === "/live" ||
    location.pathname.toLowerCase().startsWith("/live/");

  const LIVE_CHAT_SELECTORS = [
    '[data-e2e="chat-room"]',
    '[data-e2e="live-chat-room"]',
    '[data-e2e*="chat-room"]',
    '[data-e2e*="live-chat"]',
    '[data-e2e*="chat-list"]',
    '[data-e2e="chat-message-list"]',
    '[class*="DivChatRoom"]',
    '[class*="ChatRoom"]',
    '[class*="chat-room"]',
    '[class*="chatroom"]',
    '[class*="chat_room"]',
    '[class*="ChatContainer"]',
    '[class*="chat-container"]',
    '[class*="LiveChat"]',
    '[class*="live-chat"]',
    '[class*="ChatMessageList"]',
    '[class*="chat-message-list"]',
    'aside[class*="chat" i]',
    'section[class*="chat" i]',
    'div[role="log"]'
  ];

  const liveChatElements = () => {
    let rooms = [...new Set(LIVE_CHAT_SELECTORS.flatMap(selector => [...document.querySelectorAll(selector)]))];
    if (!rooms.length) {
      const msgs = document.querySelectorAll(
        '[data-e2e*="chat-message"], [class*="ChatMessage"], [class*="chat-message"], [class*="chat-item"], [class*="message-item"], [class*="DivChatMessageItem"]'
      );
      if (msgs.length) {
        const parents = [...new Set([...msgs].map(m => m.closest('[class*="chat" i], [data-e2e*="chat" i], aside, section, div[role="log"]') || m.parentElement).filter(Boolean))];
        if (parents.length) {
          rooms = parents;
        }
      }
    }
    return rooms;
  };

  async function resolveLiveChatElements(timeoutMs = 4000) {
    let rooms = liveChatElements();
    if (rooms.length) return rooms;

    const toggle = document.querySelector(
      '[data-e2e*="chat-toggle"], [data-e2e*="chat-collapse"], [data-e2e*="chat-icon"], button[aria-label*="chat" i], [class*="ChatToggle"], [class*="chat-toggle"]'
    );
    if (toggle) {
      try { toggle.click(); } catch (_) {}
    }

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await sleep(250);
      rooms = liveChatElements();
      if (rooms.length) return rooms;
    }
    return rooms;
  }

  let liveChatReading = false;
  let liveChatPollInterval = null;
  let liveChatMutationObserver = null;
  let lastKnownChatMessage = "";
  const seenChatNodes = new WeakSet();
  const seenChatTexts = new Set();

  function postLiveChatMessage(payload) {
    const jsonStr = typeof payload === "string" ? payload : JSON.stringify(payload);
    let posted = false;
    if (window.reelsHost && typeof window.reelsHost.postMessage === "function") {
      try { window.reelsHost.postMessage(jsonStr); posted = true; } catch (_) {}
    }
    if (!posted && window.chrome && window.chrome.webview && typeof window.chrome.webview.postMessage === "function") {
      try { window.chrome.webview.postMessage(jsonStr); posted = true; } catch (_) {}
    }
    if (!posted && window.wx && typeof window.wx.postMessage === "function") {
      try { window.wx.postMessage(jsonStr); posted = true; } catch (_) {}
    }
  }

  function parseChatMessageElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    const raw = (el.innerText || el.textContent || "").trim().replace(/\s+/g, " ");
    if (!raw || raw.length < 2) return null;
    if (/^adicionar coment[aá]rio|^add a comment|^live chat$|^chat da live$/i.test(raw)) return null;

    const userEl = el.querySelector('[class*="User" i], [class*="nickname" i], [class*="user-name" i], [data-e2e*="user" i]');
    const textEl = el.querySelector('[class*="Content" i], [class*="comment" i], [class*="content" i], [data-e2e*="content" i]');
    if (userEl && textEl && userEl !== textEl) {
      const u = userEl.innerText.trim();
      const c = textEl.innerText.trim();
      if (u && c) return `${u}: ${c}`.replace(/\s+/g, " ");
    }
    return raw;
  }

  function dispatchNewChatMessage(text) {
    if (!text || seenChatTexts.has(text)) return;
    seenChatTexts.add(text);
    if (seenChatTexts.size > 250) {
      const first = seenChatTexts.values().next().value;
      seenChatTexts.delete(first);
    }
    lastKnownChatMessage = text;
    postLiveChatMessage({
      type: "live_chat",
      messages: [text],
      text: text
    });
  }

  function handleNewChatNodes(root) {
    if (!root || !liveChatReading) return;
    const selector = '[data-e2e*="chat-message"], [class*="ChatMessage" i], [class*="chat-message" i], [class*="chat-item" i], [class*="message-item" i], [class*="DivChatMessage" i]';
    const isMsg = root.matches && root.matches(selector);
    const elements = isMsg ? [root] : (root.querySelectorAll ? [...root.querySelectorAll(selector)] : []);
    if (!elements.length && root.children && root.children.length) {
      for (const child of root.children) {
        if (!seenChatNodes.has(child)) {
          seenChatNodes.add(child);
          const t = parseChatMessageElement(child);
          if (t) dispatchNewChatMessage(t);
        }
      }
      return;
    }
    for (const el of elements) {
      if (!seenChatNodes.has(el)) {
        seenChatNodes.add(el);
        const t = parseChatMessageElement(el);
        if (t) dispatchNewChatMessage(t);
      }
    }
  }

  function extractLiveChatMessages(limit = 10) {
    if (!isLivePage()) {
      return { ok: false, error: "Você não está em uma live." };
    }
    const rooms = liveChatElements();
    if (!rooms.length) {
      return { ok: false, error: "O chat da live ainda está carregando ou não está disponível." };
    }

    const messageSelectors = [
      '[data-e2e="chat-message"]',
      '[data-e2e*="chat-message"]',
      '[class*="DivChatMessageItem"]',
      '[class*="ChatMessageItem"]',
      '[class*="ChatMessage"]',
      '[class*="chat-message"]',
      '[class*="chat-item"]',
      '[class*="message-item"]',
      'div[data-e2e*="message"]',
      '[role="listitem"]'
    ];

    let items = [];
    for (const room of rooms) {
      for (const sel of messageSelectors) {
        const found = room.querySelectorAll(sel);
        if (found.length) {
          items = [...found];
          break;
        }
      }
      if (items.length) break;
    }

    if (!items.length) {
      for (const room of rooms) {
        const children = [...room.children].filter(c => (c.innerText || "").trim().length > 0);
        if (children.length) {
          items = children;
          break;
        }
      }
    }

    const messages = [];
    for (const item of items) {
      const text = parseChatMessageElement(item);
      if (text && !messages.includes(text)) {
        messages.push(text);
      }
    }

    return {
      ok: true,
      messages: messages.slice(-limit),
      count: messages.length
    };
  }

  function startLiveChatObserver() {
    liveChatReading = true;
    const initial = extractLiveChatMessages(10);
    if (initial.ok && initial.messages.length) {
      for (const m of initial.messages) seenChatTexts.add(m);
      lastKnownChatMessage = initial.messages[initial.messages.length - 1];
    }
    const existing = document.querySelectorAll(
      '[data-e2e*="chat-message"], [class*="ChatMessage" i], [class*="chat-message" i], [class*="chat-item" i], [class*="message-item" i], [class*="DivChatMessage" i]'
    );
    for (const el of existing) seenChatNodes.add(el);

    if (liveChatMutationObserver) liveChatMutationObserver.disconnect();
    liveChatMutationObserver = new MutationObserver(mutations => {
      if (!liveChatReading || !isLivePage()) return;
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          handleNewChatNodes(node);
        }
      }
    });

    const rooms = liveChatElements();
    const targetRoom = rooms[0] || document.body;
    try {
      liveChatMutationObserver.observe(targetRoom, { childList: true, subtree: true });
    } catch (_) {
      try {
        liveChatMutationObserver.observe(document.body, { childList: true, subtree: true });
      } catch (_) {}
    }

    if (liveChatPollInterval) clearInterval(liveChatPollInterval);
    liveChatPollInterval = setInterval(() => {
      if (!liveChatReading || !isLivePage()) return;
      handleNewChatNodes(targetRoom);
    }, 1000);
  }

  function stopLiveChatObserver() {
    liveChatReading = false;
    if (liveChatPollInterval) {
      clearInterval(liveChatPollInterval);
      liveChatPollInterval = null;
    }
    if (liveChatMutationObserver) {
      liveChatMutationObserver.disconnect();
      liveChatMutationObserver = null;
    }
  }
  const visible = element => {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
  };
  // Visible and not covered by anything at the point a click would land.
  const onScreen = element => {
    if (!visible(element)) return false;
    const rect = element.getBoundingClientRect();
    const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return Boolean(target && element.contains(target));
  };

  function followState(element) {
    if (!element) return null;
    const pressed = element.getAttribute("aria-pressed");
    if (pressed === "true") return true;
    if (pressed === "false") return false;
    const value = [
      element.getAttribute("aria-label"), element.getAttribute("title"),
      element.getAttribute("data-state"), element.textContent
    ].filter(Boolean).join(" ").replace(/\s+/g, " ").trim().toLowerCase();
    if (/deixar de seguir|parar de seguir|\bunfollow\b|\bseguindo\b|\bfollowing\b/.test(value)) return true;
    if (/\bseguir\b|\bfollow\b/.test(value)) return false;
    return null;
  }

  function isExpectedProfile(expectedProfileUrl) {
    try {
      const expected = new URL(expectedProfileUrl);
      const host = value => value.toLowerCase().replace(/^(www\.|m\.)/, "");
      const path = value => decodeURIComponent(value).replace(/\/+$/, "").toLowerCase();
      return expected.protocol === "https:" && host(expected.hostname) === "tiktok.com" &&
        host(location.hostname) === "tiktok.com" && /^\/@[^/]+$/.test(path(expected.pathname)) &&
        path(location.pathname) === path(expected.pathname);
    } catch (_) {
      return false;
    }
  }

  function profileFollowSnapshot(expectedProfileUrl) {
    if (!isExpectedProfile(expectedProfileUrl)) return {state: null, target: null, wrongProfile: true};
    const roots = [...document.querySelectorAll([
      "[data-e2e='user-page-header']", "[data-e2e='profile-page-header']",
      "main header", "header", "[class*='DivShareLayoutHeader']",
      "[class*='ShareLayoutHeader']", "[class*='ProfileHeader']"
    ].join(","))].filter(visible);
    const selectors = [
      "button[data-e2e='follow-button']", "[role=button][data-e2e='follow-button']",
      "button[data-e2e*='profile-follow' i]", "[role=button][data-e2e*='profile-follow' i]",
      "button[aria-label*='seguir' i]", "button[aria-label*='follow' i]",
      "[role=button][aria-label*='seguir' i]", "[role=button][aria-label*='follow' i]"
    ];
    for (const root of roots) {
      for (const element of root.querySelectorAll(selectors.join(","))) {
        if (!visible(element)) continue;
        const state = followState(element);
        if (state !== null) return {state, target: element};
      }
    }

    // TikTok currently exposes a person/check icon beside Message on profiles
    // that are already followed. This is the actionable unfollow control.
    const unfollowIcon = roots.flatMap(root => [...root.querySelectorAll(
      "div[class*='DivFollowIcon'], button[class*='DivFollowIcon'], [role=button][class*='DivFollowIcon']"
    )]).find(visible);
    if (unfollowIcon) return {state: true, target: unfollowIcon};

    return {state: null, target: null};
  }

  function interactionBlocked() {
    if (document.querySelector(".secsdk-captcha-wrapper, [data-e2e*='captcha' i]")) {
      return "O TikTok exige uma verificação para esta conta. Não foi possível confirmar o seguimento.";
    }
    const text = normalizedText(document.body?.innerText).toLowerCase();
    if (/too many requests|muitas solicita[cç][oõ]es/.test(text)) {
      return "O TikTok limitou temporariamente esta ação. Tente novamente mais tarde.";
    }
    if (/\/login/.test(location.pathname)) {
      return "É preciso entrar no TikTok. Use F6 para verificar o login e repita a ação.";
    }
    return "";
  }

  async function profileFollowAction(toggle, expectedProfileUrl) {
    if (!isExpectedProfile(expectedProfileUrl)) {
      throw new Error("O perfil carregado não corresponde ao autor esperado. Nenhuma ação foi realizada.");
    }
    const deadline = Date.now() + 8000;
    let current = profileFollowSnapshot(expectedProfileUrl);
    let stableState = current.state;
    let stableSince = Date.now();
    while (Date.now() < deadline) {
      const blocked = interactionBlocked();
      if (blocked) throw new Error(blocked);
      if (current.state !== null && Date.now() - stableSince >= 1200) break;
      await sleep(150);
      current = profileFollowSnapshot(expectedProfileUrl);
      if (current.state !== stableState || current.state === null) {
        stableState = current.state;
        stableSince = Date.now();
      }
    }
    if (current.state === null || Date.now() - stableSince < 1200) {
      throw new Error("Não foi possível verificar o estado de seguimento no perfil do TikTok.");
    }
    if (!toggle) return {state: current.state};
    if (!current.target) {
      throw new Error("O perfil confirma que você segue este autor, mas não oferece um controle seguro para deixar de seguir.");
    }

    const before = current.state;
    if (!isExpectedProfile(expectedProfileUrl)) {
      throw new Error("A página mudou antes do clique. Nenhuma ação de seguimento foi realizada.");
    }
    await trustedClick(current.target);
    if (before) {
      // Some layouts open a confirmation dialog instead of changing state on
      // the first click. Only accept an exact unfollow action inside a dialog.
      const confirmDeadline = Date.now() + 1200;
      while (Date.now() < confirmDeadline) {
        const confirm = [...document.querySelectorAll("[role=dialog] button, [role=dialog] [role=button]")]
          .find(element => visible(element) && /^(deixar de seguir|parar de seguir|unfollow)$/i.test(
            normalizedText(element.getAttribute("aria-label") || element.textContent)
          ));
        if (confirm) {
          await trustedClick(confirm);
          break;
        }
        await sleep(100);
      }
    }

    const changedDeadline = Date.now() + 5000;
    let changedSince = null;
    while (Date.now() < changedDeadline) {
      const blocked = interactionBlocked();
      if (blocked) throw new Error(blocked);
      await sleep(150);
      current = profileFollowSnapshot(expectedProfileUrl);
      if (current.state !== null && current.state !== before) {
        if (changedSince === null) changedSince = Date.now();
        if (Date.now() - changedSince >= 1200) return {state: current.state};
      } else {
        changedSince = null;
      }
    }
    throw new Error("O TikTok não confirmou a alteração do estado de seguimento.");
  }

  function followClickDiagnostic(target, x, y) {
    const describe = element => element ? {
      tag: element.tagName.toLowerCase(),
      role: element.getAttribute("role") || "",
      data_e2e: element.getAttribute("data-e2e") || "",
      classes: [...element.classList].slice(0, 4).join(" ")
    } : null;
    const hit = document.elementFromPoint(x, y);
    const path = [];
    for (let element = hit; element && path.length < 4; element = element.parentElement) {
      path.push(describe(element));
    }
    return {target: describe(target), hit: describe(hit), hit_inside_target: Boolean(hit && target.contains(hit)), path};
  }

  async function trustedClick(element, scroll = true, diagnostic = false) {
    if (!element || !element.isConnected) throw new Error("O controle desapareceu da página.");
    if (scroll) element.scrollIntoView({block: "center", inline: "center"});
    await sleep(80);
    const rect = element.getBoundingClientRect();
    const response = await transport.runtime.sendMessage({
      type: "accessible-reels-trusted-click",
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      follow_diagnostic: diagnostic ? followClickDiagnostic(element,
        rect.left + rect.width / 2, rect.top + rect.height / 2) : undefined
    });
    if (!response || response.ok !== true) {
      throw new Error(response && response.error ? response.error : "O navegador recusou o clique.");
    }
  }

  // Best-effort: TikTok's own feed already advances on a real ArrowDown/
  // ArrowUp key press, independent of whichever nav-button markup is in the
  // DOM at the moment (that markup is what the click/scroll fallback below
  // depends on, and TikTok has been observed changing it). Never throws --
  // the caller keeps polling for a video change and falls back to the
  // click/scroll path if this didn't produce one.
  async function trustedKeyPress(key) {
    try {
      await transport.runtime.sendMessage({type: "accessible-reels-trusted-key", key});
    } catch (_) {}
  }

  // The item of the feed at the center of the screen, even under a dialog.
  function feedItem() {
    const x = innerWidth / 2, y = innerHeight / 2;
    return [...document.querySelectorAll("[data-e2e='recommend-list-item-container'], article")].find(element => {
      const rect = element.getBoundingClientRect();
      return rect.left <= x && rect.right > x && rect.top <= y && rect.bottom > y;
    }) || null;
  }
  // The For You feed mixes photo posts with videos. A photo post has no video
  // element, while the next video is often already mounted just below it.
  function photoPost() {
    const item = feedItem();
    return item && !item.querySelector("video") && item.querySelector(
      "[class*='DivPhotoPlayerContainer'], [class*='DivPhotoVideoContainer'], [class*='ImgPhotoSlide']"
    ) ? item : null;
  }
  function scrollFeed(element, direction) {
    let scroller = element.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight &&
        /auto|scroll/.test(getComputedStyle(scroller).overflowY))) {
      scroller = scroller.parentElement;
    }
    scroller = scroller || document.scrollingElement;
    if (scroller) scroller.scrollBy({top: direction * scroller.clientHeight, behavior: "smooth"});
  }
  // Scrolls past every photo post in the given direction. Scrolling, unlike the
  // key and the buttons, also works while a TikTok dialog covers the feed.
  async function skipPhotoPosts(direction, deadline) {
    let post;
    while ((post = photoPost()) && Date.now() < deadline) {
      await waitUntilSettled(Math.min(deadline, Date.now() + 1500), photoPost);
      if (photoPost() !== post) continue;
      scrollFeed(post, direction);
      const until = Math.min(deadline, Date.now() + 2500);
      while (photoPost() === post && Date.now() < until) await sleep(100);
      if (photoPost() === post) return false;
    }
    // TikTok mounts the video shortly after its item reaches the screen.
    while (!activeVideo() && !photoPost() && Date.now() < deadline) await sleep(150);
    await waitUntilSettled(Math.min(deadline, Date.now() + 1500));
    return !photoPost() && Boolean(activeVideo());
  }
  function activeVideo() {
    if (photoPost()) return null;
    // In the For You feed the current video can be transparent (painted on a
    // canvas) while the next one already peeks into the screen, so being on the
    // centered item decides, not being visible.
    const item = feedItem();
    if (item?.matches("[data-e2e='recommend-list-item-container']")) {
      const own = [...item.querySelectorAll("video")];
      lastActiveVideo = own.find(video => !video.paused && !video.ended) || own[0] || null;
      lastActiveSource = lastActiveVideo?.currentSrc || "";
      return lastActiveVideo;
    }
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
  // Resolves once the same video (or other element) has kept its source and
  // position for three consecutive samples: the feed finished scrolling onto it.
  async function waitUntilSettled(deadline, current = activeVideo) {
    let previous = null;
    let steady = 0;
    while (Date.now() < deadline) {
      const element = current();
      const state = element && {
        element,
        top: Math.round(element.getBoundingClientRect().top),
        source: element.currentSrc || element.getAttribute("src")
      };
      const same = state && previous && state.element === previous.element &&
        state.top === previous.top && state.source === previous.source;
      steady = same ? steady + 1 : 0;
      previous = state;
      if (steady >= 3) return;
      await sleep(150);
    }
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
    // TikTok can mount the action rail (like/comment/favorite/share) one level
    // above the element that exclusively wraps the active video, alongside a
    // sibling item's preloaded (not yet visible) <video>. Allow climbing past
    // exactly one such level before giving up, instead of stopping immediately.
    let sharedLevelsAllowed = 1;
    for (let depth = 0; ancestor && ancestor !== document.body && depth < 15; depth++) {
      const videos = [...ancestor.querySelectorAll("video")];
      if (videos.some(item => item !== video)) {
        if (sharedLevelsAllowed <= 0) break;
        sharedLevelsAllowed -= 1;
      }
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
    // TikTok currently renders the action rail (like/comment/favorite/share)
    // outside any element shared with the video, so it is never found by
    // climbing ancestors. Only the active item's rail is visible at a time, so
    // a document-wide, visibility-filtered search stays unambiguous.
    for (const selector of selectors) {
      const match = [...document.querySelectorAll(selector)].find(visible);
      if (match) return match.closest("button, [role=button], a[href], [tabindex]") || match;
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

  // Anonymized structural dump of an element: tags, attributes, classes --
  // enough to find the right selector -- with anything that could be a
  // person's name, avatar or caption removed instead of merely guessed at
  // attribute-by-attribute. Any text node over 20 chars (likely a video
  // description, username or comment) is replaced with a placeholder, and
  // every image source is stripped.
  function anonymizedOuterHTML(element, limit = 6000) {
    if (!element) return "(elemento não encontrado)";
    const clone = element.cloneNode(true);
    clone.querySelectorAll("img, picture source").forEach(node => {
      node.removeAttribute("src");
      node.removeAttribute("srcset");
    });
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
    const toRedact = [];
    let node;
    while ((node = walker.nextNode())) {
      const text = (node.nodeValue || "").trim();
      if (text.length > 20) toRedact.push(node);
    }
    for (const textNode of toRedact) textNode.nodeValue = "[texto]";
    return clone.outerHTML.slice(0, limit);
  }

  function sharePanelDiagnostics() {
    const panel = [...document.querySelectorAll("[role=dialog], [role=menu], [data-e2e*=share i]")]
      .filter(visible)[0] || null;
    return `painel de compartilhamento ${panel ? "visível" : "não visível"}; ` +
      `html=${anonymizedOuterHTML(panel)}`;
  }

  function canonicalLink(value) {
    try {
      const url = new URL(value, location.href);
      const videoMatch = url.pathname.match(/^\/@[^/?#]+\/video\/(\d+)\/?$/);
      const liveMatch = url.pathname.match(/^\/(@[^/?#]+)\/live\/?$/);
      const directLive = url.hostname === "live.tiktok.com" ? url.pathname.match(/^\/(@[^/?#]+)(\/live)?\/?$/) : null;
      const trustedHost = ["www.tiktok.com", "tiktok.com", "live.tiktok.com"].includes(url.hostname);
      if (url.protocol !== "https:" || !trustedHost || url.username || url.password || url.port) return "";
      if (directLive) return `https://www.tiktok.com/${directLive[1]}/live`;
      if (liveMatch) return `https://www.tiktok.com/${liveMatch[1]}/live`;
      if (videoMatch) return `https://www.tiktok.com${url.pathname.replace(/\/$/, "")}`;
      return "";
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

  function downloadMedia(video, link) {
    const isHttp = value => typeof value === "string" && value.startsWith("https://");
    const current = video.currentSrc || video.src;
    if (isHttp(current)) return current;
    const id = link.match(/\/video\/(\d+)/)?.[1] ||
      videoIdFromActiveCard(video, ancestorsFor(video));
    if (!id) return "";
    const roots = [window.__accessibleMediaItems?.get(id)];
    for (const script of document.querySelectorAll(
      "script#__UNIVERSAL_DATA_FOR_REHYDRATION__, script#SIGI_STATE, script[type='application/json']"
    )) {
      try { roots.push(JSON.parse(script.textContent || "")); } catch (_) {}
    }
    // Feed cards loaded after navigation often keep their item data in React
    // props instead of the initial hydration script. Match the active ID only.
    for (const element of [video, ...ancestorsFor(video)]) {
      for (const key of Object.keys(element)) {
        if (key.startsWith("__reactProps$")) roots.push(element[key]);
      }
    }
    const seen = new WeakSet();
    const pending = roots.map(value => [value, 0]);
    let budget = 12000;
    const address = (value, depth = 0) => {
      if (depth > 3) return "";
      if (isHttp(value)) return value;
      if (!value || typeof value !== "object") return "";
      if (Array.isArray(value)) return value.map(item => address(item, depth + 1)).find(Boolean) || "";
      return [value.src, ...(value.UrlList || value.url_list || [])].find(isHttp) || "";
    };
    while (pending.length && budget-- > 0) {
      const [value, depth] = pending.pop();
      if (!value || typeof value !== "object" || value instanceof Node || seen.has(value) || depth > 18) continue;
      seen.add(value);
      if (String(value.id || value.itemId || value.aweme_id || "") === id) {
        const data = value.video || {};
        const candidate = address(data.playAddr) || address(data.play_addr) ||
          address(data.downloadAddr) || address(data.download_addr);
        if (candidate) return candidate;
      }
      for (const key of Object.keys(value)) {
        // Avoid invoking getters or walking React owners and browser objects.
        if (["_owner", "return", "stateNode"].includes(key)) continue;
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (descriptor && "value" in descriptor) pending.push([descriptor.value, depth + 1]);
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
    return null;
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
    // TikTok can render the active item's author/description/link overlay
    // outside any element shared with the video (same as the action rail).
    // Fall back to a document-wide, visibility-filtered search: only one
    // such overlay is visible at a time, so this stays unambiguous.
    const query = selectors => {
      for (const root of ancestors) {
        for (const selector of selectors) {
          const element = root.querySelector(selector);
          const text = normalizedText(element && (element.getAttribute("aria-label") || element.textContent));
          if (text) return text;
        }
      }
      for (const selector of selectors) {
        const element = [...document.querySelectorAll(selector)].find(visible);
        const text = normalizedText(element && (element.getAttribute("aria-label") || element.textContent));
        if (text) return text;
      }
      return "";
    };
    const findProfileAnchor = roots => {
      for (const root of roots) {
        for (const anchor of root.querySelectorAll("a[href^='/@'], a[href*='tiktok.com/@']")) {
          if (!visible(anchor)) continue;
          // The document-wide fallback must not pick up the signed-in account's
          // own profile link or any other navigation/header/sidebar chrome --
          // only the active video's own author credit is a valid match here.
          if (anchor.closest(
            "nav, header, [role=navigation], [data-e2e*='nav' i], [data-e2e*='sidebar' i], " +
            "[data-e2e*='sidenav' i], [data-e2e*='top-bar' i]"
          )) continue;
          try {
            const raw = anchor.getAttribute("href") || "";
            const candidate = raw.startsWith("/") ? null : new URL(anchor.href, location.href);
            const pathname = candidate ? candidate.pathname : raw;
            const trustedHost = !candidate || candidate.hostname === "tiktok.com" || candidate.hostname.endsWith(".tiktok.com");
            const match = pathname.match(/^\/@([A-Za-z0-9._-]{1,24})\/?$/);
            if (trustedHost && match) {
              return {handle: match[1], url: `https://www.tiktok.com/@${match[1]}`};
            }
          } catch (_error) {}
        }
      }
      return null;
    };
    const profile = findProfileAnchor(ancestors) || findProfileAnchor([document]);
    let author = query([
      "[data-e2e=video-author-uniqueid]", "[data-e2e=browse-username]",
    ]);
    author ||= profile ? `@${profile.handle}` : "";
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
    // Never search the whole document for a video link: pages list other videos
    // too, and a wrong link is worse than none (copying then uses Share).
    link ||= canonicalLink(location.href);
    if (!link) {
      let handle = profile?.handle || "";
      // O feed atual pode expor o @autor em texto acessível, sem um link de
      // perfil ao redor. Ele ainda pertence ao mesmo vídeo já selecionado.
      handle ||= author.match(/@([A-Za-z0-9._-]{1,24})/)?.[1] ||
        author.match(/^([A-Za-z0-9._-]{1,24})$/)?.[1] || "";
      const videoId = videoIdFromActiveCard(video, ancestors);
      if (handle && videoId) link = `https://www.tiktok.com/@${handle}/video/${videoId}`;
    }
    link ||= stateVideoLink(author, description);
    
    let profile_url = profile?.url || "";
    if (!profile_url) {
        let handle = author.match(/@([A-Za-z0-9._-]{1,24})/)?.[1] || author.match(/^([A-Za-z0-9._-]{1,24})$/)?.[1] || "";
        if (handle) profile_url = `https://www.tiktok.com/@${handle}`;
    }

    return {
      author: author || "Autor não encontrado",
      description: description || "Descrição não encontrada",
      link,
      profile_url
    };
  }

  function collectSearchResults() {
    const results = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll("a[href*='/video/']")) {
      let url;
      try { url = new URL(anchor.href, location.href); } catch (_error) { continue; }
      const videoMatch = url.pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
      if (!videoMatch) continue;
      const key = videoMatch[0];
      if (seen.has(key)) continue;
      seen.add(key);
      const container = anchor.closest(
        "[data-e2e=search-card-video-container], [data-e2e=user-post-item], li"
      ) || anchor.parentElement;
      const image = anchor.querySelector("img") || (container && container.querySelector("img"));
      const description = normalizedText(
        (image && (image.alt || image.getAttribute("aria-label"))) ||
        anchor.getAttribute("aria-label") || anchor.title ||
        (container && container.innerText) || ""
      );
      const author = videoMatch[1];
      results.push({
        url: `https://www.tiktok.com/${author}/video/${videoMatch[2]}`,
        author: decodeURIComponent(author),
        description
      });
      if (results.length >= 50) break;
    }
    return {results};
  }

  // TikTok's favorite button keeps the same accessible name ("Adicionar aos
  // favoritos...") in both states and exposes no pressed attribute: the only
  // difference is the bookmark icon, yellow when saved and white when not.
  function iconColorState(button) {
    const icon = button.querySelector("svg");
    if (!icon) return null;
    const match = getComputedStyle(icon).fill.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!match) return null;
    const [red, green, blue] = [Number(match[1]), Number(match[2]), Number(match[3])];
    if (red > 200 && green > 140 && blue < 110) return true;
    if (red > 200 && green > 200 && blue > 200) return false;
    return null;
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
    if (/favorite|collect/i.test(button.getAttribute("data-e2e") || "")) {
      const colored = iconColorState(button);
      if (colored !== null) return colored;
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
  const MORE_SELECTORS = [
    "[data-e2e=more-menu-icon]", "[data-e2e*='more-icon' i]", "[data-e2e*='more-menu' i]",
    "[role=button][aria-label*='mais opções' i]", "[role=button][aria-label*='more options' i]",
    "[role=button][aria-label*='mais ações' i]", "[role=button][aria-label*='more actions' i]",
    "button[aria-label*='mais opções' i]", "button[aria-label*='more options' i]",
    "button[aria-label*='mais ações' i]", "button[aria-label*='more actions' i]"
  ];
  const NOT_INTERESTED = /^(não tenho interesse|não me interessa|não estou interessado|not interested)\b/i;
  function findNotInterestedItem() {
    const pool = new Set(document.querySelectorAll("[role=menuitem], button, [role=button], li, a, [data-e2e]"));
    for (const popup of document.querySelectorAll("[role=menu], [role=dialog], [role=listbox]")) {
      if (visible(popup)) popup.querySelectorAll("*").forEach(element => pool.add(element));
    }
    const matches = [...pool].filter(element => visible(element) &&
      NOT_INTERESTED.test(normalizedText(element.getAttribute("aria-label") || element.textContent)));
    return matches.find(element => !matches.some(other => other !== element && element.contains(other))) || null;
  }
  // The "..." button only exists visibly while the pointer is over the video.
  async function hoverVideo(video) {
    const target = video.closest("[data-e2e=feed-video], article, section") || video.parentElement || video;
    const rect = target.getBoundingClientRect();
    const init = {bubbles: true, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2};
    for (const type of ["pointerover", "pointerenter", "mouseover", "mouseenter", "pointermove", "mousemove"]) {
      target.dispatchEvent(new MouseEvent(type, init));
    }
    await sleep(300);
  }
  function hiddenMoreButton(video) {
    const scope = ancestorsFor(video).slice(-1)[0] || document.body;
    return scope.querySelector("[data-e2e=more-menu-icon], [data-e2e*='more-menu' i]");
  }
  // Compact map of the controls around the video, for support when a command cannot find its target.
  function describeControls(video) {
    const scope = ancestorsFor(video).slice(-1)[0] || document.body;
    const controls = [...scope.querySelectorAll("button, [role=button], [role=menuitem], a[href], [data-e2e]")]
      .filter(visible).slice(0, 80)
      .map(element => [element.tagName.toLowerCase(), element.getAttribute("data-e2e") || "",
        element.getAttribute("aria-label") || "", normalizedText(element.textContent).slice(0, 30)].join("|"));
    const popups = [...document.querySelectorAll("[role=menu], [role=dialog], [role=listbox]")]
      .filter(visible).map(element => normalizedText(element.textContent).slice(0, 500));
    // Which account controls the page shows tells whether the session is logged in.
    const account = [...document.querySelectorAll(
      "[data-e2e*='login' i], [data-e2e*='profile-icon' i], [data-e2e*='upload-icon' i], [data-e2e*='inbox' i]")]
      .slice(0, 10).map(element => `${visible(element) ? "visible" : "hidden"}|${element.getAttribute("data-e2e")}`);
    // Menus that only appear while the pointer hovers the video are not visible yet.
    const menuLike = /more|mais|menu|report|denunci|interess|interested|dislike|option|opç/i;
    const menuControls = [...scope.querySelectorAll("button, [role=button], [data-e2e], [aria-label]")]
      .filter(element => menuLike.test(`${element.getAttribute("data-e2e") || ""} ${element.getAttribute("aria-label") || ""} ${element.getAttribute("title") || ""}`))
      .slice(0, 30).map(element => `${visible(element) ? "visible" : "hidden"}|${element.tagName.toLowerCase()}|` +
        `${element.getAttribute("data-e2e") || ""}|${element.getAttribute("aria-label") || ""}`);
    return {controls, popups, menuControls, account};
  }
  // The platform may move to the next video by itself after a mark; only ask for a skip when it did not.
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
    if (!video) throw new Error("Não foi possível localizar o vídeo atual.");
    try {
      let item = findNotInterestedItem();
      if (!item) {
        await hoverVideo(video);
        const more = findNearVideo(MORE_SELECTORS);
        const hiddenMore = more ? null : hiddenMoreButton(video);
        if (more) {
          await trustedClick(more);
        } else if (hiddenMore) {
          hiddenMore.click();
        } else {
          // Some layouts only offer the option in the video's context menu.
          const rect = video.getBoundingClientRect();
          video.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true,
            clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2}));
        }
        const deadline = Date.now() + 3000;
        while (!item && Date.now() < deadline) {
          await sleep(150);
          item = findNotInterestedItem();
        }
      }
      if (!item) throw new Error("Este vídeo não oferece a opção Não tenho interesse. Use F6 para acessar a página.");
      const link = snapshot().link;
      await trustedClick(item, false);
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline) {
        await sleep(150);
        if (!item.isConnected || !visible(item)) return afterMark(video, link);
      }
      throw new Error("O TikTok não confirmou a marcação. Confira na página (F6).");
    } catch (error) {
      error.details = describeControls(video);
      document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
      throw error;
    }
  }
  const COMMENT_SELECTORS = [
    "[data-e2e=comment-icon]", "[role=button][aria-label*='coment' i]",
    "[role=button][aria-label*='comment' i]"
  ];
  // On TikTok comment-level-1 marks the paragraph with a comment's text, inside the item
  // that also holds its author and its Responder control. Each comment is listed once,
  // through that item, so a reply always starts from the element that has Responder.
  const COMMENT_TEXT = "[data-e2e=comment-level-1], [data-e2e=comment-level-2], [data-e2e=comment-text]";
  const COMMENT_ITEM = "[data-e2e=comment-item], [data-e2e=comment-reply-item], [class*='CommentItemContainer'], [class*='CommentItem']";
  const COMMENT_LIST = "[data-e2e='comment-list'], [class*='CommentListContainer'], [class*='CommentList']";
  const REPLY_CONTROL = "[data-e2e*='comment-reply' i], [data-e2e*='reply' i], button, [role=button]";
  let nextCommentId = 0;
  function isCommentActionOrInput(element) {
    if (!element) return false;
    if (element.closest("[data-e2e*='comment-input'], [class*='CommentInput'], [class*='BottomArea'], [contenteditable='true'], form")) {
      return true;
    }
    const text = normalizedText(element.innerText || element.getAttribute("aria-label") || "").toLowerCase();
    if (/^(adicionar coment[aá]rio|add a? comment|publicar|postar)\b/i.test(text)) {
      return true;
    }
    return false;
  }
  function replyControlIn(item) {
    const controls = [...item.querySelectorAll(REPLY_CONTROL)].filter(visible);
    const byE2e = controls.find(control => /comment-reply/i.test(control.getAttribute("data-e2e") || ""));
    if (byE2e) return byE2e;
    const byText = controls.find(control =>
      /^(responder|reply)\b/i.test(normalizedText(control.innerText || control.getAttribute("aria-label") || control.getAttribute("title") || "")));
    if (byText) return byText;
    const byPartial = controls.find(control =>
      /\b(responder|reply)\b/i.test(normalizedText(control.getAttribute("aria-label") || control.innerText || "")));
    if (byPartial) return byPartial;
    const sub = item.querySelector("[class*='SubContent'], [class*='PCommentSub'], [class*='Action']");
    if (sub) {
      const candidates = [...sub.querySelectorAll("button, [role=button], span[role=button]")].filter(el =>
        visible(el) && !/like|curtir|heart|menu|more|options/i.test(`${el.getAttribute("data-e2e") || ""} ${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`));
      if (candidates.length > 0) return candidates[0];
    }
    return null;
  }
  function commentItemOf(element) {
    if (!element.matches(COMMENT_TEXT)) return element;
    const item = element.parentElement?.closest(COMMENT_ITEM);
    if (item) return item;
    // Without a known item class, the item is the nearest ancestor holding Responder.
    for (let node = element, level = 0; node && level < 6; node = node.parentElement, level++) {
      if (node !== element && node.querySelectorAll(COMMENT_TEXT).length > 1) break;
      if (replyControlIn(node)) return node;
    }
    return element;
  }
  function commentElements() {
    const items = [];
    for (const element of document.querySelectorAll(`${COMMENT_ITEM}, ${COMMENT_TEXT}`)) {
      if (!visible(element)) continue;
      if (isCommentActionOrInput(element)) continue;
      const item = commentItemOf(element);
      if (!item || isCommentActionOrInput(item)) continue;
      if (!items.includes(item)) items.push(item);
    }
    // An item inside another one is part of that comment (its reply thread), unless marked as reply item.
    return items.filter(item => item.matches?.("[data-e2e*='reply-item']") || !items.some(other => other !== item && other.contains(item)));
  }
  function commentText(item) {
    if (isCommentActionOrInput(item)) return "";
    const author = normalizedText(item.querySelector("[data-e2e^='comment-username']")?.innerText);
    const body = normalizedText(item.querySelector(COMMENT_TEXT)?.innerText);
    const raw = normalizedText(item.innerText);
    if (/^(adicionar coment[aá]rio|add a? comment)\b/i.test(raw)) return "";
    return author && body ? `${author}: ${body}` : (body || author || raw);
  }
  function commentRows() {
    const all = commentElements();
    return all.map(item => {
      let text = commentText(item);
      if (!text || /^(adicionar coment[aá]rio|add a? comment)\b/i.test(text.trim())) return null;
      const isReply = all.some(other => other !== item && other.contains(item));
      if (isReply && !text.startsWith('↳') && !text.startsWith('[Resposta]')) {
        text = "[Resposta] " + text;
      }
      // Ids never repeat, so a list built earlier can not point at another comment.
      let id = item.getAttribute("data-accessible-reels-comment-id");
      if (!id) {
        id = `accessible-reels-comment-${++nextCommentId}`;
        item.setAttribute("data-accessible-reels-comment-id", id);
      }
      return {id, text};
    }).filter(Boolean);
  }
  function commentScrollContainer() {
    const list = document.querySelector(COMMENT_LIST);
    if (list && list.scrollHeight > list.clientHeight + 20) return list;
    const first = document.querySelector(COMMENT_ITEM) || document.querySelector(COMMENT_TEXT);
    for (let p = first?.parentElement; p && p !== document.body; p = p.parentElement) {
      if (p.scrollHeight > p.clientHeight + 20) {
        const style = getComputedStyle(p);
        if (/(auto|scroll)/.test(style.overflowY) || p.scrollHeight > p.clientHeight + 100) {
          return p;
        }
      }
    }
    return list || null;
  }
  // The application limits the clicks of each command (MAX_CLICKS there), and
  // the panel must still be opened and closed; a click over it would time out.
  const MAX_EXPANSIONS = 2;
  // Controls that load more replies, only inside the comments. The options menu
  // of a comment or video is also named "Mais", so a generic name is not enough.
  function replyExpanders() {
    const areas = [...document.querySelectorAll(COMMENT_LIST), ...commentElements()];
    const controls = new Set(areas.flatMap(area => [...area.querySelectorAll(
      "[data-e2e*='view-more' i], [class*='DivMoreButton'], button, [role=button]"
    )]));
    return [...controls].filter(control => visible(control) && (
      control.matches("[data-e2e*='view-more' i], [class*='DivMoreButton']") ||
      /^(ver|view|mostrar|show|carregar|load)\b.*(mais|more|respost|repl)/i.test(controlName(control))
    ));
  }
  // Logged when Responder is not found: the shape of the comment, never its text or author.
  function describeCommentItem(item) {
    const shape = [];
    const walk = (node, depth) => {
      if (shape.length >= 60 || depth > 8) return;
      const names = String(node.className?.baseVal ?? node.className ?? "").split(/\s+/)
        .map(name => name.split("-").pop()).filter(name => /^[A-Z]/.test(name)).join(".");
      const label = node.getAttribute("aria-label") || "";
      const control = node.matches("button, [role=button]") ? normalizedText(node.innerText).slice(0, 15) : "";
      shape.push([depth, node.tagName.toLowerCase(), node.getAttribute("data-e2e") || "", node.getAttribute("role") || "",
        names, label.length <= 25 ? label : "", control, visible(node) ? "visible" : "hidden"].join("|"));
      for (const child of node.children) walk(child, depth + 1);
    };
    walk(item, 0);
    return {comment_item: shape};
  }
  // The send control of a comment field is found from the field outwards. It may be a
  // text button, an icon named by aria-label/data-e2e, or an icon that only turns
  // TikTok's red once the field has text; emoji and mention buttons are never it.
  const TIKTOK_ACTIVE_RED = "rgb(254, 44, 85)";
  const POST_CANDIDATES = "[data-e2e*='comment-post' i], [data-e2e*='post' i], button, [role=button], input[type='submit']";
  const POST_NAME = /^(publicar|postar|post|enviar|send)\b/i;
  const NOT_POST = /emoji|mention|comment-at|gif|image|imagem|cancel|fechar|close|responder|reply|curtir|like|heart/i;
  function controlName(element) {
    return normalizedText(element.getAttribute("aria-label") || element.getAttribute("title") ||
      element.querySelector("svg title")?.textContent || element.textContent || "");
  }
  function enabledControl(element) {
    return visible(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true";
  }
  function isRedOrBrandTone(colorStr) {
    if (!colorStr) return false;
    if (colorStr.includes(TIKTOK_ACTIVE_RED)) return true;
    const match = colorStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (match) {
      const [r, g, b] = [Number(match[1]), Number(match[2]), Number(match[3])];
      return r >= 170 && r > g * 1.3 && r > b * 1.3;
    }
    if (/^#(fe2c55|ff0050|e6204c|de1b45)/i.test(colorStr)) return true;
    return false;
  }
  function paintedRed(element) {
    return [element, ...element.querySelectorAll("svg, path")].some(node => {
      const style = getComputedStyle(node);
      return isRedOrBrandTone(style.color) || isRedOrBrandTone(style.fill) || isRedOrBrandTone(style.backgroundColor);
    });
  }
  function postButtonFor(editor) {
    for (let area = editor.parentElement; area && area !== document.documentElement; area = area.parentElement) {
      const candidates = [...area.querySelectorAll(POST_CANDIDATES)]
        .filter(element => !element.contains(editor) && enabledControl(element));
      const named = candidates.find(element => POST_NAME.test(controlName(element)) ||
        /comment-post/i.test(element.getAttribute("data-e2e") || "") ||
        element.getAttribute("type") === "submit");
      if (named) return named;
      const red = candidates.find(element => paintedRed(element) &&
        !NOT_POST.test(`${element.getAttribute("data-e2e") || ""} ${controlName(element)}`));
      if (red) return red;
      // Fallback estrutural: se o botão mudou de cor ou formato de texto, seleciona controle de envio habilitado
      const structural = candidates.filter(element =>
        !NOT_POST.test(`${element.getAttribute("data-e2e") || ""} ${controlName(element)}`));
      if (structural.length === 1) return structural[0];
      if (structural.length > 1) {
        const after = structural.find(element =>
          Boolean(element.compareDocumentPosition(editor) & Node.DOCUMENT_POSITION_PRECEDING));
        if (after) return after;
        return structural[structural.length - 1];
      }
      // Past this point the area also holds another field, whose button is not this one's.
      if ([...area.querySelectorAll("[contenteditable=true]")].some(other => other !== editor && visible(other))) return null;
    }
    return null;
  }
  // Logged when no send control is found: the controls around the field, never comment text.
  function describePostArea(editor) {
    const controls = [];
    let area = editor.parentElement;
    for (let level = 0; area && level < 10 && controls.length < 25; level++, area = area.parentElement) {
      for (const element of area.querySelectorAll("button, [role=button], [data-e2e], svg")) {
        if (controls.length >= 25 || element.contains(editor) || element.dataset.accessibleReelsSeen) continue;
        element.dataset.accessibleReelsSeen = "1";
        const style = getComputedStyle(element);
        controls.push([level, element.tagName.toLowerCase(), element.getAttribute("data-e2e") || "",
          element.getAttribute("role") || "", element.getAttribute("aria-label") || "",
          normalizedText(element.textContent).slice(0, 20), element.disabled || element.getAttribute("aria-disabled") || "",
          style.color, style.fill, style.backgroundColor, visible(element) ? "visible" : "hidden"].join("|"));
      }
    }
    document.querySelectorAll("[data-accessible-reels-seen]").forEach(element => delete element.dataset.accessibleReelsSeen);
    return {post_area: controls};
  }
  function cleanCommentText(value) {
    return normalizedText(value)
      .replace(/^\[resposta\]\s*/i, "")
      .replace(/^↳\s*/, "")
      .replace(/^\d+\s+de\s+\d+:\s*/i, "")
      .trim();
  }
  // A TikTok dialog (login, interests) on screen, other than the comments themselves.
  function blockingDialog() {
    return [...document.querySelectorAll("[role=dialog], [aria-modal=true], [data-e2e=login-modal]")].find(element => {
      const rect = element.getBoundingClientRect();
      return visible(element) && rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth &&
        !element.querySelector(`${COMMENT_ITEM}, ${COMMENT_TEXT}`);
    }) || null;
  }
  function blockingDialogError(dialog) {
    if (dialog.matches("[data-e2e=login-modal], #loginModalContentContainer") ||
        dialog.querySelector("[data-e2e=login-modal], #loginModalContentContainer") ||
        /(entrar no|criar conta no|log in to|sign up for) tiktok/i.test(dialog.innerText)) {
      return new Error("O TikTok pediu login para mostrar os comentários. Use F6 para entrar na sua conta.");
    }
    const title = normalizedText(String(dialog.innerText || "").trim().split("\n")[0]).slice(0, 60);
    return new Error("Uma janela do TikTok está cobrindo a página" + (title ? `: “${title}”` : "") +
      ". Use F6 para fechá-la na página e tente de novo.");
  }
  async function openComments(video) {
    const button = findNearVideo(COMMENT_SELECTORS);
    if (!button) throw new Error("Não foi possível localizar o botão de comentários.");
    // A click on a covered button would land on the dialog, for example on one of its login options.
    button.scrollIntoView({block: "center", inline: "center"});
    await sleep(80);
    let dialog = onScreen(button) ? null : blockingDialog();
    if (dialog) throw blockingDialogError(dialog);
    await trustedClick(button);
    await sleep(1200);
    dialog = commentRows().length ? null : blockingDialog();
    if (dialog) throw blockingDialogError(dialog);
    commentsVideo = {video, source: video.currentSrc, link: snapshot().link};
    return commentRows();
  }
  async function closeComments() {
    const close = [...document.querySelectorAll(
      "button[aria-label='exit' i], [role=button][aria-label='exit' i], " +
      "button[data-e2e*='comment-close' i], [role=button][data-e2e*='comment-close' i], " +
      "[data-e2e*='close-icon' i], button[aria-label*='fechar' i], [role=button][aria-label*='fechar' i], " +
      "button[aria-label*='close' i], [role=button][aria-label*='close' i]"
    )].find(visible);
    if (close) await trustedClick(close);
    commentsVideo = null;
  }
  async function replyToComment(identifier, text) {
    let rows = commentRows();
    const searchId = String(identifier || "").trim();
    const cleanSearchText = cleanCommentText(text);
    let target = (searchId && rows.find(item => item.id === searchId)) ||
      (cleanSearchText && rows.find(item => cleanCommentText(item.text) === cleanSearchText)) ||
      (cleanSearchText && rows.find(item => {
        const itemClean = cleanCommentText(item.text);
        return itemClean.includes(cleanSearchText) || cleanSearchText.includes(itemClean);
      }));
    if (!target) {
      const expandButtons = replyExpanders().slice(0, MAX_EXPANSIONS);
      if (expandButtons.length > 0) {
        for (const btn of expandButtons) await trustedClick(btn);
        await sleep(300);
        rows = commentRows();
        target = (searchId && rows.find(item => item.id === searchId)) ||
          (cleanSearchText && rows.find(item => cleanCommentText(item.text) === cleanSearchText)) ||
          (cleanSearchText && rows.find(item => {
            const itemClean = cleanCommentText(item.text);
            return itemClean.includes(cleanSearchText) || cleanSearchText.includes(itemClean);
          }));
      }
    }
    if (!target) throw new Error("O comentário selecionado não está mais disponível.");
    const element = document.querySelector(`[data-accessible-reels-comment-id="${CSS.escape(target.id)}"]`);
    const reply = element && replyControlIn(element);
    if (!reply || !visible(reply)) {
      const error = new Error("Não foi possível localizar Responder neste comentário.");
      if (element) error.details = describeCommentItem(element);
      throw error;
    }
    await trustedClick(reply);
    return element;
  }

  // The logged-in account's own profile link is in the side navigation.
  async function ownProfile() {
    const deadline = Date.now() + 10000;
    let handle = "";
    while (!handle && Date.now() < deadline) {
      const link = document.querySelector('[data-e2e="nav-profile"]');
      handle = ((link && link.getAttribute("href")) || "").match(/^\/(@[^/?#]+)/)?.[1] || "";
      if (!handle) await sleep(250);
    }
    if (!handle) throw new Error("Entre na sua conta do TikTok pela página (F6) para ver seus vídeos.");
    return {profile_url: `https://www.tiktok.com/${handle}`};
  }

  // Profile tabs of the logged-in account. The activity panel has buttons with
  // similar names ("Curtidas"), so only non-button tabs count.
  const LIBRARY_TABS = {
    liked: {
      item: '[data-e2e="user-liked-item"]',
      tab: () => document.querySelector('[data-e2e="liked-tab"]') || findProfileTab(/^(curtid|liked)/i),
      name: "Curtidos"
    },
    favorites: {
      item: '[data-e2e="favorites-item"]',
      tab: () => document.querySelector('[data-e2e="favorites-tab"]') || findProfileTab(/^(favorit|saved|salvo)/i),
      name: "Favoritos"
    }
  };
  const LIBRARY_LIMIT = 500;

  function findProfileTab(pattern) {
    return [...document.querySelectorAll('[role="tab"]')].find(
      tab => tab.tagName !== "BUTTON" && pattern.test(normalizedText(tab.innerText))
    );
  }

  // One short step of a progressive listing. The page keeps its own state, so
  // the caller can poll while the list is already in use: open the tab once,
  // then every call harvests the cards in view and scrolls for more.
  async function libraryStep(kind) {
    const spec = LIBRARY_TABS[kind];
    if (!spec) throw new Error("Lista desconhecida.");
    let state = window.__accessibleLibrary;
    if (!state || state.kind !== kind) {
      state = window.__accessibleLibrary = {kind, items: new Map(), idle: 0, opened: false};
    }
    if (!state.opened) {
      let deadline = Date.now() + 10000;
      let tab = spec.tab();
      while (!tab && Date.now() < deadline) {
        await sleep(250);
        tab = spec.tab();
      }
      if (!tab) throw new Error(`Não encontrei a aba ${spec.name} no seu perfil. Verifique se está logado (F6).`);
      if (tab.getAttribute("aria-selected") !== "true") {
        try { await trustedClick(tab); } catch (_error) { tab.click(); }
      }
      deadline = Date.now() + 10000;
      while (!document.querySelector(spec.item) && Date.now() < deadline) await sleep(250);
      state.opened = true;
    }
    const before = state.items.size;
    const items = [...document.querySelectorAll(spec.item)];
    for (const item of items) {
      const anchor = item.querySelector('a[href*="/video/"]');
      if (!anchor) continue;
      let url;
      try { url = new URL(anchor.href, location.href); } catch (_error) { continue; }
      const match = url.pathname.match(/\/(\@[^/?#]+)\/video\/(\d+)/);
      if (!match) continue;
      const link = `https://www.tiktok.com/${match[1]}/video/${match[2]}`;
      if (state.items.has(link)) continue;
      const image = item.querySelector("img");
      state.items.set(link, {
        url: link,
        author: decodeURIComponent(match[1]),
        description: normalizedText((image && (image.alt || image.getAttribute("aria-label"))) ||
                                    anchor.getAttribute("aria-label") || anchor.title || "")
      });
    }
    if (state.items.size > before) state.idle = 0; else state.idle += 1;
    const done = state.items.size >= LIBRARY_LIMIT || state.idle >= 5;
    if (!done) {
      // TikTok loads more cards only when the last row reaches the viewport.
      if (items.length) items[items.length - 1].scrollIntoView({block: "end"});
      window.scrollBy(0, window.innerHeight);
      await sleep(700);
    }
    return {results: [...state.items.values()].slice(0, LIBRARY_LIMIT), library: kind, done};
  }

  async function leavePhotoPosts(action) {
    const found = await skipPhotoPosts(action === "next" ? 1 : -1, Date.now() + 10000);
    stabilizeAudio();
    if (!found) throw new Error("Só há publicações de fotos nessa direção. Tente novamente ou use o outro sentido.");
    return snapshot();
  }

  async function execute(action, argument) {
    if (action === "own_profile") return ownProfile();
    if (action === "library_step") return libraryStep(argument);
    // The top-level page can finish loading before TikTok mounts the first
    // video. Both explicit playback and the automatic details refresh run at
    // that boundary, so give the player time to appear instead of reporting a
    // false failure while TikTok starts it in the background.
    if (["play", "refresh_info"].includes(action)) {
      const deadline = Date.now() + 8000;
      while (!activeVideo() && !photoPost() && Date.now() < deadline) await sleep(150);
    }
    if (action === "profile_follow") {
      return profileFollowAction(Boolean(argument?.toggle), argument?.profile_url || "");
    }
    const video = activeVideo();
    if (!["diagnostics", "collect_search_results", "close_comments", "toggle_live_chat", "read_live_chat"].includes(action) && !video) {
      if (photoPost()) {
        if (action === "next" || action === "previous") return leavePhotoPosts(action);
        throw new Error("Esta é uma publicação de fotos. Use próximo ou anterior para ir a um vídeo.");
      }
      throw new Error("Não foi possível localizar o vídeo atual.");
    }
    if (action === "collect_search_results") {
      const deadline = Date.now() + 12000;
      const collected = new Map();
      let firstResultAt = 0;
      let lastGrowthAt = 0;
      let profileScrolls = 0;
      const collectingProfile = argument === "profile";
      const collectingMore = argument?.mode === "more";
      const requiredSearchScrolls = collectingMore ? 12 : 8;
      do {
        const result = collectSearchResults();
        const before = collected.size;
        for (const item of result.results) collected.set(item.url, item);
        const now = Date.now();
        if (collected.size && !firstResultAt) firstResultAt = now;
        if (collected.size > before) lastGrowthAt = now;
        // TikTok virtualizes older cards as more results render. Preserve
        // every valid card seen during a short settling window.
        const settledSearch = firstResultAt && profileScrolls >= requiredSearchScrolls && now - lastGrowthAt >= 1200;
        // Profile grids load more rows only after scrolling.  Do not stop at
        // the first visible row: keep going until several scrolls produced no
        // new card, preserving pinned/newest-to-oldest DOM order in the map.
        const settledProfile = firstResultAt && profileScrolls >= 5 && now - lastGrowthAt >= 1200;
        if (collected.size >= 50 || (collectingProfile ? settledProfile : settledSearch)) {
          return {results: [...collected.values()]};
        }
        if (collected.size) {
          window.scrollBy(0, window.innerHeight);
          profileScrolls += 1;
        }
        if (/\/login/.test(location.pathname)) throw new Error("Faça login no TikTok pela página (F6).");
        await sleep(300);
      } while (Date.now() < deadline);
      return {results: [...collected.values()]};
    }
    if (action === "seek") {
      if (![-30, -15, 15, 30].includes(argument)) throw new Error("Intervalo inválido.");
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        throw new Error("Este vídeo ainda não permite avançar ou voltar no tempo.");
      }
      video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + argument));
      return {position: video.currentTime};
    }
    if (["author", "description", "copy_link", "refresh_info", "download_link"].includes(action)) {
      const info = snapshot();
      if (action === "author") {
        const FOLLOW_SELECTORS = [
          "button[data-e2e=feed-follow]", "button[data-e2e=video-author-follow]",
          "[role=button][aria-label*='seguir' i]", "[role=button][aria-label*='follow' i]",
          "[role=button][aria-label*='seguindo' i]", "[role=button][aria-label*='following' i]"
        ];
        const btn = findNearVideo(FOLLOW_SELECTORS);
        const state = followState(btn);
        info.follow_state = state;
        info.needs_profile_follow = state === null && Boolean(info.profile_url);
      }
      if (action === "download_link") return {...info, media_url: downloadMedia(video, info.link || "")};
      if (action === "copy_link" && !info.link) {
        try {
          return await copyLinkFromTikTok(video);
        } catch (error) {
          // The DOM may have settled (author/video id now resolvable) by the
          // time the fragile share-panel click failed. Prefer copying the
          // link ourselves over surfacing an avoidable UI error.
          const retryLink = snapshot().link;
          if (retryLink) return {...info, link: retryLink};
          throw error;
        }
      }
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
      const triggerNavClick = async () => {
        const nearby = findNearVideo(selectors);
        const button = (onScreen(nearby) && nearby) ||
          [...document.querySelectorAll(selectors.join(","))].find(onScreen);
        // Scrolling a navigation button into the center can move a scroll-snap
        // feed back onto the current item before the click even reaches TikTok.
        if (button) await trustedClick(button, false);
        else scrollFeed(video, action === "next" ? 1 : -1);
      };
      const moved = current => current && (current !== video ||
        (current.currentSrc || current.getAttribute("src")) !== source ||
        snapshot().link !== link);
      // Try a real key press first -- it survives nav-button markup changes
      // that break the selectors/scroll fallback above. Give it a short
      // window before falling back, so a working key press isn't slowed
      // down by also clicking (which could then double-advance).
      const startItem = feedItem();
      await trustedKeyPress(action === "next" ? "ArrowDown" : "ArrowUp");
      let triedClick = false;
      const deadline = Date.now() + 4500;
      while (Date.now() < deadline) {
        await sleep(150);
        stabilizeAudio();
        if (photoPost()) {
          const info = await leavePhotoPosts(action);
          if (moved(activeVideo())) return info;
          break;
        }
        if (!moved(activeVideo())) {
          // Once on another item, its video is only still loading.
          if (!triedClick && Date.now() >= deadline - 3000 && feedItem() === startItem) {
            triedClick = true;
            await triggerNavClick();
          }
          continue;
        }
        // O vídeo seguinte já cobre a maior parte da tela enquanto a rolagem
        // ainda anima, e ela pode voltar ao vídeo anterior. Só lemos os
        // detalhes depois que o feed para de se mexer.
        await waitUntilSettled(deadline + 1500);
        stabilizeAudio();
        if (photoPost()) continue;
        if (moved(activeVideo())) return snapshot();
      }
      throw new Error("O TikTok não mudou de vídeo. Tente novamente ou use F6 para acessar a página.");
    }
    if (action === "toggle" || action === "play") {
      initialPlaybackReleased = true;
      if (video.paused) {
        const startPlayback = async candidate => {
          await Promise.race([candidate.play(), sleep(5000).then(() => {
            throw new Error("A reprodução não foi confirmada. Use Reproduzir ou pausar, ou F6 para verificar a página.");
          })]);
          scheduleAudioPreference(candidate);
        };
        try {
          await startPlayback(video);
        } catch (error) {
          // TikTok can briefly expose an empty video while replacing a search
          // result. Wait for its media source instead of exposing WebView's
          // "no supported source" error to the user.
          const isSourceError = value => value?.name === "NotSupportedError" ||
            /supported source/i.test(String(value?.message || value));
          if (!isSourceError(error)) throw error;
          const deadline = Date.now() + 8000;
          let started = false;
          while (Date.now() < deadline) {
            await sleep(150);
            const candidate = activeVideo();
            if (!candidate || !candidate.currentSrc ||
                candidate.readyState < HTMLMediaElement.HAVE_METADATA || candidate.error) continue;
            try {
              await startPlayback(candidate);
              started = true;
              break;
            } catch (retryError) {
              if (!isSourceError(retryError)) throw retryError;
            }
          }
          if (!started && video.paused && activeVideo()?.paused) {
            throw new Error("O vídeo ainda não disponibilizou uma fonte reproduzível. Aguarde alguns segundos e tente novamente.");
          }
        }
      } else if (action === "toggle") video.pause();
      // TikTok can swap the <video> element while a result opens; report the
      // one on screen now, not the stale element this command started with.
      const current = video.isConnected ? video : (activeVideo() || video);
      return {paused: current.paused};
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

    if (action === "toggle_follow") {
      const FOLLOW_SELECTORS = [
        "button[data-e2e=feed-follow]", "button[data-e2e=video-author-follow]",
        "[role=button][data-e2e=feed-follow]", "[role=button][data-e2e=video-author-follow]",
        "[role=button][aria-label*='seguir' i]", "[role=button][aria-label*='follow' i]"
      ];
      const video = activeVideo();
      if (!video) throw new Error("Não foi possível localizar o vídeo atual.");
      const info = snapshot();
      if (!info.profile_url) throw new Error("Não foi possível identificar o autor para conferir o seguimento.");
      if (activeVideo() !== video) throw new Error("O vídeo mudou. Repita a ação no vídeo atual.");
      let button = findNearVideo(FOLLOW_SELECTORS);
      if (!button) {
        for (const ancestor of ancestorsFor(video)) {
          button = [...ancestor.querySelectorAll("button, [role=button]")].find(element => {
            const text = normalizedText(element.getAttribute("aria-label") || element.textContent).toLowerCase();
            return visible(element) && /^(seguir|follow|seguindo|following)\b/.test(text);
          });
          if (button) break;
        }
      }
      if (!button) throw new Error("Este vídeo não oferece um botão para seguir ou deixar de seguir.");
      const visibleState = followState(button);
      const knownState = typeof argument?.known_follow_state === "boolean" ? argument.known_follow_state : null;
      if (visibleState === null && knownState === null) {
        // The feed's icon is actionable but has no accessible state. Ask the
        // profile only for the state, then come back here for the real click.
        return {...info, needs_follow_state: true, follow_click_sent: false};
      }
      const before = visibleState === null ? knownState : visibleState;
      await trustedClick(button, true, true);
      await sleep(1200);
      return {...info, expected_state: !before, follow_click_sent: true};
    }
    if (action === "not_interested") return markNotInterested();
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
      // Outside the try: when the panel did not open there is nothing to close,
      // and closing would press the close button of some other dialog.
      await openComments(video);
      try {
        const container = commentScrollContainer();
        const accumulated = new Map();
        for (const item of commentRows()) {
          accumulated.set(item.id, item);
        }
        let lastCount = accumulated.size;
        let staleCount = 0;
        let expansionsLeft = MAX_EXPANSIONS;
        const expanded = new WeakSet();
        const deadline = Date.now() + 18000;
        while (Date.now() < deadline && staleCount < 6) {
          if (container && container.scrollHeight > container.clientHeight) {
            container.scrollTop = container.scrollHeight;
            container.dispatchEvent(new Event('scroll', {bubbles: true}));
          }
          const candidates = document.querySelectorAll(COMMENT_LIST);
          for (const el of candidates) {
            if (el.scrollHeight > el.clientHeight + 20) {
              el.scrollTop = el.scrollHeight;
              el.dispatchEvent(new Event('scroll', {bubbles: true}));
            }
          }
          const items = commentElements();
          if (items.length) {
            try { items[items.length - 1].scrollIntoView({block: "end", behavior: "instant"}); } catch (_) {}
          }
          const expanders = expansionsLeft > 0 ? replyExpanders() : [];
          for (const button of expanders.filter(item => !expanded.has(item)).slice(0, expansionsLeft)) {
            expanded.add(button);
            expansionsLeft -= 1;
            try { await trustedClick(button); } catch (_) {}
          }
          await sleep(500);
          for (const item of commentRows()) {
            accumulated.set(item.id, item);
          }
          if (accumulated.size > lastCount) {
            lastCount = accumulated.size;
            staleCount = 0;
          } else {
            staleCount++;
          }
        }
        return {comments: Array.from(accumulated.values())};
      } finally {
        // Best-effort: a failed close must not discard comments already
        // read successfully above by replacing the return with this error.
        try { await closeComments(); } catch (_) {}
      }
    }
    if (action === "reply_comment") {
      await openComments(video);
      const identifier = typeof argument === "object" ? argument.replyTo || argument.id : argument;
      const text = typeof argument === "object" ? argument.replyText || argument.text : "";
      return {replyTo: normalizedText((await replyToComment(identifier, text)).innerText)};
    }
    if (action === "post_comment") {
      const text = normalizedText(typeof argument === "object" ? argument.text : String(argument || ""));
      if (!text) throw new Error("Digite um comentário antes de publicar.");
      await openComments(video);
      try {
        const replyTo = typeof argument === "object" ? argument.replyTo : "";
        const editors = () => [...document.querySelectorAll(
          "[data-e2e=comment-input] [contenteditable=true], [contenteditable=true][role=textbox]"
        )].filter(visible);
        const inComment = element => element.closest(
          "[data-e2e=comment-level-1], [data-e2e=comment-item], [class*='CommentItem'], [class*='ReplyContainer']");
        let editor = null;
        if (replyTo) {
          const before = new Set(editors());
          const comment = await replyToComment(replyTo, argument.replyText);
          const follows = element => comment.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING;
          // The reply box is inside the replied comment, or a reply field after it, or a field
          // Responder just opened. The main field is never used: the reply would become a comment.
          const replyBox = () => {
            const boxes = editors().filter(element => comment.contains(element) || !before.has(element) ||
              (inComment(element) && follows(element)));
            return boxes.find(element => comment.contains(element)) || boxes.find(follows) || boxes[0] || null;
          };
          for (const limit = Date.now() + 2000; Date.now() < limit && !editor; await sleep(100)) editor = replyBox();
          if (!editor) throw new Error("A caixa de resposta do TikTok não abriu. Nada foi enviado.");
        } else {
          // A new comment never goes into a reply box left open inside a comment.
          editor = editors().find(element => !inComment(element)) || editors()[0];
        }
        const sameVideo = () => commentsVideo && commentsVideo.video === activeVideo() &&
          commentsVideo.source === video.currentSrc && commentsVideo.link === snapshot().link;
        if (!sameVideo()) throw new Error("O vídeo mudou. O comentário não foi enviado.");
        if (!editor) throw new Error("Não foi possível localizar o campo de comentário.");
        // A reply may start with the mention TikTok fills in; anything else is the person's draft.
        const prefix = normalizedText(editor.textContent);
        if (prefix && !(replyTo && /^@\S+$/.test(prefix))) {
          throw new Error("Há um rascunho na página. Revise-o antes de publicar.");
        }
        const expected = normalizedText(`${prefix} ${text}`);
        // TikTok's editor ignores text set from script, so the application types it
        // as trusted keyboard input after a real click places the caret in the field.
        await trustedClick(editor);
        // The click may land inside a mention; type after everything already in the field.
        const caret = document.createRange();
        caret.selectNodeContents(editor);
        caret.collapse(false);
        getSelection().removeAllRanges();
        getSelection().addRange(caret);
        const typed = await transport.runtime.sendMessage({type: "accessible-reels-trusted-text", text});
        if (!typed?.ok) throw new Error(typed?.error || "Não foi possível digitar o comentário.");
        // The button of the editor in use, so a reply is not sent by the main field's button.
        // A new comment keeps the page-wide search by name as a last resort.
        const findPost = () => postButtonFor(editor) || (replyTo ? null :
          [...document.querySelectorAll(POST_CANDIDATES)].find(element =>
            enabledControl(element) && POST_NAME.test(controlName(element))) || null);
        let post = null;
        for (const limit = Date.now() + 2000; Date.now() < limit && !post; await sleep(100)) {
          if (normalizedText(editor.textContent) === expected) post = findPost();
        }
        if (normalizedText(editor.textContent) !== expected) {
          throw new Error("O TikTok não aceitou o texto digitado. Nada foi enviado.");
        }
        if (!post) {
          const error = new Error("Não foi possível localizar Publicar comentário. O texto ficou no campo do TikTok; " +
            "confira pela página (F6) antes de tentar de novo.");
          error.details = describePostArea(editor);
          throw error;
        }
        if (!sameVideo()) throw new Error("O vídeo mudou. O comentário não foi enviado.");
        await trustedClick(post);
        const shown = () => commentRows().map(row => normalizedText(row.text)).concat(
          [...document.querySelectorAll("[data-e2e=comment-level-2], [data-e2e=comment-reply-item]")]
            .filter(visible).map(element => normalizedText(element.innerText)));
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          await sleep(200);
          if (sameVideo() && !(editor.isConnected && normalizedText(editor.textContent)) &&
              shown().some(row => row.includes(text))) return {};
        }
        throw new Error("O envio não foi confirmado. Confira os comentários antes de tentar novamente.");
      } finally {
        // Same reasoning as the "comments" handler: don't let a failed close
        // mask a comment that was already confirmed as posted above.
        try { await closeComments(); } catch (_) {}
      }
    }
    if (action === "close_comments") {
      await closeComments();
      return {};
    }
    if (action === "toggle_live_chat") {
      if (!isLivePage()) throw new Error("Você não está em uma live.");
      if (argument?.force_stop || (liveChatReading && !argument?.force_start)) {
        stopLiveChatObserver();
        return { ok: true, active: false };
      }
      const elements = await resolveLiveChatElements(4000);
      if (!elements.length) {
        throw new Error("O chat da live ainda está carregando ou não está disponível.");
      }
      startLiveChatObserver();
      const recent = extractLiveChatMessages(15);
      return {
        ok: true,
        active: true,
        messages: recent.ok ? recent.messages : [],
        count: recent.ok ? recent.count : 0
      };
    }
    if (action === "read_live_chat") {
      if (!isLivePage()) throw new Error("Você não está em uma live.");
      const elements = await resolveLiveChatElements(3000);
      if (!elements.length) {
        throw new Error("O chat da live ainda está carregando ou não está disponível.");
      }
      const recent = extractLiveChatMessages(5);
      return {
        ok: true,
        messages: recent.ok ? recent.messages : [],
        count: recent.ok ? recent.count : 0
      };
    }
    if (action === "diagnostics") {
      const active = activeVideo();
      // The scope findNearVideo searches for curtir/favoritar/compartilhar: the
      // outermost ancestor that still (mostly) belongs only to this video.
      const likeScope = active ? ancestorsFor(active).slice(-1)[0] : null;
      const likeMatches = [...document.querySelectorAll(LIKE_SELECTORS.join(","))].filter(visible);
      return {message: `Extensão conectada; página ${location.hostname}; ` +
        `${document.querySelectorAll("video").length} vídeo(s); ` +
        `vídeo ativo ${active ? "sim" : "não"}; ${sharePanelDiagnostics()}`,
        report: JSON.stringify({
          controls: active ? describeControls(active) : null,
          likeScopeHtml: anonymizedOuterHTML(likeScope),
          likeMatchesDocumentWide: likeMatches.length,
          likeMatchesHtml: likeMatches.slice(0, 2).map(element => anonymizedOuterHTML(element, 1500)),
        })};
    }
    throw new Error("Comando desconhecido recebido pela extensão.");
  }

  transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "accessible-reels-command") return false;
    execute(message.action, message.argument)
      .then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error && error.message ? error.message : String(error),
        details: error && error.details}));
    return true;
  });
})();
