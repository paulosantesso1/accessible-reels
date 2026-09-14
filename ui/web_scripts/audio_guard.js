(() => {
  if (globalThis.__accessibleReelsAudioGuard) return;
  globalThis.__accessibleReelsAudioGuard = true;

  let preferredVolume = null;
  let preferredMuted = null;
  const mediaPrototype = HTMLMediaElement.prototype;
  const volumeDescriptor = Object.getOwnPropertyDescriptor(mediaPrototype, "volume");
  const mutedDescriptor = Object.getOwnPropertyDescriptor(mediaPrototype, "muted");
  const nativePlay = mediaPrototype.play;

  // Plataformas podem pausar no visibilitychange, pagehide ou ao consultar
  // document.hidden. A plataforma ativa continua audível ao minimizar; a troca
  // real ainda pausa a mídia diretamente por __accessibleSetActive(false).
  const active = () => globalThis.__accessibleNetworkActive === true;
  const stopWhenActive = event => {
    if (active()) event.stopImmediatePropagation();
  };
  document.addEventListener("visibilitychange", stopWhenActive, true);
  document.addEventListener("webkitvisibilitychange", stopWhenActive, true);
  window.addEventListener("pagehide", stopWhenActive, true);
  window.addEventListener("freeze", stopWhenActive, true);

  const inheritedDescriptor = name => {
    let owner = document;
    while (owner) {
      const descriptor = Object.getOwnPropertyDescriptor(owner, name);
      if (descriptor) return descriptor;
      owner = Object.getPrototypeOf(owner);
    }
    return null;
  };
  const maskVisibility = (name, visibleValue) => {
    const descriptor = inheritedDescriptor(name);
    if (!descriptor || typeof descriptor.get !== "function") return;
    try {
      Object.defineProperty(document, name, {
        configurable: true,
        get() { return active() ? visibleValue : descriptor.get.call(document); }
      });
    } catch (_error) {}
  };
  maskVisibility("hidden", false);
  maskVisibility("webkitHidden", false);
  maskVisibility("visibilityState", "visible");

  const apply = media => {
    if (!(media instanceof HTMLMediaElement)) return;
    if (preferredVolume !== null && volumeDescriptor) {
      const current = volumeDescriptor.get.call(media);
      if (Math.abs(current - preferredVolume) > 0.005) {
        volumeDescriptor.set.call(media, preferredVolume);
      }
    }
    if (preferredMuted !== null && mutedDescriptor &&
        mutedDescriptor.get.call(media) !== preferredMuted) {
      mutedDescriptor.set.call(media, preferredMuted);
    }
  };

  if (volumeDescriptor && volumeDescriptor.configurable) {
    Object.defineProperty(mediaPrototype, "volume", {
      ...volumeDescriptor,
      set(value) {
        volumeDescriptor.set.call(this,
          preferredVolume === null ? value : preferredVolume);
      }
    });
  }
  if (mutedDescriptor && mutedDescriptor.configurable) {
    Object.defineProperty(mediaPrototype, "muted", {
      ...mutedDescriptor,
      set(value) {
        mutedDescriptor.set.call(this,
          preferredMuted === null ? value : preferredMuted);
      }
    });
  }
  mediaPrototype.play = function(...args) {
    apply(this);
    return nativePlay.apply(this, args);
  };

  document.addEventListener("accessible-reels-volume-preference", event => {
    try {
      const preference = JSON.parse(event.detail || "{}");
      preferredVolume = Number.isFinite(preference.volume) ?
        Math.max(0, Math.min(1, preference.volume)) : null;
      preferredMuted = typeof preference.muted === "boolean" ? preference.muted : null;
      document.querySelectorAll("video, audio").forEach(apply);
    } catch (_error) {}
  });

  new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node instanceof HTMLMediaElement) apply(node);
        node.querySelectorAll("video, audio").forEach(apply);
      }
    }
  }).observe(document, {childList: true, subtree: true});

  for (const eventName of ["loadedmetadata", "play", "playing"]) {
    document.addEventListener(eventName, event => apply(event.target), true);
  }
})();
