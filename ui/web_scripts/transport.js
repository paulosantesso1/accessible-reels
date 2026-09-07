(() => {
  if (window !== top || globalThis.__accessibleTransport) return;
  let listener;
  let commandToken = null;
  let clickId = 0;
  const waiting = new Map();
  const key = 'accessible-reels-audio';
  globalThis.__accessibleTransport = {
    storage: {local: {
      get: async () => { try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch (_) { return {}; } },
      set: async values => {
        let previous = {};
        try { previous = JSON.parse(localStorage.getItem(key) || '{}'); } catch (_) {}
        localStorage.setItem(key, JSON.stringify({...previous, ...values}));
      }
    }},
    runtime: {
      onMessage: {addListener: fn => { listener = fn; }},
      sendMessage: message => {
        if (message.type !== 'accessible-reels-trusted-click' || !commandToken) {
          return Promise.resolve({ok:false, error:'Nenhum comando do aplicativo em execução.'});
        }
        return new Promise(resolve => {
          const id = ++clickId;
          const timeout = setTimeout(() => { waiting.delete(id); resolve({ok:false, error:'O clique não respondeu a tempo.'}); }, 5000);
          waiting.set(id, result => { clearTimeout(timeout); resolve(result); });
          window.reelsHost.postMessage(JSON.stringify({type:'click', token:commandToken, id, x:message.x, y:message.y}));
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
