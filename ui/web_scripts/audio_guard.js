(() => {
  if (globalThis.__accessibleReelsAudioGuard) return;
  globalThis.__accessibleReelsAudioGuard = true;

  let preferredVolume = null;
  let preferredMuted = null;
  const mediaPrototype = HTMLMediaElement.prototype;
  const volumeDescriptor = Object.getOwnPropertyDescriptor(mediaPrototype, "volume");
  const mutedDescriptor = Object.getOwnPropertyDescriptor(mediaPrototype, "muted");
  const nativePlay = mediaPrototype.play;

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
