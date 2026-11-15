(function (root) {
  "use strict";
  const PATHS = { nfl: "football/nfl", ncaaf: "football/college-football", nba: "basketball/nba" };
  const ALIASES = {
    "delaware fightin blue hens": "delaware blue hens", "hawaii warriors": "hawaii rainbow warriors",
    "miami fl hurricanes": "miami hurricanes", "north carolina state wolfpack": "nc state wolfpack",
    "southern miss golden eagles": "southern mississippi golden eagles",
  };
  const normalize = (v) => {
    const s = String(v || "").toLowerCase().replace(/&/g, " and ").replace(/['’]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
    return ALIASES[s] || s;
  };
  const score = (v) => v !== null && v !== undefined && /^\d+$/.test(String(v)) && Number.isSafeInteger(Number(v)) ? Number(v) : null;
  function dateKey(iso) {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(iso));
    const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
    return p.year + p.month + p.day;
  }
  function parseEvent(raw) {
    const comp = (raw.competitions || [])[0];
    if (!comp) return null;
    const away = (comp.competitors || []).find((c) => c.homeAway === "away"), home = (comp.competitors || []).find((c) => c.homeAway === "home");
    if (!away || !home) return null;
    const status = comp.status || raw.status || {}, type = status.type || {};
    return {
      event_id: String(raw.id || ""), start_time: raw.date || comp.date,
      away_name: away.team && away.team.displayName, home_name: home.team && home.team.displayName,
      away_score: score(away.score), home_score: score(home.score),
      state: type.state === "in" ? "live" : type.state === "post" && type.completed === true ? "final" : "scheduled",
      detail: type.shortDetail || type.detail || "",
      situation: root.ActionsScoreboard ? root.ActionsScoreboard.parseSituation(raw) : null,
    };
  }
  function matchEvent(game, events) {
    const start = Date.parse(game.start_time);
    const within = (e) => Number.isFinite(start) && Number.isFinite(Date.parse(e.start_time)) && Math.abs(start - Date.parse(e.start_time)) <= 12 * 3600000;
    if (game.espn_event_id) {
      const ids = events.filter((e) => e.event_id === String(game.espn_event_id) && within(e));
      if (ids.length === 1) return ids[0];
    }
    const home = normalize(game.home_name), away = normalize(game.away_name);
    if (!home || !away) return null;
    const exact = events.filter((e) => within(e) && normalize(e.home_name) === home && normalize(e.away_name) === away);
    return exact.length === 1 ? exact[0] : null;
  }
  async function fetchGames(games, fetcher = root.fetch.bind(root)) {
    const groups = new Map(), result = { scores: [], failed: [] };
    for (const g of games) {
      if (!PATHS[g.league] || !Number.isFinite(Date.parse(g.start_time))) continue;
      const key = g.league + "/" + dateKey(g.start_time);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(g);
    }
    await Promise.all([...groups.values()].map(async (part) => {
      const g = part[0], controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
      try {
        let url = `https://site.web.api.espn.com/apis/site/v2/sports/${PATHS[g.league]}/scoreboard?dates=${dateKey(g.start_time)}`;
        if (g.league === "ncaaf") url += "&groups=80&limit=300";
        const res = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
        if (!res.ok) throw new Error("Scoreboard HTTP " + res.status);
        const body = await res.json();
        if (!Array.isArray(body.events)) throw new Error("Invalid scoreboard");
        const events = body.events.map(parseEvent).filter(Boolean), checked = new Date().toISOString();
        for (const game of part) {
          const e = matchEvent(game, events);
          if (!e || e.state !== "scheduled" && (e.away_score === null || e.home_score === null)) { result.failed.push(Number(game.game_id)); continue; }
          result.scores.push({ game_id: Number(game.game_id), away_score: e.away_score, home_score: e.home_score,
            state: e.state, detail: e.detail, situation: e.situation, updated_at: checked, graded: false });
        }
      } catch (error) { result.failed.push(...part.map((g) => Number(g.game_id))); }
      finally { clearTimeout(timeout); }
    }));
    return result;
  }
  root.ActionsLiveScores = { dateKey, parseEvent, matchEvent, fetchGames };
})(globalThis);
