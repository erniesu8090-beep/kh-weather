const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ROOT = path.join(__dirname, '..');

function harness({offline = false, hosted = false, brokenImage = false} = {}) {
  const nodes = new Map();
  class Element {
    constructor(id = '') { this.id=id; this.textContent=''; this.value=''; this.attributes={}; this.dataset={}; this.listeners={}; this.hidden=false; this.disabled=false; this.children=[]; this.src=''; const set = new Set(); this.classList={add:x=>set.add(x),remove:x=>set.delete(x),contains:x=>set.has(x)}; }
    addEventListener(name, fn) { this.listeners[name]=fn; }
    setAttribute(name, value) { this.attributes[name]=value; }
    getAttribute(name) { return this.attributes[name]; }
    appendChild(child) { this.children.push(child); if(child.id) nodes.set(child.id,child); if(child.src && child.onload) queueMicrotask(()=>child.onerror?.()); }
    remove() { nodes.delete(this.id); }
    set innerText(value) {this.textContent=value;}
    get innerText() {return this.textContent;}
  }
  const html = fs.readFileSync(path.join(ROOT,'index.html'),'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) nodes.set(match[1],new Element(match[1]));
  const buttons = [];
  for (const match of html.matchAll(/<button class="([^"]+)"[^>]*data-(mode|hours)="([^"]+)"/g)) {
    const button = new Element(); button.dataset[match[2]]=match[3]; for(const name of match[1].split(' ')) button.classList.add(name); buttons.push(button);
  }
  const viewport = new Element();
  const legend = new Element();
  const events={}; let fetches=0, imageLoads=0;
  const observation = new Date().toISOString();
  const fixture = {rainfall: {stations: [{code:'C0V45',ten_min:'0',one_hr:'0',three_hr:'0',all_hr:'0',today:'0',observed_at:observation}]}, radar: {areas:{Area2:{scans_hd:[{url:'https://example.test/one.png',time:observation},{url:'https://example.test/two.png',time:observation}]}}}};
  const document = {
    hidden:false,visibilityState:'visible',body:new Element(),
    getElementById:id=>nodes.get(id)||null,
    createElement:()=>new Element(),
    addEventListener:(name,fn)=>events[name]=fn,
    querySelector:selector=>selector==='.radar-viewport'?viewport:legend,
    querySelectorAll:selector=> selector.includes('btn-circle-ctrl') ? ['btnFirst','btnPrev','btnPlayPause','btnNext','btnLast'].map(id=>nodes.get(id)) : buttons.filter(b=>selector.includes('radarTabs') && b.dataset.mode || selector.includes('spanGroup') && b.dataset.hours)
  };
  const context = vm.createContext({document,location:{hostname:hosted?'example.test':'localhost'}, navigator:{},localStorage:{getItem:()=>null,setItem:()=>{}},console,Date,Map,Promise,AbortController,setTimeout,clearTimeout,setInterval:()=>1,clearInterval:()=>{},queueMicrotask,fetch:async url=>{fetches++; await Promise.resolve(); if(offline) throw new Error('Offline'); if(String(url).endsWith('config.json')) return {ok:true,json:async()=>({cwaApiKey:'public-test-key'})}; if(String(url).includes('opendata')) return {ok:false,status:503}; return {ok:true,json:async()=>structuredClone(fixture)};},Image:class extends Element {set src(url){this._src=url;if(url) {imageLoads++;queueMicrotask(()=>brokenImage?this.onerror?.():this.onload?.());}} get src(){return this._src;}},addEventListener:(name,fn)=>events['window:'+name]=fn});
  context.window=context;
  for (const file of ['stations.js','weather.js','app.js']) vm.runInContext(fs.readFileSync(path.join(ROOT,file),'utf8'),context,{filename:file});
  return {context,nodes,buttons,events,viewport,legend,fixture,fetches:()=>fetches,imageLoads:()=>imageLoads,run:code=>vm.runInContext(code,context)};
}

test('refresh requests coalesce, real zero displays and missing station stays missing', async()=>{
  const h=harness();
  const first=h.run('fetchData(true)'); const second=h.run('fetchData(true)');
  assert.equal(first,second);
  await first;
  assert.equal(h.fetches(),1);
  assert.equal(h.nodes.get('card1_10m').textContent,'0.0');
  assert.equal(h.nodes.get('card1Status').textContent,'近10分鐘無雨');
  assert.equal(h.nodes.get('card2_10m').textContent,'—');
  assert.equal(h.nodes.get('card2Status').textContent,'暫無資料');
  assert.match(h.nodes.get('dataStatus').textContent,/過期|時間不明/);
  assert.equal(h.nodes.get('btnRefresh').disabled,false);
});
test('tab and range changes render cached data without another request',async()=>{
  const h=harness(); h.events.DOMContentLoaded(); await h.run('state.pending');
  const count=h.fetches();
  h.buttons.find(b=>b.dataset.mode==='satellite_taiwan').listeners.click();
  assert.equal(h.legend.hidden,true);
  assert.match(h.nodes.get('imageStatus').textContent,/暫無資料/);
  h.buttons.find(b=>b.dataset.hours==='2').listeners.click();
  assert.equal(h.fetches(),count);
  assert.equal(h.nodes.get('radarImg').hidden,true);
});
test('offline startup ends loading and never reports no rain',async()=>{
  const h=harness({offline:true}); await h.run('fetchData(true)');
  assert.equal(h.nodes.get('btnRefresh').disabled,false);
  assert.match(h.nodes.get('dataStatus').textContent,/無法取得/);
  assert.equal(h.nodes.get('card1Status').textContent,'暫無資料');
  assert.equal(h.nodes.get('radarImg').hidden,true);
});
test('image failure is visible and does not show an unloaded frame as current',async()=>{
  const h=harness({brokenImage:true}); await h.run('fetchData(true)'); await new Promise(r=>setImmediate(r));
  assert.match(h.nodes.get('imageStatus').textContent,/載入失敗/);
  assert.equal(h.nodes.get('radarImg').hidden,true);
  assert.equal(h.viewport.getAttribute('aria-busy'),'false');
});
test('hosted mode survives live API and radar failures using snapshot',async()=>{
  const h=harness({hosted:true}); await h.run('fetchData(true)');
  assert.equal(h.nodes.get('card1_10m').textContent,'0.0');
  assert.equal(h.run('state.data.backup'),true);
  assert.ok(h.run('state.radarScans.length')>0);
});
