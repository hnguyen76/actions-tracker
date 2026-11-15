const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../src/actions_tracker/templates/static/scoreboard.js'), 'utf8');
const BASE = Date.parse('2026-11-15T16:10:00Z');

function harness() {
  let now = BASE, nextTimer = 0;
  const timers = new Map(), listeners = new Map();
  class Element {
    constructor(tag) { this.tagName = tag; this.className = ''; this.dataset = {}; this.attributes = {}; this.children = []; this.parentNode = null; this.hidden = false; this.ownText = ''; }
    set textContent(v) { this.ownText = String(v); this.children = []; }
    get textContent() { return this.ownText + this.children.map(x => x.textContent).join(''); }
    get classList() { return { add: (...names) => { this.className = [...new Set(this.className.split(/\s+/).filter(Boolean).concat(names))].join(' '); } }; }
    setAttribute(k, v) { this.attributes[k] = String(v); }
    append(...items) { for (const item of items) { item.parentNode = this; this.children.push(item); } }
    replaceChildren(...items) { for (const old of this.children) old.parentNode = null; this.children = []; this.ownText = ''; this.append(...items); }
    get isConnected() { return this === doc.root || !!this.parentNode?.isConnected; }
    getClientRects() { for (let p = this; p; p = p.parentNode) if (p.hidden) return []; return this.isConnected ? [{}] : []; }
  }
  const walk = (node) => [node, ...node.children.flatMap(walk)];
  const doc = {
    hidden: false,
    createElement: tag => new Element(tag),
    addEventListener: (event, fn) => { const a = listeners.get(event) || []; a.push(fn); listeners.set(event, a); },
    querySelectorAll: () => walk(doc.root).filter(n => n.className.split(/\s+/).includes('asb-halftime') && n.dataset.halftimeEndsAt),
  };
  doc.root = new Element('root');
  const host = new Element('div'); doc.root.append(host);
  class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
  const context = vm.createContext({ document: doc, Date: ClockDate, setInterval: (fn, ms) => { assert.equal(ms, 1000); timers.set(++nextTimer, fn); return nextTimer; }, clearInterval: id => timers.delete(id) });
  context.window = context;
  vm.runInContext(source, context);
  return {
    api: context.ActionsScoreboard, doc, host, timers,
    nodes: cls => walk(doc.root).filter(n => n.className.split(/\s+/).includes(cls)),
    advance: ms => { now += ms; for (const fn of [...timers.values()]) fn(); },
    hide: hidden => { doc.hidden = hidden; for (const fn of listeners.get('visibilitychange') || []) fn(); },
  };
}
const game = (extra = {}) => ({ game_id: 1, league: 'nfl', state: 'live', detail: 'Halftime', away_abbr: 'NE', home_abbr: 'DET', away_score: 3, home_score: 21,
  situation: { is_halftime: true, period: 2, clock: '0:00', halftime_ends_at: new Date(BASE + 532000).toISOString(), possession: 'home', possession_text: 'NE 8', down_distance: '2nd & 2' }, ...extra });

