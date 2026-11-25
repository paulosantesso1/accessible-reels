(() => {
  if (window !== top || globalThis.__accessibleTransport) return;
  let listener;
  let commandToken = null;
  let clickId = 0;
  const waiting = new Map();
  const key = 'accessible-reels-audio';
  // Every network starts audible at the same volume until the person chooses one.
  const audioDefaults = {};
  for (const network of ['', 'Instagram', 'YouTube']) {
    audioDefaults[`accessibleReels${network}Volume`] = 0.5;
    audioDefaults[`accessibleReels${network}Muted`] = false;
  }
  globalThis.__accessibleTransport = {
    storage: {local: {
      get: async () => {
        let saved = {};
        try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch (_) {}
        return {...audioDefaults, ...saved};
      },
      set: async values => {
        let previous = {};
        try { previous = JSON.parse(localStorage.getItem(key) || '{}'); } catch (_) {}
        localStorage.setItem(key, JSON.stringify({...previous, ...values}));
      }
    }},
    runtime: {
      onMessage: {addListener: fn => { listener = fn; }},
      sendMessage: message => {
        const kind = {
          'accessible-reels-trusted-click': 'click',
          'accessible-reels-trusted-key': 'key',
          'accessible-reels-trusted-text': 'text',
        }[message.type];
        if (!kind || !commandToken) {
          return Promise.resolve({ok:false, error:'Nenhum comando do aplicativo em execução.'});
        }
        return new Promise(resolve => {
          const id = ++clickId;
          const timeout = setTimeout(() => { waiting.delete(id); resolve({ok:false, error:'O aplicativo não respondeu a tempo.'}); }, 5000);
          waiting.set(id, result => { clearTimeout(timeout); resolve(result); });
          let payload;
          if (kind === 'click') {
            payload = {type:'click', token:commandToken, id, x:message.x, y:message.y, follow_diagnostic: message.follow_diagnostic};
          } else if (kind === 'key') {
            payload = {type:'key', token:commandToken, id, key:message.key};
          } else {
            payload = {type:'text', token:commandToken, id, text:message.text};
          }
          window.reelsHost.postMessage(JSON.stringify(payload));
        });
      }
    }
  };
  globalThis.__accessibleClickDone = (id, result) => {
    waiting.get(id)?.(result);
    waiting.delete(id);
  };
  globalThis.__accessibleIsReady = () => typeof listener === 'function';
  globalThis.__accessibleRun = async (action, argument, token, platform) => {
    if (commandToken) return {ok:false, error:'Aguarde o comando anterior.'};
    if (!listener) return {ok:false, error:'Os controles ainda estão carregando.'};
    commandToken = token;
    try {
      return await new Promise(resolve => listener({type:'accessible-reels-command',platform,action,argument}, {}, resolve));
    } finally { commandToken = null; }
  };
  globalThis.__accessibleSetActive = active => {
    globalThis.__accessibleNetworkActive = Boolean(active);
    if (!active) document.querySelectorAll('video,audio').forEach(v => v.pause());
  };
  globalThis.__accessibleNetworkActive = true;
  document.addEventListener('play', event => {
    if (!globalThis.__accessibleNetworkActive && event.target instanceof HTMLMediaElement) event.target.pause();
  }, true);
})();
(() => {
    // Prevent the web page from stealing our Alt shortcuts!
    window.addEventListener('keydown', (e) => {
        if (e.altKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'p', 'P', 'a', 'A', 'd', 'D', 'c', 'C', 'e', 'E', 'l', 'L', 'f', 'F', 's', 'S', 'm', 'M'].includes(e.key)) {
            // Stop propagation so YouTube/TikTok don't receive it and play sounds/block it
            e.stopImmediatePropagation();
        }
    }, true);
})();
