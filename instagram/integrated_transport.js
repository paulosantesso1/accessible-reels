(() => {
  let nextClick = 0;
  const waiting = new Map();
  globalThis.__accessibleInstagramClicks = [];
  globalThis.__accessibleInstagramClickDone = (id, result) => {
    waiting.get(id)?.(result);
    waiting.delete(id);
  };
  globalThis.__accessibleInstagramTransport = {
    storage: {local: {
      get: () => window.__accessibleInstagramHost("load", {}),
      set: values => window.__accessibleInstagramHost("save", values)
    }},
    runtime: {
      sendMessage: message => message.type === "accessible-reels-trusted-click"
        ? new Promise(resolve => {
          const id = ++nextClick;
          waiting.set(id, resolve);
          globalThis.__accessibleInstagramClicks.push({id, x: message.x, y: message.y});
        }) : Promise.resolve({ok: true}),
      onMessage: {addListener: listener => {
        globalThis.__accessibleInstagramCommand = (action, argument) => new Promise(resolve => {
          listener({type: "accessible-reels-command", platform: "instagram", action, argument}, {}, resolve);
        });
      }}
    }
  };
})();
