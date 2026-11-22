const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const file = path.join(__dirname, '../../src/actions_tracker/templates/static/second-half.js');
const context = { globalThis: {} };
vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
const api = context.globalThis.ActionsSecondHalf;

const halftime = (extra = {}) => ({
  state: 'live', detail: 'Halftime', away_score: 42, home_score: 51,
  situation: { is_halftime: true, period: 2 },
  second_half: { away: 3.5, home: -3.5, total: 109.5, first_away: 5.5, first_home: -5.5, first_total: 101.5 },
  ...extra,
});

test('2H rule takes the first-half ATS loser and reverses an Under to Over', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(api.decide(halftime()))), {
    spread: { side: 'away', line: 3.5, first_line: 5.5 }, total: { side: 'over', line: 109.5 },
    first_points: 93, first_total: 101.5, first_result: 'under', first_spread_result: 'away_loss', implied: false,
  });
});

test('2H total reverses an Over to Under and stays off after a push', () => {
  const over = api.decide(halftime({ away_score: 55, home_score: 51 }));
  assert.equal(over.first_result, 'over');
  assert.deepEqual(JSON.parse(JSON.stringify(over.total)), { side: 'under', line: 109.5 });
  const push = api.decide(halftime({ away_score: 50, home_score: 51.5 }));
  assert.equal(push.first_result, 'push');
  assert.equal(push.total, null);
});

test('a first-half spread push has no spread play and non-halftime games are ignored', () => {
  const push = halftime({ away_score: 50, home_score: 50, second_half: {
    away: 2.5, home: -2.5, total: 100.5, first_away: 0, first_home: 0, first_total: 100.5 } });
  assert.equal(api.decide(push).spread, null);
  assert.equal(api.decide(push).first_spread_result, 'push');
  assert.equal(api.decide(halftime({ detail: '8:00 - 3rd', situation: { period: 3 } })), null);
});

test('raw score leader is ignored when ESPN first-half spread says that team lost ATS', () => {
  const result = api.decide(halftime({ second_half: {
    away: 3.5, home: -3.5, total: 109.5, first_away: 10.5, first_home: -10.5, first_total: 101.5 } }));
  assert.equal(result.spread.side, 'home');
  assert.equal(result.spread.first_line, -10.5);
  assert.equal(result.first_spread_result, 'home_loss');
});

test('missing ESPN half lines never invents a pick', () => {
  const result = api.decide(halftime({ second_half: {} }));
  assert.equal(result.spread, null);
  assert.equal(result.total, null);
  assert.equal(result.first_result, 'missing');
  assert.equal(result.first_spread_result, 'missing');
});
