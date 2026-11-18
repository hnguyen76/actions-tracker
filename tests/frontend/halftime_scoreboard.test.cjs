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
    createElementNS: (ns, tag) => new Element(tag),
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

test('halftime countdown derives remaining time from the absolute deadline', () => {
  const h = harness(); h.api.render(h.host, [game()]);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · 08:52');
  assert.equal(h.nodes('asb-clock')[0].attributes['aria-live'], 'off');
  assert.equal(h.nodes('asb-possession').length, 0);
  assert.equal(h.nodes('asb-situation').length, 0);
  h.advance(5500);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · 08:47');
  assert.equal(h.timers.size, 1);
});
test('expired estimate waits for official third-quarter status and stops its ticker', () => {
  const h = harness(); h.api.render(h.host, [game()]); h.advance(532000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · chờ 3rd');
  assert.equal(h.timers.size, 0);
  h.advance(60000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · chờ 3rd');
});
test('hidden pages pause and resume immediately from wall-clock time', () => {
  const h = harness(); h.api.render(h.host, [game()]); h.hide(true);
  assert.equal(h.timers.size, 0); h.advance(30000);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · 08:52');
  h.hide(false);
  assert.equal(h.nodes('asb-clock')[0].textContent, 'Halftime · 08:22');
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
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:12 · 2nd');
});
test('ordinary game clock, final and third-quarter status never become a countdown', () => {
  const h = harness();
  h.api.render(h.host, [game({ detail: '5:47 - 2nd', situation: { period: 2, clock: '5:47', halftime_ends_at: new Date(BASE + 10000).toISOString() } })]);
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:47 · 2nd'); h.advance(5000);
  assert.equal(h.nodes('asb-clock')[0].textContent, '5:47 · 2nd'); assert.equal(h.timers.size, 0);
  h.api.render(h.host, [game({ situation: { ...game().situation, period: 3, clock: '15:00' } })]);
  assert.equal(h.nodes('asb-clock')[0].textContent, '15:00 · 3rd'); assert.equal(h.timers.size, 0);
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
      description: '3 plays, 11 yards, 1:28', down_distance: '3rd & 6', spot: 'DET 32', ball_x: 68, start_x: 79,
      first_down_x: 62, distance: 6, play_yards: -5, play_clock: '2:12', play_type: 'Penalty', last_play: 'Illegal Formation.' },
  })]);
  assert.equal(h.nodes('asb-drive').length, 1);
  // header: only the logo of the team with the ball, no "ĐỢT TẤN CÔNG HIỆN TẠI" text
  assert.equal(h.nodes('asb-drive-team')[0].textContent, '');
  assert.equal(h.nodes('asb-drive-logo')[0].attributes.alt, 'DET cầm banh');
  assert.equal(h.nodes('asb-field')[0].attributes['aria-label'], 'DET cầm banh, 3rd & 6, banh tại DET 32');
  // perspective field: 120 yards incl. end zones, the top edge 92.5% of the bottom; marker and drive bar at mid height
  assert.equal(h.nodes('asb-ball-marker')[0].attributes.style, 'left:64.44%');
  const first = h.nodes('asb-first-down')[0].attributes;
  assert.deepEqual([first.x1, first.x2], ['711', '720']);
  assert.equal(h.nodes('asb-drive-progress')[0].attributes.style, 'left:64.44%;width:8.82%');
  assert.equal(h.nodes('asb-yard-number').length, 9);
  assert.equal(h.nodes('asb-yard-number')[0].attributes.style, 'left:16.67%');
  assert.equal(h.nodes('asb-yardline').length, 9);
  assert.equal(h.nodes('asb-drive-facts')[0].textContent, '3rd & 6 · DET 32');
  assert.match(h.nodes('asb-last-play')[0].textContent, /Illegal Formation/);
  h.api.render(h.host, [game({ detail: '2:05 - 4th', situation: { period: 4, clock: '2:05' }, drive: null })]);
  assert.equal(h.nodes('asb-drive').length, 0);
});
test('drive bar is left out when the start of the drive is unknown', () => {
  const h = harness();
  h.api.render(h.host, [game({ detail: '2:12 - 4th', situation: { period: 4, clock: '2:12' },
    drive: { team_side: 'away', team_abbr: 'NE', down_distance: '1st & 10', spot: 'NE 39', ball_x: 39, first_down_x: 49, distance: 10 } })]);
  assert.equal(h.nodes('asb-ball-marker')[0].attributes.style, 'left:41.18%');
  assert.equal(h.nodes('asb-drive-progress').length, 0);
  assert.equal(h.nodes('asb-drive-team')[0].textContent, 'NE');  // no logo: the abbreviation stands in
});
test('quarter labels read 1st 2nd 3rd 4th and overtime stays OT', () => {
  const h = harness();
  for (const [period, label] of [[1, '1st'], [2, '2nd'], [3, '3rd'], [4, '4th'], [5, 'OT'], [6, 'OT2']]) {
    h.api.render(h.host, [game({ detail: '9:58', situation: { period, clock: '9:58' } })]);
    assert.equal(h.nodes('asb-clock')[0].textContent, '9:58 · ' + label);
  }
});

