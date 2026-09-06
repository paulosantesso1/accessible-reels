const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function background(initial = {}) {
  const storage = {...initial};
  const sent = [], removed = [], requests = [];
  const tabs = new Map([
    [1, {id:1, windowId:10, url:'https://www.tiktok.com/@ana/video/123',active:true}],
    [2, {id:2, windowId:20, url:'https://www.instagram.com/reels/ABC/',active:true}],
    [3, {id:3, windowId:20, url:'https://www.instagram.com/reels/XYZ/',active:false}],
  ]);
  const noop = async () => {};
  let listener;
  const chrome = {
    runtime: {id:'a'.repeat(32),getManifest:()=>({version:'1.3.0'}),onMessage:{addListener:fn=>listener=fn}},
    storage: {local: {
      get:async()=>({...storage}), set:async value=>Object.assign(storage,value),
      remove:async keys=>{for(const key of Array.isArray(keys)?keys:[keys]) delete storage[key];}
    }},
    tabs: {
      get:async id=>{if(!tabs.has(id))throw new Error('closed');return tabs.get(id);},
      query:async filter=>[...tabs.values()].filter(tab=>filter.url.some(pattern=>pattern.includes('instagram')===tab.url.includes('instagram'))),
      remove:async id=>{removed.push(id);tabs.delete(id);},
      sendMessage:async (id,message)=>{sent.push({id,...message});return {ok:true};},
      onUpdated:{addListener:()=>{},removeListener:()=>{}},
    },
    windows: {update:noop},
    action:{onClicked:{addListener:()=>{}},setBadgeText:noop,setBadgeBackgroundColor:noop,setTitle:noop},
    debugger:{attach:noop,detach:noop,sendCommand:noop}
  };
  const context = vm.createContext({chrome,URL,Headers,AbortSignal,setTimeout,clearTimeout,setInterval:()=>{},
    fetch:async url=>{requests.push(url);return {ok:true,status:204};}
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../browser_extension/background.js'),'utf8'),context);
  return {context,storage,sent,removed,tabs,requests,listener};
}

test('Instagram and TikTok commands go to their own pinned tabs',async()=>{
  const b=background({accessibleReelsTabId:1,accessibleReelsInstagramTabId:2});
  await b.context.runCommand({platform:'instagram',action:'toggle_like'});
  await b.context.runCommand({platform:'tiktok',action:'toggle_favorite'});
  assert.equal(b.sent[0].id,2);
  assert.equal(b.sent[0].platform,'instagram');
  assert.equal(b.sent[1].id,1);
});

test('wrong-platform cached tab is rejected and replaced with an Instagram tab',async()=>{
  const b=background({accessibleReelsInstagramTabId:1});
  await b.context.runCommand({platform:'instagram',action:'next'});
  assert.equal(b.sent[0].id,2);
  assert.equal(b.storage.accessibleReelsInstagramTabId,2);
});

test('closing Instagram never closes TikTok or another Instagram tab',async()=>{
  const b=background({accessibleReelsInstagramTabId:2,accessibleReelsTabId:1});
  await b.context.runCommand({platform:'instagram',action:'close_instagram'});
  assert.deepEqual(b.removed,[2]);
  assert.ok(b.tabs.has(1));
  assert.ok(b.tabs.has(3));
});

test('closing a vanished pinned tab does not fall back to another tab',async()=>{
  const b=background({accessibleReelsInstagramTabId:99,accessibleReelsTabId:99});
  await b.context.runCommand({platform:'instagram',action:'close_instagram'});
  await b.context.runCommand({platform:'tiktok',action:'close_tiktok'});
  assert.deepEqual(b.removed,[]);
});

test('Instagram result URL rejects cross-site navigation and strips tracking',()=>{
  const b=background();
  assert.equal(b.context.instagramResultUrl('https://instagram.com/reels/ABC/?tracking=1'), 'https://www.instagram.com/reel/ABC/');
  for(const url of ['https://tiktok.com/reel/ABC/','https://instagram.com.evil.test/reel/ABC/','https://instagram.com/reels/audio/123/']) {
    assert.throws(()=>b.context.instagramResultUrl(url));
  }
});

test('both bridges are polled independently',async()=>{
  const b=background();
  await b.context.pollOnce();
  assert.ok(b.requests.includes('http://127.0.0.1:43119/v1/command'));
  assert.ok(b.requests.includes('http://127.0.0.1:43120/v1/command'));
});

test('unsupported platform cannot execute a TikTok command',async()=>{
  const b=background();
  await assert.rejects(b.context.runCommand({platform:'other',action:'toggle_like'}));
  assert.equal(b.sent.length,0);
});

test('Instagram social action is never retried after a lost response',async()=>{
  const b=background({accessibleReelsInstagramTabId:2});
  let count=0;
  b.context.chrome.tabs.sendMessage=async()=>{count++;throw new Error('channel closed');};
  await assert.rejects(b.context.runCommand({platform:'instagram',action:'toggle_like'}));
  assert.equal(count,1);
});
