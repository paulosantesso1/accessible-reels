(() => {
  if (globalThis.__accessibleInstagramInstalled) return;
  globalThis.__accessibleInstagramInstalled = true;
  const transport = globalThis.__accessibleTransport;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  let queue = Promise.resolve();
  let commentsVideo = null;
  let preferredVolume = null;
  let preferredMuted = null;
  const watched = new WeakSet();
  const applying = new WeakSet();
  const audioKeys = {volume: "accessibleReelsInstagramVolume", muted: "accessibleReelsInstagramMuted"};

  function publishAudio() {
    document.dispatchEvent(new CustomEvent("accessible-reels-volume-preference", {
      detail: JSON.stringify({volume: preferredVolume, muted: preferredMuted})
    }));
  }
  function applyAudio(video) {
    if (preferredVolume === null || applying.has(video)) return;
    applying.add(video);
    try {
      if (Math.abs(video.volume - preferredVolume) > 0.005) video.volume = preferredVolume;
      if (preferredMuted !== null && video.muted !== preferredMuted) video.muted = preferredMuted;
    } finally { applying.delete(video); }
  }
  function stabilizeAudio() {
    for (const video of document.querySelectorAll("video")) {
      if (!watched.has(video)) {
        watched.add(video);
        for (const name of ["volumechange", "play", "playing", "loadedmetadata", "canplay"]) {
          video.addEventListener(name, () => applyAudio(video));
        }
      }
      applyAudio(video);
    }
  }
  const audioReady = transport.storage.local.get(Object.values(audioKeys)).then(values => {
    if (Number.isFinite(values[audioKeys.volume])) preferredVolume = Math.max(0, Math.min(1, values[audioKeys.volume]));
    if (typeof values[audioKeys.muted] === "boolean") preferredMuted = values[audioKeys.muted];
  }).catch(() => {}).finally(() => { publishAudio(); stabilizeAudio(); });
  new MutationObserver(stabilizeAudio).observe(document, {childList: true, subtree: true});
  setInterval(stabilizeAudio, 250);

  function visible(element) {
    if (!element || !element.isConnected) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" &&
      style.visibility !== "hidden" && Number(style.opacity || 1) > 0;
  }
  function activeVideo() {
    const candidates = [...document.querySelectorAll("video")].filter(visible).map(video => {
      const r = video.getBoundingClientRect();
      return {video, area: Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) *
        Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0))};
    }).filter(item => item.area > 0);
    candidates.sort((a, b) => b.area - a.area);
    return candidates[0]?.video || null;
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
          applyAudio(video);
          video.play().catch(() => {});
        } else if (Date.now() < deadline) probe();
      }, 750);
    };
    probe();
  }
  setTimeout(startInitialPlaybackWhenReady, 0);
  function reelRoot(video = activeVideo()) {
    let root = video;
    for (let p = video?.parentElement; p && p !== document.body; p = p.parentElement) {
      if ([...p.querySelectorAll("video")].some(item => item !== video)) break;
      // Never include the global sidebar, or a dialog belonging to another action.
      if (p.matches("main, [role=main]") || p.querySelector("nav")) break;
      root = p;
    }
    return root;
  }
  function label(element) {
    return clean(element.getAttribute("aria-label") || element.getAttribute("title") ||
      element.querySelector("svg[aria-label],img[alt]")?.getAttribute("aria-label") ||
      element.querySelector("img[alt]")?.getAttribute("alt") || element.textContent);
  }
  function buttonNamed(root, pattern) {
    if (!root) return null;
    const candidates = [...root.querySelectorAll("button,[role=button],svg[aria-label]")]
      .filter(el => visible(el) && pattern.test(label(el)))
      .map(el => el.closest("button,[role=button]") || el);
    // Nested role=button wrappers exist around Save. Prefer the actual inner button.
    return candidates.find(el => !candidates.some(other => other !== el && el.contains(other))) || null;
  }
  async function click(element) {
    if (!visible(element) || element.disabled || element.getAttribute("aria-disabled") === "true") {
      throw new Error("O controle não está disponível no Instagram.");
    }
    element.scrollIntoView({block: "nearest", inline: "nearest"});
    await sleep(80);
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!hit || (hit !== element && !element.contains(hit))) {
      throw new Error("Outro painel está cobrindo o controle. Feche-o no Instagram antes de continuar.");
    }
    const result = await transport.runtime.sendMessage({
      type: "accessible-reels-trusted-click", x: rect.left + rect.width / 2, y: rect.top + rect.height / 2
    });
    if (!result?.ok) throw new Error(result?.error || "O navegador recusou o clique.");
  }
  async function waitFor(read, message, timeout = 5000) {
    const deadline = Date.now() + timeout;
    do {
      const value = read();
      if (value) return value;
      await sleep(150);
    } while (Date.now() < deadline);
    throw new Error(message);
  }
  function canonicalLink(value) {
    try {
      const url = new URL(value, location.href);
      const match = url.pathname.match(/^\/(reels?|p)\/([\w-]+)\/?$/);
      if (url.protocol !== "https:" || !["www.instagram.com", "instagram.com"].includes(url.hostname) ||
          url.username || url.password || url.port || !match || match[2] === "audio") return "";
      return `https://www.instagram.com/${match[1] === "p" ? "p" : "reel"}/${match[2]}/`;
    } catch (_error) { return ""; }
  }
  function snapshot() {
    const video = activeVideo();
    if (!video) throw new Error("Abra um Reel no Instagram antes de usar os controles.");
    const root = reelRoot(video);
    const anchors = [...root.querySelectorAll("a[href]")];
    const profile = anchors.find(a => /^\/[\w.]+\/reels\/?$/.test(new URL(a.href).pathname)) ||
      anchors.find(a => /^\/[\w.]+\/$/.test(new URL(a.href).pathname) && !/^\/(?:reels|explore|direct|accounts)\//.test(new URL(a.href).pathname));
    const author = profile ? `@${new URL(profile.href).pathname.split("/")[1]}` : "Autor não encontrado";
    const group = video.closest('[role="group"]') || root;
    const captions = [...group.querySelectorAll("button,[role=button]")].filter(el =>
      !el.contains(video) && !el.querySelector("button,[role=button],svg") &&
      !el.getAttribute("aria-label") && clean(el.textContent) &&
      !/^(seguir|seguindo|follow|following|\d[\d.,\s]*|mais|more)$/i.test(clean(el.textContent)));
    const description = clean(captions[0]?.textContent).replace(/\s*…?\s*(mais|more)$/i, "").replace(/\s*…$/, "") ||
      clean(root.querySelector("h1")?.textContent) || "Descrição não encontrada";
    const link = anchors.map(a => canonicalLink(a.href)).find(Boolean) || canonicalLink(location.href);
    return {author, description, link};
  }
  function commentDialog() {
    return [...document.querySelectorAll('[role="dialog"]')].find(el => visible(el) &&
      /comentários|comments/i.test(el.innerText));
  }
  function commentRows(dialog) {
    const rows = [];
    for (const time of dialog.querySelectorAll("time")) {
      let row = time;
      for (let p = time.parentElement; p && p !== dialog; p = p.parentElement) {
        if (p.querySelectorAll("time").length > 1 || p.querySelector("input,textarea")) break;
        row = p;
      }
      const text = clean(row.innerText);
      if (text && !rows.some(item => item.text === text)) {
        const id = row.getAttribute("data-accessible-reels-comment-id") || `accessible-reels-comment-${rows.length + 1}`;
        row.setAttribute("data-accessible-reels-comment-id", id);
        rows.push({id, text});
      }
      if (rows.length >= 200) break;
    }
    return rows;
  }
  async function closeComments() {
    const dialog = commentDialog();
    if (dialog) {
      const button = buttonNamed(dialog, /^(fechar|close)$/i);
      if (!button) throw new Error("Não foi possível localizar Fechar comentários.");
      await click(button);
      await waitFor(() => !commentDialog(), "O Instagram não fechou os comentários.", 2000);
    }
    commentsVideo = null;
  }
  async function openComments(video) {
    let dialog = commentDialog();
    if (!dialog) {
      const button = buttonNamed(reelRoot(video), /^(comentar|comment)(\s+.*)?$/i);
      if (!button) throw new Error("Não foi possível localizar Comentar neste Reel.");
      await click(button);
      dialog = await waitFor(commentDialog, "O Instagram não abriu os comentários.");
    }
    commentsVideo = {video, source: video.currentSrc, link: snapshot().link};
    await waitFor(() => commentRows(dialog).length || !dialog.querySelector('[role="status"]'),
      "Os comentários ainda estão carregando. Tente novamente.", 5000);
    return dialog;
  }
  async function replyToComment(dialog, identifier, text) {
    const rows = commentRows(dialog);
    const target = rows.find(item => item.id === String(identifier || "")) ||
      rows.find(item => item.text === clean(text));
    if (!target) throw new Error("O comentário selecionado não está mais disponível.");
    const element = document.querySelector(`[data-accessible-reels-comment-id="${CSS.escape(target.id)}"]`);
    const reply = buttonNamed(element, /^(responder|reply)$/i);
    if (!reply) throw new Error("Não foi possível localizar Responder neste comentário.");
    await click(reply);
    return clean(element.innerText);
  }
  async function toggleSocial(pattern, undoPattern, name) {
    const video = activeVideo();
    const button = buttonNamed(reelRoot(video), pattern);
    if (!button) throw new Error(`Não foi possível localizar ${name} no Reel atual.`);
    const before = undoPattern.test(label(button));
    await click(button);
    const state = () => {
      if (activeVideo() !== video) throw new Error("O Reel mudou durante o comando; confira o estado antes de repetir.");
      const current = buttonNamed(reelRoot(video), pattern);
      return current && undoPattern.test(label(current)) !== before;
    };
    await waitFor(state, `O Instagram não confirmou ${name}; confira o estado antes de repetir.`, 3500);
    await sleep(700);
    if (!state()) throw new Error(`O Instagram reverteu ${name}.`);
    return {state: !before};
  }
  function collectSearchResults() {
    const results = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('main a[href], [role="main"] a[href]')) {
      const url = canonicalLink(anchor.href);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const image = anchor.querySelector("img");
      const description = clean(image?.alt || anchor.getAttribute("aria-label") || anchor.textContent);
      results.push({url, author: "Instagram", description: description && !/^reel$/i.test(description) ?
        description : `Resultado ${results.length + 1}; abra para ler autor e descrição`});
      if (results.length >= 50) break;
    }
    return {results};
  }
  async function execute(action, argument) {
    await audioReady;
    if (action === "diagnostics") return {message: `Instagram conectado; ${document.querySelectorAll("video").length} vídeo(s); Reel ativo ${activeVideo() ? "sim" : "não"}.`};
    if (action === "collect_search_results") {
      const deadline = Date.now() + 6000;
      do {
        const result = collectSearchResults();
        if (result.results.length) return result;
        if (/\/accounts\//.test(location.pathname)) throw new Error("Faça login no Instagram pelo navegador.");
        await sleep(200);
      } while (Date.now() < deadline);
      return {results: []};
    }
    if (action === "close_comments") { await closeComments(); return {}; }
    const video = await waitFor(activeVideo, "Abra os Reels e faça login no Instagram pelo navegador.");
    if (action === "seek") {
      if (![-30, -15, 15, 30].includes(argument)) throw new Error("Intervalo inválido.");
      if (!Number.isFinite(video.duration) || video.duration <= 0) {
        throw new Error("Este vídeo ainda não permite avançar ou voltar no tempo.");
      }
      video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + argument));
      return {position: video.currentTime};
    }
    if (["author", "description", "refresh_info", "copy_link", "download_link"].includes(action)) {
      const info = snapshot();
      if (action === "download_link") return {...info, media_url: video.currentSrc || video.src || ""};
      if (action === "copy_link" && !info.link) throw new Error("Não foi possível identificar o link do Reel atual.");
      return info;
    }
    if (action === "next" || action === "previous") {
      await closeComments();
      const before = video.currentSrc;
      const nav = buttonNamed(document, action === "next" ?
        /^(navegar para o próximo reel|go to next reel|next reel)$/i :
        /^(navegar para o reel anterior|go to previous reel|previous reel)$/i);
      if (nav) {
        await click(nav);
      } else {
        // Instagram removes the arrow buttons in the narrower layout used by
        // the embedded WebView. Move to the adjacent loaded Reel instead.
        const currentRect = video.getBoundingClientRect();
        const candidates = [...document.querySelectorAll("video")]
          .filter(item => item !== video && visible(item))
          .map(item => ({item, rect: item.getBoundingClientRect()}))
          .filter(({rect}) => action === "next" ? rect.top > currentRect.top + 20 : rect.top < currentRect.top - 20)
          .sort((a, b) => action === "next" ? a.rect.top - b.rect.top : b.rect.top - a.rect.top);
        if (!candidates.length) {
          throw new Error(action === "next" ?
            "Não há um próximo Reel carregado." : "Você está no primeiro Reel carregado.");
        }
        candidates[0].item.scrollIntoView({block: "center", inline: "nearest"});
      }
      await waitFor(() => {const active = activeVideo(); return active && (active !== video || active.currentSrc !== before);},
        "O Instagram não mudou de Reel; você pode estar no início ou fim da lista.", 4000);
      await sleep(350);
      stabilizeAudio();
      return snapshot();
    }
    if (action === "toggle" || action === "play") {
      initialPlaybackReleased = true;
      if (video.paused) {
        applyAudio(video);
        await Promise.race([video.play(), sleep(3000).then(() => { throw new Error("Reprodução não confirmada. Interaja uma vez com o Reel no navegador."); })]);
      } else if (action === "toggle") video.pause();
      return {paused: video.paused};
    }
    if (["volume_up", "volume_down", "toggle_mute"].includes(action)) {
      if (preferredVolume === null) preferredVolume = video.volume;
      if (action === "toggle_mute") {
        preferredMuted = !(preferredMuted ?? (video.muted || video.volume === 0));
        if (!preferredMuted && preferredVolume === 0) preferredVolume = 0.05;
      } else {
        // Instagram can start muted with video.volume still at 1. Adjust from
        // audible silence, not the hidden full-volume value, before unmuting.
        const base = video.muted || preferredMuted === true || video.volume === 0 ? 0 : preferredVolume;
        const percent = Math.round(base * 100) + (action === "volume_up" ? 5 : -5);
        preferredVolume = Math.max(0, Math.min(100, percent)) / 100;
        preferredMuted = false;
      }
      publishAudio();
      stabilizeAudio();
      await transport.storage.local.set({[audioKeys.volume]: preferredVolume, [audioKeys.muted]: preferredMuted});
      return {volume: preferredVolume, muted: preferredMuted};
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
    if (action === "toggle_like") return toggleSocial(/^(curtir|descurtir|like|unlike)$/i, /^(descurtir|unlike)$/i, "a curtida");
    if (action === "toggle_favorite") return toggleSocial(/^(salvar|remover|remover dos salvos|save|unsave|remove)$/i, /^(remover|remover dos salvos|unsave|remove)$/i, "Salvar");
    if (action === "comments") {
      try {
        const dialog = await openComments(video);
        return {comments: commentRows(dialog)};
      } finally {
        await closeComments();
      }
    }
    if (action === "reply_comment") {
      const dialog = await openComments(video);
      const identifier = typeof argument === "object" ? argument.replyTo || argument.id : argument;
      const text = typeof argument === "object" ? argument.replyText || argument.text : "";
      return {replyTo: await replyToComment(dialog, identifier, text)};
    }
    if (action === "post_comment") {
      const text = String(typeof argument === "object" ? argument.text : argument || "").trim();
      if (!text) throw new Error("Digite um comentário antes de publicar.");
      try {
        const dialog = await openComments(video);
        const replyTo = typeof argument === "object" ? argument.replyTo : "";
        if (replyTo) await replyToComment(dialog, replyTo, argument.replyText);
        const sameReel = () => commentsVideo && commentsVideo.video === activeVideo() &&
          commentsVideo.source === video.currentSrc && commentsVideo.link === snapshot().link;
        if (!sameReel()) throw new Error("O Reel mudou. O comentário não foi enviado.");
        const editor = [...dialog.querySelectorAll('input[placeholder],textarea[placeholder]')]
          .find(el => visible(el) && /coment|comment/i.test(el.placeholder));
        if (!editor) throw new Error("Não foi possível localizar o campo de comentário.");
        if (editor.value.trim()) throw new Error("Há um comentário não enviado no navegador. Revise-o antes de publicar pela interface.");
        editor.focus();
        const prototype = editor.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(prototype, "value").set.call(editor, text);
        editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
        const post = await waitFor(() => buttonNamed(dialog, /^(publicar|post)$/i), "Não foi possível localizar Publicar comentário.", 2000);
        if (!sameReel()) throw new Error("O Reel mudou. O comentário não foi enviado.");
        await click(post);
        await waitFor(() => sameReel() && editor.isConnected && editor.value === "" &&
          commentRows(dialog).some(row => row.text.includes(clean(text))),
          "O envio não foi confirmado. Confira no Instagram antes de tentar novamente.", 4000);
        return {};
      } finally {
        await closeComments();
      }
    }
    throw new Error("Comando desconhecido recebido pela extensão do Instagram.");
  }
  function enqueue(action, argument) {
    const result = queue.then(() => execute(action, argument));
    queue = result.catch(() => {});
    return result;
  }
  function announce(message) {
    let status = document.getElementById("accessible-instagram-status");
    if (!status) {
      status = document.createElement("div");
      status.id = "accessible-instagram-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "assertive");
      status.setAttribute("aria-atomic", "true");
      Object.assign(status.style, {position: "fixed", width: "1px", height: "1px", overflow: "hidden", clipPath: "inset(50%)"});
      (document.body || document.documentElement).appendChild(status);
    }
    status.textContent = "";
    setTimeout(() => { status.textContent = message; }, 0);
  }
  function shortcutAction(event) {
    if (event.repeat || event.ctrlKey || event.metaKey || event.getModifierState?.("AltGraph")) return null;
    const key = event.key.toLowerCase();
    if (event.altKey && event.shiftKey) return ({arrowup: "volume_up", arrowdown: "volume_down", m: "toggle_mute", c: "comments"})[key];
    if (event.altKey) return ({arrowdown: "next", arrowup: "previous", p: "toggle", a: "author", d: "description", c: "copy_link", f12: "diagnostics", e: "search_page"})[key];
    if (event.shiftKey) return null;
    return ({f5: "refresh_info", l: "toggle_like", f: "toggle_favorite"})[key];
  }
  transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "accessible-reels-command" || message.platform !== "instagram") return false;
    enqueue(message.action, message.argument).then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error.message || "Falha no Instagram."}));
    return true;
  });
})();
