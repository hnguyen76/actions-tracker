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

// real DraftKings pregame + live items for VIL @ SLP, 25/11 12:46 ET (home SLP 494, away VIL 102)
const ODDS = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/espn_soccer_odds_live.json'), 'utf8'));

test('the DraftKings live market reads the 3-way moneyline and the total now', () => {
  const live = plain(api.parseLiveOdds(ODDS.items.find((x) => /live/i.test(x.provider.name))));
  assert.deepEqual(live, { ml: { home: 180, away: 135, draw: 265 }, total: { line: 2.5, over: -172, under: 144 } });
  assert.equal(api.parseLiveOdds(ODDS.items.find((x) => x.provider.name === 'DraftKings')), null);
});

test('at halftime the 2H moneyline is DraftKings\' "Moneyline - Rest of Game" (real BAR @ SAB, 25/11 13:34 ET)', () => {
  const rest = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/espn_soccer_props_live_ht.json'), 'utf8'));
  assert.deepEqual(plain(api.halfMarkets(rest, '21922', '83').rest_ml), { home: 1100, away: -450, draw: 400 });
  const onlyDraw = { items: rest.items.filter((x) => !x.team) };              // the team prices were off the board
  assert.deepEqual(plain(api.halfMarkets(onlyDraw, '21922', '83').rest_ml), { draw: 400 });
});

test('fetchLive: live games with pregame and live lines; at halftime the half markets and the 2H plays', async () => {
  const event = (state, name, home, away) => ({ id: '401915293', date: '2026-11-25T17:45Z', competitions: [{
    status: { displayClock: "45'+3'", period: 1, type: { state, name, shortDetail: name === 'STATUS_HALFTIME' ? 'HT' : "45'+3'" } },
    competitors: [{ homeAway: 'home', score: String(home), team: { id: '494', abbreviation: 'SLP' } },
      { homeAway: 'away', score: String(away), team: { id: '102', abbreviation: 'VIL' } }] }] });
  const restOfGame = (withTeams) => ({ items: [
    ...(withTeams ? [{ type: { name: 'Moneyline - Rest of Game' }, team: { $ref: 'x/teams/102' }, current: { over: { american: '+150' } } },
      { type: { name: 'Moneyline - Rest of Game' }, team: { $ref: 'x/teams/494' }, current: { over: { american: '+230' } } }] : []),
    { type: { name: 'Moneyline - Rest of Game' }, team: null, current: { over: { american: '+140' } } }] });
  const run = async (status, home, away, withTeams = true) => {
    const urls = [];
    const fetcher = async (url) => {
      urls.push(url);
      let body = { events: [] };
      if (url.includes('/uefa.champions/scoreboard')) body = { events: [event('in', status, home, away)] };
      else if (url.includes('/odds?')) body = ODDS;
      else if (url.includes('propBets')) body = restOfGame(withTeams);
      return { ok: true, json: async () => JSON.parse(JSON.stringify(body)) };
    };
    // the 1H lines the phone captured before kickoff (Soccer_Half_Lines)
    const half = new Map([['401915293', api.halfMarkets(PROPS, '494', '102')]]);
    return plain(await api.fetchLive(fetcher, Date.parse('2026-11-25T18:35:00Z'), half));
  };
  const live = await run('STATUS_FIRST_HALF', 1, 0);
  assert.equal(live.length, 1);
  assert.deepEqual(live[0].live.ml, { home: 180, away: 135, draw: 265 });
  assert.equal(live[0].second_half, undefined);                             // only at halftime
  // halftime 1-0 to SLP: the live full-game total 2,5 minus the goal = the 2H total 1,5 (same prices)
  const ht = (await run('STATUS_HALFTIME', 1, 0))[0];
  assert.equal(ht.halftime, true);
  assert.deepEqual(ht.markets.first_total, { line: 1.5, over: 127, under: -166 });
  assert.deepEqual(ht.markets.second_total, { line: 1.5, over: -172, under: 144 });
  assert.deepEqual(ht.second_half.side, { team: 'away', price: 150, favourite: 'away', covered: false });
  assert.deepEqual(ht.second_half.total, { side: 'over', line: 1.5, price: -172, first_goals: 1, first_line: 1.5 });
});

test('fetchLive: a 2H team price off the board shows no price, never the stale pregame 2H moneyline', async () => {
  const fetcher = async (url) => {
    let body = { events: [] };
    if (url.includes('/uefa.champions/scoreboard')) body = { events: [{ id: '777', date: '2026-11-25T17:45Z', competitions: [{
      status: { displayClock: "45'+3'", period: 1, type: { state: 'in', name: 'STATUS_HALFTIME', shortDetail: 'HT' } },
      competitors: [{ homeAway: 'home', score: '0', team: { id: '494', abbreviation: 'SLP' } },
        { homeAway: 'away', score: '0', team: { id: '102', abbreviation: 'VIL' } }] }] }] };
    else if (url.includes('/odds?')) body = ODDS;
    else if (url.includes('propBets')) body = { items: [{ type: { name: 'Moneyline - Rest of Game' }, team: null, current: { over: { american: '+150' } } }] };
    return { ok: true, json: async () => JSON.parse(JSON.stringify(body)) };
  };
  const [g] = plain(await api.fetchLive(fetcher, Date.parse('2026-11-25T18:35:00Z'),
    new Map([['777', api.halfMarkets(PROPS, '494', '102')]])));
  assert.deepEqual(g.second_half.side, { team: 'away', price: null, favourite: 'away', covered: false });
});

test('fetchLive never reads the leftover pregame half props: no captured 1H lines, no 2H plays', async () => {
  const urls = [];
  const fetcher = async (url) => {
    urls.push(url);
    let body = { events: [] };
    if (url.includes('/uefa.champions/scoreboard')) body = { events: [{ id: '888', date: '2026-11-25T17:45Z', competitions: [{
      status: { displayClock: "45'+1'", period: 1, type: { state: 'in', name: 'STATUS_HALFTIME', shortDetail: 'HT' } },
      competitors: [{ homeAway: 'home', score: '0', team: { id: '494', abbreviation: 'SLP' } },
        { homeAway: 'away', score: '1', team: { id: '102', abbreviation: 'VIL' } }] }] }] };
    else if (url.includes('/odds?')) body = ODDS;
    else if (url.includes('propBets')) body = { items: [] };
    return { ok: true, json: async () => JSON.parse(JSON.stringify(body)) };
  };
  const [g] = plain(await api.fetchLive(fetcher, Date.parse('2026-11-25T18:35:00Z')));
  assert.deepEqual(g.second_half, { side: null, total: null });
  assert.equal(urls.filter((u) => u.includes('propBets')).length, 1);          // the live props only
});

test('a locked 2H play during the 2H: the 2H score and where it stands now', () => {
  const side = { market: 'ml', pick_side: 'home', home_1h: 0, away_1h: 1 };
  assert.deepEqual(plain(api.lockedStatus(side, 2, 1)), { home_2h: 2, away_2h: 0, now: 'win' });
  assert.equal(api.lockedStatus(side, 1, 2).now, 'loss');                    // 2H 1-1: the 3-way rest of game loses
  const over = { market: 'total', pick_side: 'over', line: 1.5, home_1h: 1, away_1h: 0 };
  assert.equal(api.lockedStatus(over, 2, 0).now, 'loss');                    // one 2H goal: under 1,5 so far
  assert.equal(api.lockedStatus(over, 2, 1).now, 'win');
  assert.equal(api.lockedStatus({ ...over, pick_side: 'under', line: 1 }, 2, 0).now, 'push');
  assert.equal(api.lockedStatus(over, null, 0), null);
});