test('bet strip: pick and margin, no state pill and no ATS explanation line', () => {
  const h = harness();
  h.api.render(h.host, [game({ detail: '0:00 - 2nd', away_abbr: 'PIT', home_abbr: 'CIN', away_score: 3, home_score: 24,
    bet_side: 'home', market: 'spread', line: -4.5 })]);
  assert.equal(h.nodes('asb-bet-pick')[0].textContent, 'CIN -4.5');
  assert.equal(h.nodes('asb-bet-state').length, 0);  // no "ĐANG THẮNG" pill: the colour says it
  assert.equal(h.nodes('asb-bet-margin')[0].textContent, '16.5');
  assert.equal(h.nodes('asb-bet-ats').length, 0);
});
test('at halftime the card shows the second-half line; it is gone once the 2nd half starts', () => {
  const h = harness();
  const g = { away_abbr: 'PIT', home_abbr: 'CIN', second_half: { away: -1.5, home: 1.5, total: 23.5 } };
  h.api.render(h.host, [game(g)]);
  assert.equal(h.nodes('asb-2h')[0].textContent, '⏱ 2H · PIT -1.5 · CIN +1.5 · Total 23.5');
  h.api.render(h.host, [game({ ...g, detail: '15:00 - 3rd', situation: { period: 3, clock: '15:00' } })]);
  assert.equal(h.nodes('asb-2h').length, 0);
});

