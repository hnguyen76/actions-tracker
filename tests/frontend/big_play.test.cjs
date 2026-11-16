const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../src/actions_tracker/templates/static/big-play.js'), 'utf8');

function load(extra = {}) {
  const ctx = { document: { addEventListener() {} }, setTimeout, clearTimeout, ...extra };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.ActionsBigPlay;
}
const card = (extra = {}) => ({ game_id: 1, state: 'live', away_score: 14, home_score: 14, drive: { big_plays: [] }, ...extra });
const pick = { id: '9001', kind: 'interception', side: 'home', text: 'Pass intercepted.' };
const plain = (events) => JSON.parse(JSON.stringify(events));

test('detect: first look only records, then score jumps and new big plays become events', () => {
  const { detect } = load(), m = new Map();
  let t = 1e6;
  assert.deepEqual(plain(detect(m, [card({ drive: { big_plays: [pick] } })], t)), []);
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, drive: { big_plays: [pick] } })], t += 5000)),
    [{ game_id: 1, kind: 'touchdown', side: 'home' }]);
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, away_score: 17 })], t += 5000)),
    [{ game_id: 1, kind: 'field_goal', side: 'away' }]);
  assert.deepEqual(plain(detect(m, [card({ home_score: 22, away_score: 17 })], t += 5000)), []);  // extra point
  assert.deepEqual(plain(detect(m, [card({ home_score: 24, away_score: 17 })], t += 5000)), []);  // two-point try
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, away_score: 17 })], t += 5000)), []);  // ESPN correction
  const lost = { id: '9102', kind: 'fumble_lost', side: 'away', text: null };
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, away_score: 17, drive: { big_plays: [pick, lost] } })], t += 5000)),
    [{ game_id: 1, kind: 'fumble_lost', side: 'away' }]);
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, away_score: 17, drive: null })], t += 5000)), []);
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, away_score: 17, drive: { big_plays: [lost] } })], t += 5000)), []);
});

test('detect: a look older than 60 s re-baselines quietly; a walk-off field goal still counts at final', () => {
  const { detect } = load(), m = new Map();
  const t = 1e6;
  detect(m, [card()], t);
  assert.deepEqual(plain(detect(m, [card({ home_score: 21, drive: { big_plays: [pick] } })], t + 61000)), []);
  assert.deepEqual(plain(detect(m, [card({ home_score: 24, state: 'final', drive: { big_plays: [pick] } })], t + 66000)),
    [{ game_id: 1, kind: 'field_goal', side: 'home' }]);
});

function fakeDom() {
  const all = [];
  class El {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.className = ''; this.children = []; this.parentNode = null; this.attributes = {};
      this.listeners = {}; this.style = {}; this.ownText = ''; all.push(this); }
    get classList() { return { add: (...n) => { this.className = [...new Set(this.className.split(' ').filter(Boolean).concat(n))].join(' '); },
      contains: (n) => this.className.split(' ').includes(n) }; }
    set textContent(v) { this.ownText = String(v); this.children = []; }
    get textContent() { return this.ownText + this.children.map((c) => c.textContent).join(''); }
    append(...items) { for (const i of items) { i.parentNode = this; this.children.push(i); } }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); this.parentNode = null; }
    setAttribute(k, v) { this.attributes[k] = String(v); }
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
    getContext() { return null; }
  }
  const body = new El('body');
  const connected = (n) => { for (let p = n; p; p = p.parentNode) if (p === body) return true; return false; };
  return {
    document: { body, head: body, createElement: (t) => new El(t), addEventListener() {} },
    find: (cls) => all.filter((n) => connected(n) && n.className.split(' ').includes(cls)),
    click: (n) => (n.listeners.click || []).forEach((fn) => fn({})),
  };
}
function page(bet = { state: 'win', pick: 'CIN -4,5' }) {
  const env = fakeDom(), vib = [];
  const api = load({ document: env.document, navigator: { vibrate: (p) => vib.push(p) }, matchMedia: () => ({ matches: false }),
    requestAnimationFrame: () => 0, setTimeout: () => 0, clearTimeout() {}, ActionsScoreboard: { betStatus: () => bet } });
  return { env, vib, api };
}
const live = (extra = {}) => card({ away_abbr: 'PIT', home_abbr: 'CIN', bet_side: 'home', market: 'spread', line: -4.5, ...extra });

test('observe: a new touchdown for the bet side shows one overlay with the score and the bet line', () => {
  const { env, vib, api } = page();
  api.observe([live()]);
  assert.equal(env.find('bp-overlay').length, 0);
  api.observe([live({ home_score: 21 })]);
  const shown = env.find('bp-overlay');
  assert.equal(shown.length, 1);
  assert.match(shown[0].textContent, /TOUCHDOWN/);
  assert.match(shown[0].textContent, /PIT 14 – 21 CIN/);
  assert.match(shown[0].textContent, /Bạn đặt CIN -4,5 · đang thắng/);
  assert.ok(shown[0].classList.contains('bp-good'));
  assert.equal(vib.length, 1);
});

test('observe: alerts queue one at a time; a turnover against the bet side is shown in the bad tone', () => {
  const { env, api } = page({ state: 'loss', pick: 'CIN -4,5' });
  api.observe([live()]);
  api.observe([live({ home_score: 17, drive: { big_plays: [{ id: '7', kind: 'interception', side: 'away', text: null }] } })]);
  let shown = env.find('bp-overlay');
  assert.equal(shown.length, 1);
  assert.match(shown[0].textContent, /FIELD GOAL/);
  env.click(shown[0]);
  shown = env.find('bp-overlay');
  assert.equal(shown.length, 1);
  assert.match(shown[0].textContent, /INTERCEPTION/);
  assert.match(shown[0].textContent, /PIT cướp bóng/);
  assert.ok(shown[0].classList.contains('bp-bad'));
  env.click(shown[0]);
  assert.equal(env.find('bp-overlay').length, 0);
});
