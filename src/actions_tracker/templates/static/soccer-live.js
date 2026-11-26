/* Soccer live: DraftKings half markets (through ESPN's propBets) and the owner's 2H method, as in NFL.

   ESPN lists each half-total line twice, the over first and the under second, both under "current.over"; the order
   is checked: the over's chance must fall as the line rises, otherwise the totals are not trusted. There is no 1H
   handicap for soccer, so the 1H "spread" is the 1H moneyline favourite at -0,5:
   - side: the favourite that does not lead at halftime lost its 1H "spread" -> back it in the 2H; a favourite that
     leads -> back the other team in the 2H, at DraftKings' live 3-way "Moneyline - Rest of Game";
   - total: 1H goals under the main 1H total -> 2H Over; over it -> 2H Under, at the live full-game total less the
     1H goals (the same bet as a 2H total); exactly on a whole line, none.
   A price off the board at halftime shows as none: never the stale pregame 2H moneyline. */
(function (root) {
  "use strict";
  const finite = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(String(v).replace("+", ""))) ? null
    : Number(String(v).replace("+", "")));
  const prob = (price) => (price === null ? null : price > 0 ? 100 / (price + 100) : -price / (-price + 100));
  const teamId = (item) => (String(item && item.team && item.team.$ref || "").match(/\/teams\/(\d+)/) || [])[1] || null;
  const american = (item) => finite(item && item.current && item.current.over && item.current.over.american);

  function moneyline(items, name, homeId, awayId, partial = false) {
    const out = {};
    for (const item of items.filter((x) => x.type && x.type.name === name)) {
      const id = teamId(item), price = american(item);
      if (price === null) continue;
      if (id === null) out.draw = price;
      else if (id === String(homeId)) out.home = price;
      else if (id === String(awayId)) out.away = price;
    }
    if (partial) return Object.keys(out).length ? out : null;   // live: a price can be off the board for a while
    return ["home", "away", "draw"].every((k) => k in out) ? out : null;
  }
  // main line: the over / under pair closest to even; null when a pair breaks the falling over chance
  function total(items, name) {
    const lines = new Map();
    for (const item of items.filter((x) => x.type && x.type.name === name)) {
      const line = finite(item.current && item.current.target && item.current.target.value), price = american(item);
      if (line === null || price === null) continue;
      lines.set(line, [...(lines.get(line) || []), price]);
    }
    const pairs = [...lines.entries()].filter(([, p]) => p.length === 2).sort((a, b) => a[0] - b[0])
      .map(([line, [over, under]]) => {
        const po = prob(over), pu = prob(under);
        return { line, over, under, p: po / (po + pu) };
      });
    if (!pairs.length || pairs.some((x, i) => i && x.p >= pairs[i - 1].p)) return null;
    const main = pairs.reduce((best, x) => (Math.abs(x.p - 0.5) < Math.abs(best.p - 0.5) ? x : best));
    return { line: main.line, over: main.over, under: main.under };
  }
  function halfMarkets(props, homeId, awayId) {
    const items = Array.isArray(props && props.items) ? props.items : [];
    return {
      first_ml: moneyline(items, "1st Half Moneyline", homeId, awayId),
      second_ml: moneyline(items, "2nd Half Moneyline", homeId, awayId),
      first_total: total(items, "1st Half Total"),
      second_total: total(items, "2nd Half Total"),
      rest_ml: moneyline(items, "Moneyline - Rest of Game", homeId, awayId, true),
    };
  }

  // score1H: {home, away} at halftime (stoppage-time goals included); markets: halfMarkets of pregame + live props
  function decide2H(score1H, markets) {
    const m = markets || {}, home = finite(score1H && score1H.home), away = finite(score1H && score1H.away);
    if (home === null || away === null) return null;
    let side = null;
    const ml = m.first_ml;
    if (ml && ml.home !== ml.away) {
      const favourite = ml.home < ml.away ? "home" : "away";
      const lead = favourite === "home" ? home - away : away - home;
      const covered = lead >= 1;                      // the favourite at -0,5 needs a lead at halftime
      const team = covered ? (favourite === "home" ? "away" : "home") : favourite;
      const price = m.second_ml && m.second_ml[team] !== undefined ? m.second_ml[team] : null;
      side = { team, price, favourite, covered };
    }
    let total = null;
    const t1 = m.first_total, goals = home + away;
    if (t1 && goals !== t1.line) {
      const pick = goals < t1.line ? "over" : "under", t2 = m.second_total;
      total = { side: pick, line: t2 ? t2.line : null, price: t2 ? t2[pick] : null, first_goals: goals, first_line: t1.line };
    }
    return { side, total };
  }

  // one ESPN scoreboard event: teams, score, clock (stoppage time as "45'+2'"), halftime, pregame DraftKings line
  function parseEvent(raw, comp) {
    const c = (raw && raw.competitions || [])[0];
    if (!c) return null;
    const side = (k) => (c.competitors || []).find((x) => x.homeAway === k);
    const home = side("home"), away = side("away");
    if (!home || !away) return null;
    const status = c.status || raw.status || {}, type = status.type || {};
    const team = (x) => ({ id: String(x.team && x.team.id || ""), abbr: x.team && x.team.abbreviation,
      name: x.team && x.team.displayName });
    const dk = (c.odds || []).find((o) => o && /draftkings/i.test(String(o.provider && o.provider.name || ""))) || (c.odds || [])[0];
    let pregame = null;
    if (dk) {
      const now = (x) => x && (x.close || x.current || {});
      const ml = dk.moneyline || {}, tot = dk.total || {};
      const prices = { home: finite(now(ml.home).odds), away: finite(now(ml.away).odds), draw: finite(now(ml.draw).odds) };
      const line = finite(String(now(tot.over).line || "").replace(/^[ou]/, ""));
      pregame = {
        ml: Object.values(prices).every((v) => v !== null) ? prices : null,
        total: line === null ? null : { line, over: finite(now(tot.over).odds), under: finite(now(tot.under).odds) },
      };
    }
    return {
      event_id: String(raw.id), comp, start_time: raw.date, home: team(home), away: team(away),
      home_score: finite(home.score), away_score: finite(away.score),
      state: type.state === "in" ? "live" : type.state === "post" ? "final" : "scheduled",
      status: type.name || "", detail: type.shortDetail || "", clock: status.displayClock || "",
      period: finite(status.period), halftime: type.name === "STATUS_HALFTIME", pregame,
    };
  }

  // the DraftKings live market (provider name with "Live"): 3-way moneyline and total now
  function parseLiveOdds(item) {
    if (!item || !/live/i.test(String(item.provider && item.provider.name || ""))) return null;
    const price = (x) => finite(x && (x.moneyLine ?? (x.current && x.current.moneyLine && (x.current.moneyLine.american
      ?? x.current.moneyLine.alternateDisplayValue)) ?? (x.odds && x.odds.american)));
    const ml = { home: price(item.homeTeamOdds), away: price(item.awayTeamOdds), draw: price(item.drawOdds) };
    const line = finite(item.overUnder);
    const over = finite(item.overOdds ?? (item.current && item.current.over && item.current.over.american));
    const under = finite(item.underOdds ?? (item.current && item.current.under && item.current.under.american));
    const out = { ml: Object.values(ml).every((v) => v !== null) ? ml : null,
      total: line === null ? null : { line, over, under } };
    return out.ml || out.total ? out : null;
  }

  // a 2H play the phone locked at halftime (Soccer_2H_Plays) during the 2H: the 2H score and where the play stands
  // if the game ended now (the rest of game is 3-way: a level 2H loses; a total on the number is a push)
  function lockedStatus(play, homeScore, awayScore) {
    const h = finite(homeScore), a = finite(awayScore), h1 = finite(play && play.home_1h), a1 = finite(play && play.away_1h);
    if ([h, a, h1, a1].some((v) => v === null)) return null;
    const home = h - h1, away = a - a1;
    let edge;
    if (play.market === "ml") edge = play.pick_side === "home" ? home - away : away - home;
    else {
      const over = home + away - Number(play.line);
      edge = play.pick_side === "over" ? over : -over;
    }
    return { home_2h: home, away_2h: away, now: edge > 0 ? "win" : edge < 0 || play.market === "ml" ? "loss" : "push" };
  }

  const COMPS = ["eng.1", "esp.1", "usa.1"];
  const ODDS_POLL_MS = 60000;   // live odds and the 2H markets at halftime: at most once a minute per game
  const SCOREBOARD = (comp, d) => `https://site.web.api.espn.com/apis/site/v2/sports/soccer/${comp}/scoreboard?dates=${d}`;
  const ODDS = (comp, id) => `https://sports.core.api.espn.com/v2/sports/soccer/leagues/${comp}/events/${id}/competitions/${id}/odds?lang=en&region=us&limit=100`;
  const oddsCache = new Map(), liveProps = new Map();
  function dateKey(ms) {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric",
      month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23" }).formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
    return { day: p.year + p.month + p.day, hour: Number(p.hour) };
  }
  async function getJson(fetcher, url) {
    try {
      const r = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store" });
      return r && r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  const propsUrl = (item) => {
    const ref = String(item && item.propBets && item.propBets.$ref || "");
    return /^https?:\/\/sports\.core\.api\.espn\.com\//.test(ref)
      ? ref.replace(/^http:/, "https:") + (ref.includes("?") ? "&" : "?") + "limit=1000" : null;
  };
  async function cached(map, key, ttl, load) {
    const hit = map.get(key);
    if (hit && (hit.promise || Date.now() < hit.until)) return hit.promise || hit.value;
    const entry = { value: hit ? hit.value : null, until: Date.now() + ttl, promise: null };
    map.set(key, entry);
    entry.promise = load().then((v) => { entry.value = v || entry.value; return entry.value; }).finally(() => { entry.promise = null; });
    return entry.promise;
  }

  // live games of the selected competitions: score, clock, pregame and live DraftKings odds, and at halftime the 2H plays
  // halfLines: event_id -> {first_ml, first_total}, the 1H lines the phone captured before kickoff (Soccer_Half_Lines):
  // once a game is under way ESPN's pregame half props are leftovers, so they are never read here
  async function fetchLive(fetcher = root.fetch && root.fetch.bind(root), now = Date.now(), halfLines = new Map()) {
    const today = dateKey(now), days = [today.day];
    if (today.hour < 4) days.push(dateKey(now - 86400000).day);          // a late MLS game still on past midnight
    const boards = await Promise.all(COMPS.flatMap((comp) => days.map((d) => getJson(fetcher, SCOREBOARD(comp, d))
      .then((b) => ({ comp, b })))));
    const games = [];
    for (const { comp, b } of boards) {
      for (const raw of (b && b.events) || []) {
        const e = parseEvent(raw, comp);
        if (e && e.state === "live" && !games.some((g) => g.event_id === e.event_id)) games.push(e);
      }
    }
    await Promise.all(games.map(async (g) => {
      const items = await cached(oddsCache, g.event_id, ODDS_POLL_MS, async () => {
        const body = await getJson(fetcher, ODDS(g.comp, g.event_id));
        return body && Array.isArray(body.items) ? body.items : null;
      }) || [];
      const liveItem = items.find((x) => /live/i.test(String(x && x.provider && x.provider.name || "")));
      g.live = parseLiveOdds(liveItem);
      if (!g.halftime) return;
      const during = await cached(liveProps, g.event_id, ODDS_POLL_MS, async () => {
        const url = propsUrl(liveItem);
        return url ? getJson(fetcher, url) : null;
      });
      // DraftKings has no live "2nd Half" market for soccer at halftime, but two exact equivalents: the 3-way
      // "Moneyline - Rest of Game", and the live full-game total less the 1H goals (every later goal is a 2H goal)
      const first = halfLines.get(g.event_id) || {}, rest = halfMarkets(during, g.home.id, g.away.id).rest_ml;
      const t = g.live && g.live.total, goals = (g.home_score || 0) + (g.away_score || 0);
      g.markets = { first_ml: first.first_ml, first_total: first.first_total, second_ml: rest,
        second_total: t && t.line !== null ? { line: t.line - goals, over: t.over, under: t.under } : null };
      g.second_half = decide2H({ home: g.home_score, away: g.away_score }, g.markets);
    }));
    return games.sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time));
  }

  root.ActionsSoccerLive = { halfMarkets, decide2H, parseEvent, parseLiveOdds, fetchLive, lockedStatus, COMPS };
})(globalThis);