test('team names: ESPN logo and nickname replace the long name; full name until ESPN data arrives', () => {
  const h = harness();
  const logo = 'https://a.espncdn.com/i/teamlogos/nfl/500/scoreboard/pit.png';
  h.api.render(h.host, [game({ detail: '12:15 - 3rd', away_name: 'Pittsburgh Steelers', home_name: 'Cincinnati Bengals', away_abbr: 'PIT', home_abbr: 'CIN',
    situation: { period: 3, clock: '12:15', away_nick: 'Steelers', away_logo: logo, home_nick: 'Bengals', home_logo: 'http://evil.example/cin.png' } })]);
  const names = h.nodes('asb-name').map((n) => n.textContent);
  assert.deepEqual(names, ['Steelers', 'Bengals']);
  const logos = h.nodes('asb-logo');
  assert.equal(logos.length, 1);
  assert.equal(logos[0].attributes.src, logo);
  h.api.render(h.host, [game({ detail: '12:15 - 3rd', away_name: 'Pittsburgh Steelers', home_name: 'Cincinnati Bengals', situation: { period: 3, clock: '12:15' } })]);
  assert.deepEqual(h.nodes('asb-name').map((n) => n.textContent), ['Pittsburgh Steelers', 'Cincinnati Bengals']);
});
test('live ESPN odds show only the market and side of the play, using American decimals', () => {
  const h = harness(), market = {
    provider: 'DraftKings - Live Odds',
    spread: { away: { line: 6.5, odds: -112 }, home: { line: -6.5, odds: -108 } },
    total: { line: 44.5, over_odds: -110, under_odds: -112 },
  };
  const playing = { detail: '5:47 - 2nd', situation: { period: 2, clock: '5:47' }, live_odds: market };
  h.api.render(h.host, [game({ ...playing, away_abbr: 'PIT', home_abbr: 'CIN', market: 'spread', bet_side: 'home', line: -4.5 })]);
  let row = h.nodes('asb-live-odds')[0];
  assert.equal(row.textContent, '📡 ESPN · CIN -6.5 (-108)');
  assert.match(row.attributes['aria-label'], /Live odds CIN -6\.5 -108 qua ESPN/);
  h.api.render(h.host, [game({ ...playing, market: 'total', bet_side: 'under', line: 46.5 })]);
  row = h.nodes('asb-live-odds')[0];
  assert.equal(row.textContent, '📡 ESPN · Under 44.5 (-112)');
  assert.ok(!row.textContent.includes('CIN'));
  h.api.render(h.host, [game({ ...playing, market: 'ml', bet_side: 'home', line: null })]);
  assert.equal(h.nodes('asb-live-odds').length, 0);
});
test('live clock pulses in step with the TV dot; halftime and final clocks stay still', () => {
  const h = harness();
  h.api.render(h.host, [game({ detail: '1:14 - 3rd', situation: { period: 3, clock: '1:14' } })]);
  const clock = h.nodes('asb-clock')[0];
  assert.ok(clock.className.split(' ').includes('asb-live-clock'));
  assert.equal(clock.attributes.style, `animation-delay:-${BASE % 2400}ms`);  // same phase as every other pulse on the page
  assert.equal(h.api.pulseDelay(), `-${BASE % 2400}ms`);
  h.api.render(h.host, [game()]);
  assert.ok(!h.nodes('asb-clock')[0].className.split(' ').includes('asb-live-clock'));
  h.api.render(h.host, [game({ state: 'final' })]);
  assert.ok(!h.nodes('asb-clock')[0].className.split(' ').includes('asb-live-clock'));
});

test('bet strip: the pick in the state colour, the margin pulsing beside it while live; still at final', () => {
  const h = harness();
  const bet = { away_abbr: 'PIT', home_abbr: 'CIN', bet_side: 'home', market: 'spread', line: -4.5 };
  h.api.render(h.host, [game({ ...bet, detail: '13:02 - 4th', away_score: 3, home_score: 31, situation: { period: 4, clock: '13:02' } })]);
  let strip = h.nodes('asb-bet')[0];
  assert.ok(strip.className.split(' ').includes('asb-bet-win'));
  assert.equal(strip.attributes['aria-label'], 'CIN -4.5 đang thắng 23.5');
  let margin = h.nodes('asb-bet-margin')[0];
  assert.equal(margin.textContent, '23.5');
  assert.ok(margin.className.split(' ').includes('asb-bet-flash'));
  assert.equal(margin.attributes.style, `animation-delay:-${BASE % 2400}ms`);  // same rhythm as the clock and the TV dot
  h.api.render(h.host, [game({ ...bet, detail: '13:02 - 4th', away_score: 21, home_score: 17, situation: { period: 4, clock: '13:02' } })]);
  strip = h.nodes('asb-bet')[0];
  assert.ok(strip.className.split(' ').includes('asb-bet-loss'));
  assert.equal(strip.attributes['aria-label'], 'CIN -4.5 đang thua 8.5');
  h.api.render(h.host, [game({ ...bet, state: 'final', away_score: 3, home_score: 31 })]);
  margin = h.nodes('asb-bet-margin')[0];
  assert.ok(!margin.className.split(' ').includes('asb-bet-flash'));
  assert.equal(h.nodes('asb-bet')[0].attributes['aria-label'], 'CIN -4.5 thắng 23.5');
});
