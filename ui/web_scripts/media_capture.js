// Retain only video metadata from TikTok feed responses, never account data.
(() => {
  if (window.__accessibleMediaItems) return;
  const items = new Map();
  window.__accessibleMediaItems = items;
  const remember = root => {
    const queue = [root];
    let budget = 20000;
    while (queue.length && budget-- > 0) {
      const value = queue.pop();
      if (!value || typeof value !== 'object') continue;
      const id = String(value.id || value.itemId || value.aweme_id || '');
      if (/^\d+$/.test(id) && value.video) {
        items.set(id, {id, video: value.video});
        while (items.size > 100) items.delete(items.keys().next().value);
      } else queue.push(...Object.values(value));
    }
  };
  const relevant = value => {
    try {
      const url = new URL(value, location.href);
      return ['www.tiktok.com', 'tiktok.com'].includes(url.hostname) && url.pathname.startsWith('/api/');
    } catch (_) { return false; }
  };
  const originalFetch = window.fetch;
  window.fetch = async function(...args) {
    const response = await originalFetch.apply(this, args);
    if (relevant(response.url || args[0]?.url || args[0])) {
      response.clone().json().then(remember).catch(() => {});
    }
    return response;
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    if (relevant(url)) this.addEventListener('load', () => {
      try { remember(this.responseType === 'json' ? this.response : JSON.parse(this.responseText)); } catch (_) {}
    }, {once: true});
    return open.call(this, method, url, ...args);
  };
})();
