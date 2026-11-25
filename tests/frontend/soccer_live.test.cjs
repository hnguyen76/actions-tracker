const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const file = path.join(__dirname, '../../src/actions_tracker/templates/static/soccer-live.js');
const context = { globalThis: {} };
vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
const api = context.globalThis.ActionsSoccerLive;
const plain = (v) => JSON.parse(JSON.stringify(v));
// real DraftKings props through ESPN, VIL @ SLP (Champions League 25/11): home SLP = 494, away VIL = 102
const PROPS = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/espn_soccer_props_pregame.json'), 'utf8'));

test('half markets: the 3-way half moneylines by team and the main 1H total (prices closest to even)', () => {
  const m = plain(api.halfMarkets(PROPS, '494', '102'));
  assert.deepEqual(m.first_ml, { home: 215, away: 180, draw: 130 });
  assert.deepEqual(m.second_ml, { home: 190, away: 160, draw: 155 });
  assert.deepEqual(m.first_total, { line: 1.5, over: 127, under: -166 });
});

test('half totals list the over first: a pair that breaks the falling over chance is not trusted', () => {
  const total = (line, a, b) => [{ type: { name: '1st Half Total' }, current: { over: { american: a }, target: { value: line } } },
    { type: { name: '1st Half Total' }, current: { over: { american: b }, target: { value: line } } }];
  const ok = { items: [...total(0.5, '-359', '+254'), ...total(1.5, '+127', '-166'), ...total(2.5, '+400', '-640')] };
  assert.deepEqual(plain(api.halfMarkets(ok, '1', '2').first_total), { line: 1.5, over: 127, under: -166 });
  const swapped = { items: [...total(0.5, '+254', '-359'), ...total(1.5, '+127', '-166'), ...total(2.5, '-640', '+400')] };
  assert.equal(api.halfMarkets(swapped, '1', '2').first_total, null);
});

test('2H like NFL: the 1H favourite (-0,5) that does not lead is backed in the 2H; else the other team', () => {
  const markets = { first_ml: { home: 215, away: 180, draw: 130 }, second_ml: { home: 190, away: 160, draw: 155 },
    first_total: { line: 1.5, over: 127, under: -166 }, second_total: { line: 1.5, over: -110, under: -120 } };
  const level = plain(api.decide2H({ home: 0, away: 0 }, markets));
  assert.deepEqual(level.side, { team: 'away', price: 160, favourite: 'away', covered: false });
  assert.deepEqual(level.total, { side: 'over', line: 1.5, price: -110, first_goals: 0, first_line: 1.5 });
  const favLeads = plain(api.decide2H({ home: 0, away: 2 }, markets));
  assert.deepEqual(favLeads.side, { team: 'home', price: 190, favourite: 'away', covered: true });
  assert.deepEqual(favLeads.total, { side: 'under', line: 1.5, price: -120, first_goals: 2, first_line: 1.5 });
});

test('2H without a 2H line or a clear 1H favourite gives no play on that market', () => {
  const noSecond = plain(api.decide2H({ home: 1, away: 0 }, { first_ml: { home: 150, away: 150, draw: 200 },
    first_total: { line: 1.5, over: 120, under: -150 } }));
  assert.equal(noSecond.side, null);                                          // no favourite
  assert.deepEqual(noSecond.total, { side: 'over', line: null, price: null, first_goals: 1, first_line: 1.5 });
  const wholeLine = plain(api.decide2H({ home: 1, away: 0 }, { first_total: { line: 1, over: 100, under: -120 } }));
  assert.equal(wholeLine.total, null);                                        // exactly on a whole line: push
});

test('a live event reads the score, the clock with stoppage time, halftime, and the pregame DraftKings line', () => {
  const raw = { id: '401915293', date: '2026-11-25T17:45Z', competitions: [{
    status: { displayClock: "45'+2'", period: 1, type: { state: 'in', name: 'STATUS_FIRST_HALF', shortDetail: "45'+2'" } },
    competitors: [
      { homeAway: 'home', score: '1', team: { id: '494', abbreviation: 'SLP', displayName: 'Slavia Prague' } },
      { homeAway: 'away', score: '0', team: { id: '102', abbreviation: 'VIL', displayName: 'Villarreal' } }],
    odds: [{ provider: { name: 'DraftKings' },
      moneyline: { home: { close: { odds: '+215' } }, away: { close: { odds: '+120' } }, draw: { close: { odds: '+210' } } },
      total: { over: { close: { line: 'o2.5', odds: '-105' } }, under: { close: { line: 'u2.5', odds: '-115' } } } }] }] };
  const e = plain(api.parseEvent(raw, 'uefa.champions'));
  assert.deepEqual([e.event_id, e.state, e.clock, e.period, e.halftime], ['401915293', 'live', "45'+2'", 1, false]);
  assert.deepEqual([e.home.abbr, e.away.abbr, e.home_score, e.away_score], ['SLP', 'VIL', 1, 0]);
  assert.deepEqual(e.pregame, { ml: { home: 215, away: 120, draw: 210 }, total: { line: 2.5, over: -105, under: -115 } });
  const ht = plain(api.parseEvent({ ...raw, competitions: [{ ...raw.competitions[0],
    status: { displayClock: "45'+4'", period: 1, type: { state: 'in', name: 'STATUS_HALFTIME', shortDetail: 'HT' } } }] },
  'uefa.champions'));
  assert.deepEqual([ht.state, ht.halftime, ht.detail], ['live', true, 'HT']);
});
