const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const file = path.join(__dirname, '../../src/actions_tracker/templates/static/soccer.js');
const context = { globalThis: {} };
vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
const api = context.globalThis.ActionsSoccer;

test('prices and lines read like a sportsbook, with a real minus and a decimal comma', () => {
  assert.equal(api.price(-210), '−210');
  assert.equal(api.price(350), '+350');
  assert.equal(api.price(100), '+100');
  assert.equal(api.price(null), '–');
  assert.equal(api.line(-1.5), '−1,5');
  assert.equal(api.line(0.5), '+0,5');
  assert.equal(api.line(0), '0');
  assert.equal(api.line(2.5, false), '2,5');
});

test('a price move of a point or more is coloured, smaller moves are not', () => {
  assert.equal(api.tone(6.1), 'up');
  assert.equal(api.tone(-1), 'down');
  assert.equal(api.tone(0.6), '');
  assert.equal(api.tone(undefined), '');
});

test('line history reads open, then each change with its ET time (date when not today)', () => {
  const today = '2026-11-25';
  const seq = [['open', -165], ['2026-11-25T17:30:00.000Z', -210], ['2026-11-26T22:00:00.000Z', -230]];
  assert.equal(api.history(seq, today), 'Mở −165 · 12:30 −210 · 26/11 17:00 −230');
  const spread = [['open', [-0.5, -185]], ['2026-11-25T17:30:00.000Z', [-1.5, 120]]];
  assert.equal(api.history(spread, today, true), 'Mở −0,5 −185 · 12:30 −1,5 +120');
  const total = [['2026-11-25T17:30:00.000Z', [2.5, -160]]];
  assert.equal(api.history(total, today, false), '12:30 2,5 −160');
});

test('the board sorts by kickoff or by signal rank, and filters by competition', () => {
  const rows = [
    { event_id: 'a', comp: 'eng.1', start_time: '2026-11-28T15:00:00.000Z', signal_rank: 2 },
    { event_id: 'b', comp: 'usa.1', start_time: '2026-11-28T20:00:00.000Z', signal_rank: 1 },
    { event_id: 'c', comp: 'eng.1', start_time: '2026-11-27T20:00:00.000Z', signal_rank: 3 },
  ];
  assert.deepEqual([...api.arrange(rows, 'ALL', 'time')].map((r) => r.event_id), ['c', 'a', 'b']);
  assert.deepEqual([...api.arrange(rows, 'ALL', 'signal')].map((r) => r.event_id), ['b', 'a', 'c']);
  assert.deepEqual([...api.arrange(rows, 'eng.1', 'signal')].map((r) => r.event_id), ['a', 'c']);
  assert.equal(api.short('uefa.champions'), 'UCL');
  assert.equal(api.short('usa.1'), 'MLS');
});