test('estimate is visibly labeled and derives remaining time from the absolute deadline', () => {
  const h = harness(); h.api.render(h.host, [game()]);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · ước tính 08:52');
  assert.equal(h.nodes('asb-clock')[0].attributes['aria-live'], 'off');
  assert.equal(h.nodes('asb-possession').length, 0);
  assert.equal(h.nodes('asb-situation').length, 0);
  h.advance(5500);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · ước tính 08:47');
  assert.equal(h.timers.size, 1);
});
test('expired estimate waits for official third-quarter status and stops its ticker', () => {
  const h = harness(); h.api.render(h.host, [game()]); h.advance(532000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · chờ hiệp 3');
  assert.equal(h.timers.size, 0);
  h.advance(60000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · chờ hiệp 3');
});
test('hidden pages pause and resume immediately from wall-clock time', () => {
  const h = harness(); h.api.render(h.host, [game()]); h.hide(true);
  assert.equal(h.timers.size, 0); h.advance(30000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · ước tính 08:52');
  h.hide(false);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · ước tính 08:22');
  assert.equal(h.timers.size, 1);
});
test('rerenders share one ticker and removing cards clears the ticker', () => {
  const h = harness(); h.api.render(h.host, [game()]); const old = h.nodes('asb-clock')[0];
  for (let i = 0; i < 4; i++) h.api.render(h.host, [game()]);
  assert.equal(h.timers.size, 1); assert.equal(old.isConnected, true);
  h.api.render(h.host, []); assert.equal(h.timers.size, 0);
});
test('live updates reuse the card and preserve its pregame subtree', () => {
  const h = harness(); h.api.render(h.host, [game({ detail: '5:47 - 2nd', situation: { period: 2, clock: '5:47' } })]);
  const card = h.nodes('asb-card')[0], pregame = h.doc.createElement('section');
  pregame.className = 'live-card-pregame'; pregame.textContent = 'pregame'; card.append(pregame);
  h.api.render(h.host, [game({ detail: '5:12 - 2nd', away_score: 10, situation: { period: 2, clock: '5:12' } })]);
  assert.equal(h.nodes('asb-card')[0], card);
  assert.equal(h.nodes('live-card-pregame')[0], pregame);
  assert.equal(pregame.isConnected, true);
  assert.equal(h.nodes('asb-score')[0].textContent, '10');
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:12 · Hiệp 2');
});
test('ordinary game clock, final and third-quarter status never become a countdown', () => {
  const h = harness();
  h.api.render(h.host, [game({ detail: '5:47 - 2nd', situation: { period: 2, clock: '5:47', halftime_ends_at: new Date(BASE + 10000).toISOString() } })]);
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:47 · Hiệp 2'); h.advance(5000);
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:47 · Hiệp 2'); assert.equal(h.timers.size, 0);
  h.api.render(h.host, [game({ situation: { ...game().situation, period: 3, clock: '15:00' } })]);
  assert.equal(h.nodes('asb-clock')[0].textContent, '15:00 · Hiệp 3'); assert.equal(h.timers.size, 0);
  h.api.render(h.host, [game({ state: 'final' })]);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Hết trận · chờ chấm'); assert.equal(h.timers.size, 0);
});
test('invalid or missing estimates retain the official halftime label without a ticker', () => {
  const h = harness();
  for (const end of [null, '', 'invalid']) {
    h.api.render(h.host, [game({ situation: { ...game().situation, halftime_ends_at: end } })]);
    assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime'); assert.equal(h.timers.size, 0);
  }
});
test('only visible countdown nodes run a ticker', () => {
  const h = harness(); h.doc.root.hidden = true; h.api.render(h.host, [game()]);
  assert.equal(h.timers.size, 0);
  h.doc.root.hidden = false; h.hide(false); assert.equal(h.timers.size, 1);
});
test('official halftime status alone is retained while an empty status remains null', () => {
  const h = harness();
  assert.equal(h.api.parseSituation({ competitions: [{}] }), null);
  const s = h.api.parseSituation({ status: { type: { name: 'STATUS_HALFTIME' } }, competitions: [{}] });
  assert.equal(s.is_halftime, true);
});
test('live football renders an accessible drive field and hides it when drive data is absent', () => {
  const h = harness();
  h.api.render(h.host, [game({
    detail: '2:12 - 4th',
    situation: { period: 4, clock: '2:12', possession: 'home', possession_text: 'DET 32', down_distance: '3rd & 6' },
    drive: { team_side: 'home', team_abbr: 'DET', team_logo: 'https://a.espncdn.com/i/teamlogos/nfl/500/det.png',
      description: '3 plays, 11 yards, 1:28', down_distance: '3rd & 6', spot: 'DET 32', ball_x: 68,
      first_down_x: 62, distance: 6, play_yards: -5, play_clock: '2:12', play_type: 'Penalty', last_play: 'Illegal Formation.' },
  })]);
  assert.equal(h.nodes('asb-drive').length, 1);
  assert.equal(h.nodes('asb-field')[0].attributes['aria-label'], 'DET cầm bóng, 3rd & 6, bóng tại DET 32');
  assert.equal(h.nodes('asb-ball-marker')[0].attributes.style, 'left:65.12%');
  assert.equal(h.nodes('asb-first-down')[0].attributes.style, 'left:60.08%');
  assert.match(h.nodes('asb-last-play')[0].textContent, /Illegal Formation/);
  h.api.render(h.host, [game({ detail: '2:05 - 4th', situation: { period: 4, clock: '2:05' }, drive: null })]);
  assert.equal(h.nodes('asb-drive').length, 0);
});
