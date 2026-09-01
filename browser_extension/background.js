const BRIDGE_URL = "http://127.0.0.1:43119";
const BRIDGE_TOKEN = "ar-local-tiktok-bridge-v1-8f24c6d1";
let polling = false;

async function trustedClick(tabId, x, y) {
  const target = {tabId};
  await chrome.debugger.attach(target, "1.3");
  try {
    await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
      type: "mouseMoved", x, y
    });
    await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
      type: "mousePressed", x, y, button: "left", clickCount: 1
    });
    await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
      type: "mouseReleased", x, y, button: "left", clickCount: 1
    });
  } finally {
    await chrome.debugger.detach(target).catch(() => {});
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "accessible-reels-wake") {
    // Manter o canal aberto impede o Manifest V3 de encerrar o service worker
    // enquanto a consulta local ainda está aguardando um comando.
    pollOnce()
      .then(() => sendResponse({ok: true}))
      .catch(() => sendResponse({ok: false}));
    return true;
  }
  if (!message || message.type !== "accessible-reels-trusted-click") return false;
  if (!sender.tab || !Number.isFinite(message.x) || !Number.isFinite(message.y)) {
    sendResponse({ok: false, error: "Destino de clique inválido."});
    return false;
  }
  trustedClick(sender.tab.id, message.x, message.y)
    .then(() => sendResponse({ok: true}))
    .catch(error => sendResponse({
      ok: false,
      error: "Não foi possível enviar o clique real ao TikTok. " +
        (error && error.message ? error.message : String(error))
    }));
  return true;
});

async function bridgeFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Accessible-Reels-Bridge", BRIDGE_TOKEN);
  // Chromium 152 omits Origin on extension service-worker requests. Send the
  // extension identity explicitly so the local bridge can authenticate it.
  headers.set("X-Accessible-Reels-Extension", chrome.runtime.id);
  return fetch(`${BRIDGE_URL}${path}`, {...options, headers, cache: "no-store"});
}

async function findTikTokTab() {
  const stored = await chrome.storage.local.get("accessibleReelsTabId");
  if (Number.isInteger(stored.accessibleReelsTabId)) {
    try {
      const dedicated = await chrome.tabs.get(stored.accessibleReelsTabId);
      if (dedicated.url && /^https:\/\/([^/]+\.)?tiktok\.com\//i.test(dedicated.url)) {
        return dedicated;
      }
    } catch (_error) {
      await chrome.storage.local.remove("accessibleReelsTabId");
    }
  }
  const tabs = await chrome.tabs.query({url: ["https://*.tiktok.com/*"]});
  if (!tabs.length) throw new Error("Abra uma aba do TikTok no Chrome ou Brave.");
  tabs.sort((a, b) => Number(b.active) - Number(a.active) ||
    (b.lastAccessed || 0) - (a.lastAccessed || 0));
  await chrome.storage.local.set({accessibleReelsTabId: tabs[0].id});
  return tabs[0];
}

async function closeTikTokTab() {
  const tab = await findTikTokTab();
  await chrome.tabs.remove(tab.id);
  await chrome.storage.local.remove([
    "accessibleReelsTabId", "accessibleReelsWindowId"
  ]);
  return {ok: true};
}

async function openMinimizedTikTok() {
  const stored = await chrome.storage.local.get(["accessibleReelsTabId", "accessibleReelsWindowId"]);
  if (Number.isInteger(stored.accessibleReelsTabId)) {
    try {
      const tab = await chrome.tabs.get(stored.accessibleReelsTabId);
      if (!tab.url || !/^https:\/\/([^/]+\.)?tiktok\.com\//i.test(tab.url)) {
        await chrome.tabs.update(tab.id, {url: "https://www.tiktok.com/"});
      }
      await chrome.windows.update(tab.windowId, {state: "minimized"});
      return {ok: true, tabId: tab.id};
    } catch (_error) {
      await chrome.storage.local.remove(["accessibleReelsTabId", "accessibleReelsWindowId"]);
    }
  }
  const created = await chrome.windows.create({
    url: "https://www.tiktok.com/",
    focused: false,
    state: "minimized",
    type: "normal"
  });
  const tab = created.tabs && created.tabs[0];
  if (!tab) throw new Error("O Brave não criou a aba minimizada do TikTok.");
  await chrome.storage.local.set({
    accessibleReelsTabId: tab.id,
    accessibleReelsWindowId: created.id
  });
  return {ok: true, tabId: tab.id};
}

chrome.action.onClicked.addListener(async tab => {
  try {
    if (tab && tab.id && tab.url && /^https:\/\/([^/]+\.)?tiktok\.com\//i.test(tab.url)) {
      await chrome.storage.local.set({accessibleReelsTabId: tab.id});
    } else {
      const existing = await chrome.tabs.query({url: ["https://*.tiktok.com/*"]});
      if (existing.length) {
        await chrome.tabs.update(existing[0].id, {active: true});
        await chrome.windows.update(existing[0].windowId, {focused: true});
      } else {
        await chrome.tabs.create({url: "https://www.tiktok.com/", active: true});
      }
    }
    await chrome.action.setTitle({
      title: "Accessible Reels: TikTok ativado; conecte pela interface"
    });
    pollOnce();
  } catch (error) {
    await chrome.action.setTitle({
      title: "Accessible Reels: não foi possível abrir o TikTok"
    }).catch(() => {});
  }
});

async function runCommand(command) {
  if (command.action === "open_minimized") return openMinimizedTikTok();
  if (command.action === "close_tiktok") return closeTikTokTab();
  const tab = await findTikTokTab();
  try {
    const result = await chrome.tabs.sendMessage(tab.id, {
      type: "accessible-reels-command",
      action: command.action,
      argument: command.argument
    });
    if (!result || typeof result !== "object") {
      throw new Error("A aba do TikTok não devolveu uma resposta válida.");
    }
    return result;
  } catch (error) {
    throw new Error(
      "Recarregue a aba do TikTok para ativar a extensão. " +
      (error && error.message ? error.message : String(error))
    );
  }
}

async function pollOnce() {
  if (polling) return;
  polling = true;
  try {
    const response = await bridgeFetch("/v1/command");
    await chrome.action.setBadgeBackgroundColor({color: "#137333"});
    await chrome.action.setBadgeText({text: "ON"});
    await chrome.action.setTitle({title: "Accessible Reels: interface conectada"});
    if (response.status === 204) return;
    if (!response.ok) return;
    const command = await response.json();
    let result;
    try {
      result = await runCommand(command);
    } catch (error) {
      result = {ok: false, error: error && error.message ? error.message : String(error)};
    }
    await bridgeFetch("/v1/result", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: command.id, ...result})
    });
  } catch (_error) {
    // A interface está fechada ou ainda não ativou o modo de navegador local.
    await chrome.action.setBadgeText({text: ""}).catch(() => {});
    await chrome.action.setTitle({title: "Accessible Reels: aguardando interface"}).catch(() => {});
  } finally {
    polling = false;
  }
}

setInterval(pollOnce, 350);
pollOnce();
