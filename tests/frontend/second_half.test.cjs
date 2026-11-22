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

test('an implied 2H line (no real ESPN 2H market) shows the 1H result but no pick', () => {
  const result = api.decide(halftime({ second_half: {
    away: 3.5, home: -3.5, total: 109.5, first_away: 5.5, first_home: -5.5, first_total: 101.5, implied: true } }));
  assert.equal(result.spread, null);
  assert.equal(result.total, null);
  assert.equal(result.first_result, 'under');
  assert.equal(result.first_spread_result, 'away_loss');
  assert.equal(result.implied, true);
});

test('1H score: the saved snapshot, the halftime score, or Q1+Q2 only once the second half has begun', () => {
  const live = (period, away, home) => ({ state: 'live', detail: `3:55 - ${period}`, away_score: 50, home_score: 48,
    situation: { period, away_period_scores: away, home_period_scores: home } });
  const plain = (v) => JSON.parse(JSON.stringify(v));
  assert.deepEqual(plain(api.firstHalfScore(live(2, [26, 22], [29, 19]), { away_score_1h: 40, home_score_1h: 41 })), [40, 41]);
  assert.deepEqual(plain(api.firstHalfScore(halftime(), null)), [42, 51]);
  assert.equal(api.firstHalfScore(live(2, [26, 24], [29, 19]), null), null);       // Q2 still running: no 1H yet
  assert.deepEqual(plain(api.firstHalfScore(live(3, [26, 24, 5], [29, 19, 2]), null)), [50, 48]);
  assert.equal(api.firstHalfScore(live(3, [26], [29]), null), null);                // quarters missing
});

// live 2H win chance from the 2H score so far and the time left (normal model around the 2H line)
const inTwoH = (league, period, clock, away, home) => ({ league, state: 'live', away_score: away, home_score: home,
  situation: { period, clock } });

test('2H win chance starts at 50% for both markets when the second half kicks off', () => {
  const spread = api.winChance({ market: 'spread', pick_side: 'home', line: 3.5 }, [10, 14], inTwoH('nfl', 3, '15:00', 10, 14));
  const total = api.winChance({ market: 'total', pick_side: 'over', line: 21.5 }, [10, 14], inTwoH('nfl', 3, '15:00', 10, 14));
  assert.equal(spread.p, 0.5);
  assert.equal(total.p, 0.5);
  assert.equal(spread.minutes, 30);
  assert.deepEqual([spread.away_2h, spread.home_2h], [0, 0]);
});

test('2H win chance follows the 2H score and grows surer as time runs out', () => {
  const pick = { market: 'spread', pick_side: 'home', line: 3.5 };
  const early = api.winChance(pick, [10, 14], inTwoH('nfl', 3, '10:00', 17, 14));   // home 2H 0-7 down, Q3 10:00
  const late = api.winChance(pick, [10, 14], inTwoH('nfl', 4, '1:00', 17, 14));     // same score, 1:00 left
  assert.ok(early.p < 0.5 && late.p < early.p && late.p < 0.05, `${early.p} ${late.p}`);
  assert.equal(late.now, -3.5);                                                     // 0-7 + 3.5 if it ended now
  const ahead = api.winChance(pick, [10, 14], inTwoH('nfl', 4, '2:00', 10, 21));    // home 2H 7-0 up
  assert.ok(ahead.p > 0.95, String(ahead.p));
  const over = api.winChance({ market: 'total', pick_side: 'over', line: 109.5 }, [52, 51], inTwoH('nba', 4, '5:00', 110, 105));
  assert.ok(over.p > 0.99, String(over.p));                                          // 112 already past 109.5
  const under = api.winChance({ market: 'total', pick_side: 'under', line: 109.5 }, [52, 51], inTwoH('nba', 4, '5:00', 110, 105));
  assert.ok(Math.abs(over.p + under.p - 1) < 1e-9);
});

test('2H win chance reads NBA sub-minute clocks and overtime, and needs the second half', () => {
  assert.ok(Math.abs(api.minutesLeft('nba', 4, '45.3') - 45.3 / 60) < 1e-9);
  assert.equal(api.minutesLeft('nba', 3, '6:00'), 18);
  assert.equal(api.minutesLeft('nfl', 5, '8:00'), 8);                              // overtime: what is left of it
  assert.equal(api.minutesLeft('nfl', 3, ''), null);
  const pick = { market: 'spread', pick_side: 'away', line: -0.5 };
  assert.equal(api.winChance(pick, [52, 51], inTwoH('nba', 2, '3:00', 52, 51)), null);   // still the first half
  assert.equal(api.winChance(pick, [null, 51], inTwoH('nba', 3, '9:00', 60, 58)), null);
  assert.equal(api.winChance(pick, [52, 51], { ...inTwoH('nba', 4, '0:00', 101, 99), state: 'final' }).p, 1);  // 2H 49-48
});

test('at halftime the lines the phone locked (and sent on Telegram) win over the browser\'s newer line', () => {
  const game = halftime({ second_half: { away: 4.5, home: -4.5, total: 111.5, first_away: 5.5, first_home: -5.5,
    first_total: 101.5, implied: true } });
  const snapshot = { second_spread_away: 3.5, second_spread_home: -3.5, second_total: null,
    first_spread_away: 5.5, first_spread_home: -5.5, first_total: 101.5 };
  const locked = api.withLockedLines(game, snapshot);
  assert.deepEqual(JSON.parse(JSON.stringify(locked.second_half)), { away: 3.5, home: -3.5, total: 111.5,
    first_away: 5.5, first_home: -5.5, first_total: 101.5, implied: false });
  assert.equal(api.decide(locked).spread.line, 3.5);
  assert.equal(api.withLockedLines(game, null), game);                        // nothing locked yet: unchanged
});
