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
