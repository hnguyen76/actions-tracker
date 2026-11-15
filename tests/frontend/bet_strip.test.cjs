const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../src/actions_tracker/templates/static/scoreboard.js'), 'utf8');

function load() {
  const ctx = { window: {}, document: { addEventListener() {}, querySelectorAll: () => [], createElement: () => ({}) },
                setTimeout, clearTimeout, setInterval, clearInterval, Date, Number, String, Math, JSON };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.window.ActionsScoreboard;
}

test('spread bet: margin after the line decides winning or losing', () => {
  const { betStatus } = load();
  const kc = betStatus({ bet_side: 'away', market: 'spread', line: -3, away_score: 7, home_score: 0, away_abbr: 'KC', home_abbr: 'ATL' });
  assert.equal(kc.state, 'win');
  assert.equal(kc.pick, 'KC -3');
  assert.match(kc.detail, /ATS: KC 7 − 3 = 4 vs ATL 0 → hơn 4 điểm/);
  const dog = betStatus({ bet_side: 'home', market: 'spread', line: 3.5, away_score: 10, home_score: 3, away_abbr: 'A', home_abbr: 'H' });
  assert.equal(dog.state, 'loss');
  assert.match(dog.detail, /kém 3,5 điểm/);
  assert.equal(betStatus({ bet_side: 'home', market: 'spread', line: 3, away_score: 3, home_score: 0 }).state, 'push');
});

test('total bet and missing data', () => {
  const { betStatus } = load();
  assert.equal(betStatus({ bet_side: 'under', market: 'total', line: 46.5, away_score: 20, home_score: 17 }).state, 'win');
  assert.equal(betStatus({ bet_side: 'over', market: 'total', line: 46.5, away_score: 20, home_score: 17 }).state, 'loss');
  assert.equal(betStatus({ bet_side: 'home', market: 'spread', line: null, away_score: 1, home_score: 2 }), null);
});
