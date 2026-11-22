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
  second_half: { away: 3.5, home: -3.5, total: 109.5, first_total: 101.5 },
  ...extra,
});

test('2H rule takes the trailing team and Over only after a first-half Under', () => {
  assert.deepEqual(JSON.parse(JSON.stringify(api.decide(halftime()))), {
    spread: { side: 'away', line: 3.5 }, total: { side: 'over', line: 109.5 },
    first_points: 93, first_total: 101.5, first_result: 'under', implied: false,
  });
});

test('2H total stays off after a first-half Over or push', () => {
  const over = api.decide(halftime({ away_score: 55, home_score: 51 }));
  assert.equal(over.first_result, 'over');
  assert.equal(over.total, null);
  const push = api.decide(halftime({ away_score: 50, home_score: 51.5 }));
  assert.equal(push.first_result, 'push');
  assert.equal(push.total, null);
});

test('a tied halftime score has no spread play and non-halftime games are ignored', () => {
  assert.equal(api.decide(halftime({ away_score: 50, home_score: 50 })).spread, null);
  assert.equal(api.decide(halftime({ detail: '8:00 - 3rd', situation: { period: 3 } })), null);
});

test('missing ESPN half lines never invents a pick', () => {
  const result = api.decide(halftime({ second_half: {} }));
  assert.equal(result.spread, null);
  assert.equal(result.total, null);
  assert.equal(result.first_result, 'missing');
});
