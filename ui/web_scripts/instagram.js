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
  // O Instagram começa a tocar assim que a primeira fonte aparece e depois
  // troca para a definitiva, reiniciando o vídeo. Até a liberação, qualquer
  // play antes da hora é desfeito logo no evento.
  for (const name of ["play", "playing"]) {
    document.addEventListener(name, event => {
      if (!initialPlaybackReleased && event.target instanceof HTMLVideoElement) event.target.pause();
    }, true);
  }
  // Logo depois de abrir um Reel, o Instagram costuma trocar o player e o
  // vídeo recomeça do zero. Isso acontece de duas formas: o elemento <video>
  // sai do documento e outro assume a tela, ou o mesmo elemento recebe uma
  // fonte nova (o elemento continua conectado, mas o tempo volta a zero).
  // Nos primeiros segundos, em qualquer um dos dois casos e no mesmo Reel, o
  // vídeo retoma de onde o anterior parou.
  function keepPositionAcrossPlayerSwap(first) {
    const deadline = Date.now() + 15000;
    const reelPath = () => location.pathname.replace(/^\/reels?\//, "");
    const path = reelPath();
    let tracked = first, source = first.currentSrc, position = 0;
    const resume = video => {
      if (position > 1 && video.currentTime < position) video.currentTime = position;
    };
    const timer = setInterval(() => {
      if (Date.now() > deadline) { clearInterval(timer); return; }
      // Outro Reel (próximo/anterior): o elemento ou a fonte nova são de outro
      // vídeo e não podem herdar a posição deste.
      if (reelPath() !== path) { clearInterval(timer); return; }
      if (!tracked.isConnected) {
        const next = activeVideo();
        if (!next || next === tracked) return;
        if (next.readyState < HTMLMediaElement.HAVE_METADATA) return;
        resume(next);
        tracked = next;
        source = next.currentSrc;
        position = Math.max(position, next.currentTime || 0);
        return;
      }
      const current = tracked.currentSrc;
      // Sem fonte: a troca está em andamento. Espera a nova ficar pronta.
      if (!current) return;
      if (current !== source) {
        if (tracked.readyState < HTMLMediaElement.HAVE_METADATA) return;
        resume(tracked);
        source = current;
      }
      position = Math.max(position, tracked.currentTime || 0);
    }, 50);
  }
  function startInitialPlaybackWhenReady() {
    const deadline = Date.now() + 12000;
    const release = video => {
      initialPlaybackReleased = true;
      if (!video) return;
      applyAudio(video);
      video.play().catch(() => {});
      keepPositionAcrossPlayerSwap(video);
    };
    const probe = () => {
      if (initialPlaybackReleased) return;
      const video = activeVideo();
      if (!video || !video.currentSrc || video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
        if (Date.now() < deadline) setTimeout(probe, 150);
        else release(video);
        return;
      }
      const source = video.currentSrc;
      video.pause();
      setTimeout(() => {
        const current = activeVideo();
        if (current === video && current.currentSrc === source &&
            current.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
          release(video);
        } else if (Date.now() < deadline) probe();
        else release(current);
      }, 750);
    };
    probe();
  }
  setTimeout(startInitialPlaybackWhenReady, 0);
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

    if (action === "toggle_follow") {
      const video = activeVideo();
      if (!video) throw new Error("Não foi possível localizar o vídeo atual.");
      const root = reelRoot(video);
      let btn = followButton(root);
      if (!btn) throw new Error("Botão de Seguir não encontrado. Pode ser seu próprio vídeo.");

      const beforeIsFollowing = followState(btn);
      if (beforeIsFollowing === null) {
        throw new Error("Não foi possível verificar o estado do botão Seguir. Use F6 para confirmar na página.");
      }
      await click(btn);
      
      const deadline = Date.now() + 3500;
      let afterIsFollowing = beforeIsFollowing;
      while (Date.now() < deadline) {
        await sleep(150);
        const currentButton = followButton(root);
        if (!currentButton || !currentButton.isConnected || !visible(currentButton)) {
            // Se o botão sumiu e não seguíamos, é porque começamos a seguir.
            if (!beforeIsFollowing) afterIsFollowing = true;
        } else {
            btn = currentButton;
            const state = followState(btn);
            if (state !== null) afterIsFollowing = state;
        }
        
        if (afterIsFollowing !== beforeIsFollowing) break;
      }
      if (afterIsFollowing === beforeIsFollowing) {
        throw new Error("A rede não confirmou a alteração de seguimento. Tente novamente.");
      }
      return { state: afterIsFollowing };
    }
    if (action === "not_interested") return markNotInterested();
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
      // The mention Instagram filled for a reply that was not sent; it would block the next comment.
      let leftoverMention = null;
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
        // Responder fills the field with "@author " shortly after the click.
        if (replyTo) {
          for (const limit = Date.now() + 1000; Date.now() < limit && !editor.value; ) await sleep(100);
        }
        const prefix = editor.value;
        if (prefix.trim() && !(replyTo && /^@[\w.]+\s*$/.test(prefix))) {
          throw new Error("Há um comentário não enviado no navegador. Revise-o antes de publicar pela interface.");
        }
        if (replyTo && prefix) leftoverMention = {editor, prefix};
        // A real click places the caret and the application types the approved text
        // as trusted keyboard input, so Instagram sees what a person would do.
        await click(editor);
        // Type after the mention; moving the caret sets no text.
        editor.setSelectionRange(prefix.length, prefix.length);
        const typed = await transport.runtime.sendMessage({type: "accessible-reels-trusted-text", text});
        if (!typed?.ok) throw new Error(typed?.error || "Não foi possível digitar o comentário.");
        await waitFor(() => editor.value === prefix + text, "O Instagram não aceitou o texto digitado. Nada foi enviado.", 2000);
        const post = await waitFor(() => {
          const button = buttonNamed(dialog, /^(publicar|post)$/i);
          return button && !button.disabled && button.getAttribute("aria-disabled") !== "true" ? button : null;
        }, "Não foi possível localizar Publicar comentário.", 2000);
        if (!sameReel()) throw new Error("O Reel mudou. O comentário não foi enviado.");
        await click(post);
        await waitFor(() => sameReel() && editor.isConnected && editor.value === "" &&
          commentRows(dialog).some(row => row.text.includes(clean(text))),
          "O envio não foi confirmado. Confira no Instagram antes de tentar novamente.", 4000);
        leftoverMention = null;
        return {};
      } catch (error) {
        // Only the untouched mention is removed; anything typed stays for the person to review.
        const leftover = leftoverMention;
        if (leftover && leftover.editor.isConnected && leftover.editor.value === leftover.prefix) {
          const prototype = leftover.editor.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(prototype, "value").set.call(leftover.editor, "");
          leftover.editor.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "deleteContentBackward"}));
        }
        throw error;
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
    return ({f5: "refresh_info"})[key];
  }
  transport.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "accessible-reels-command" || message.platform !== "instagram") return false;
    enqueue(message.action, message.argument).then(result => sendResponse({ok: true, ...result}))
      .catch(error => sendResponse({ok: false, error: error.message || "Falha no Instagram.", details: error.details}));
    return true;
  });
})();
