(function (root) {
  "use strict";
  const PATHS = { nfl: "football/nfl", ncaaf: "football/college-football", nba: "basketball/nba" };
  // Regular-season baselines: NFL Rule 4-1-3 (13m), NCAA Rule 3-2-1-b (20m).
  // The referee's actual restart can differ; these are explicitly labelled estimates.
  const HALFTIME_MINUTES = { nfl: 13, ncaaf: 20 };
  const DRIVE_POLL_MS = 10000;
  const halftimeCache = new Map();
  const driveCache = new Map();
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
      is_halftime: type.name === "STATUS_HALFTIME" || /^halftime$/i.test(type.shortDetail || type.description || ""),
      season_type: Number(raw.season && raw.season.type) || null,
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
  const boundedInteger = (value, min, max) => {
    if (typeof value !== "number" && (typeof value !== "string" || !/^\d+(?:\.0+)?$/.test(value.trim()))) return null;
    const n = Number(value);
    return Number.isSafeInteger(n) && n >= min && n <= max ? n : null;
  };
  const cleanText = (value, limit = 500) => typeof value === "string" && value.trim() ? value.trim().slice(0, limit) : null;
  function parseDrive(summary, event, eventId) {
    if (!summary || String(summary.header && summary.header.id || "") !== String(eventId)) return null;
    const drive = summary.drives && summary.drives.current;
    if (!drive || !Array.isArray(drive.plays) || !drive.plays.length) return null;
    const situation = event && event.situation || {};
    const headerCompetition = summary.header && Array.isArray(summary.header.competitions) ? summary.header.competitions[0] || {} : {};
    const headerTeams = Array.isArray(headerCompetition.competitors) ? headerCompetition.competitors : [];
    const headerAway = headerTeams.find((x) => x && x.homeAway === "away");
    const headerHome = headerTeams.find((x) => x && x.homeAway === "home");
    const awayId = String(situation.away_espn_id || headerAway && headerAway.team && headerAway.team.id || "");
    const homeId = String(situation.home_espn_id || headerHome && headerHome.team && headerHome.team.id || "");
    const teamId = drive.team && /^\d+$/.test(String(drive.team.id || "")) ? String(drive.team.id) : null;
    const side = teamId && teamId === awayId ? "away" : teamId && teamId === homeId ? "home" : null;
    if (!side) return null;
    let play = null, point = null;
    for (let i = drive.plays.length - 1; i >= 0; i--) {
      const candidate = drive.plays[i];
      if (!candidate || typeof candidate !== "object") continue;
      const end = candidate.end && typeof candidate.end === "object" ? candidate.end : null;
      const start = candidate.start && typeof candidate.start === "object" ? candidate.start : null;
      const candidatePoint = end && boundedInteger(end.yardsToEndzone, 0, 100) !== null ? end
        : start && boundedInteger(start.yardsToEndzone, 0, 100) !== null ? start : null;
      if (candidatePoint) { play = candidate; point = candidatePoint; break; }
    }
    if (!play || !point) return null;
    const yardsToEndzone = boundedInteger(point.yardsToEndzone, 0, 100);
    const ball = side === "away" ? 100 - yardsToEndzone : yardsToEndzone;
    const distance = boundedInteger(point.distance, 0, 99);
    const down = boundedInteger(point.down, 1, 4);
    const first = distance === null ? null : Math.max(0, Math.min(100, ball + (side === "away" ? distance : -distance)));
    // where the drive began: the spot of its first scrimmage play (a kickoff is measured for the kicking team)
    const opening = drive.plays.find((p) => p && typeof p === "object" && p.start && typeof p.start === "object"
      && !/kickoff/i.test(String(p.type && p.type.text || ""))
      && (!p.start.team || String(p.start.team.id || "") === teamId)
      && boundedInteger(p.start.yardsToEndzone, 0, 100) !== null);
    const startYards = opening ? boundedInteger(opening.start.yardsToEndzone, 0, 100) : null;
    const statYardage = typeof play.statYardage === "number" && Number.isFinite(play.statYardage)
      && play.statYardage >= -99 && play.statYardage <= 99 ? play.statYardage : null;
    const logo = Array.isArray(drive.team && drive.team.logos)
      ? drive.team.logos.map((x) => x && x.href).find((href) => /^https:\/\/[^/]*\.espncdn\.com\//i.test(String(href || ""))) || null : null;
    return {
      team_side: side,
      team_abbr: cleanText(drive.team && drive.team.abbreviation, 12),
      team_logo: logo,
      description: cleanText(drive.description, 100),
      down_distance: cleanText(point.shortDownDistanceText, 50),
      spot: cleanText(point.possessionText, 50),
      ball_x: ball,
      start_x: startYards === null ? null : side === "away" ? 100 - startYards : startYards,
      first_down_x: first,
      last_play: cleanText(play.text, 500),
      play_clock: cleanText(play.clock && play.clock.displayValue, 12),
      play_type: cleanText(play.type && play.type.text, 50),
      play_yards: statYardage,
      down,
      distance,
      updated_at: new Date().toISOString(),
    };
  }
  async function fetchDrive(game, event, fetcher) {
    if (!["nfl", "ncaaf"].includes(game.league) || !/^\d+$/.test(event.event_id)
      || String(game.espn_event_id || "") !== event.event_id) return null;
    const key = game.league + "/" + event.event_id;
    let cached = driveCache.get(key);
    if (cached && (cached.promise || Date.now() < cached.nextTry)) return cached.promise || cached.value;
    if (!cached) cached = { value: null, nextTry: 0, promise: null };
    cached.nextTry = Date.now() + DRIVE_POLL_MS;
    driveCache.set(key, cached);
    cached.promise = (async () => {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 4000);
      try {
        const url = `https://site.web.api.espn.com/apis/site/v2/sports/${PATHS[game.league]}/summary?event=${encodeURIComponent(event.event_id)}`;
        const res = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
        if (res.ok) cached.value = parseDrive(await res.json(), event, event.event_id);
      } catch (error) { /* Keep the last verified field position through a transient ESPN failure. */ }
      finally { clearTimeout(timeout); }
      return cached.value;
    })().finally(() => { cached.promise = null; });
    return cached.promise;
  }
  function halftimeEnd(summary, game, eventId, now = Date.now()) {
    const minutes = HALFTIME_MINUTES[game.league], kickoff = Date.parse(game.start_time);
    if (!minutes || !Number.isFinite(kickoff) || String(summary && summary.header && summary.header.id) !== String(eventId)) return null;
    const phase = summary.header.competitions && summary.header.competitions[0] && summary.header.competitions[0].status;
    if (phase && (Number(phase.period) >= 3 || phase.type && phase.type.completed === true)) return null;
    const drives = summary.drives || {}, plays = [];
    for (const drive of [drives.current, ...(Array.isArray(drives.previous) ? drives.previous : [])]) {
      if (drive && Array.isArray(drive.plays)) plays.push(...drive.plays);
    }
    const times = plays.filter((p) => p && Number(p.period && p.period.number) === 2
      && (String(p.type && p.type.id) === "65" || /^end of half$/i.test(p.type && p.type.text || ""))
      && /^0{1,2}:00$/.test(p.clock && p.clock.displayValue || ""))
      .map((p) => Date.parse(p.wallclock)).filter((t) => Number.isFinite(t) && t >= kickoff && t <= now);
    return times.length ? new Date(Math.max(...times) + minutes * 60000).toISOString() : null;
  }
  async function estimateHalftime(game, event, fetcher) {
    const key = game.league + "/" + event.event_id;
    let cached = halftimeCache.get(key);
    if (cached && (cached.endsAt || cached.promise || Date.now() < cached.nextTry)) return cached.promise || cached.endsAt;
    cached = { endsAt: null, nextTry: Date.now() + 30000, promise: null };
    halftimeCache.set(key, cached);
    cached.promise = (async () => {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 4000);
      try {
        const url = `https://site.web.api.espn.com/apis/site/v2/sports/${PATHS[game.league]}/summary?event=${encodeURIComponent(event.event_id)}`;
        const res = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
        if (res.ok) cached.endsAt = halftimeEnd(await res.json(), game, event.event_id);
      } catch (error) { /* The official Halftime label remains when no reliable timing anchor exists. */ }
      finally { clearTimeout(timeout); }
      return cached.endsAt;
    })().finally(() => { cached.promise = null; });
    return cached.promise;
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
        await Promise.all(part.map(async (game) => {
          const e = matchEvent(game, events);
          if (!e || e.state !== "scheduled" && (e.away_score === null || e.home_score === null)) { result.failed.push(Number(game.game_id)); return; }
          let situation = e.situation;
          let drive = null;
          if (e.state === "live" && e.is_halftime && e.season_type === 2 && /^\d+$/.test(e.event_id) && HALFTIME_MINUTES[game.league]) {
            situation = { ...situation, is_halftime: true, halftime_ends_at: await estimateHalftime(game, e, fetcher) };
          } else if (!e.is_halftime) {
            halftimeCache.delete(game.league + "/" + e.event_id);
            if (e.state === "live") drive = await fetchDrive(game, e, fetcher);
          }
          if (e.state !== "live") driveCache.delete(game.league + "/" + e.event_id);
          result.scores.push({ game_id: Number(game.game_id), away_score: e.away_score, home_score: e.home_score,
            state: e.state, detail: e.detail, situation, drive, updated_at: checked, graded: false });
        }));
      } catch (error) { result.failed.push(...part.map((g) => Number(g.game_id))); }
      finally { clearTimeout(timeout); }
    }));
    return result;
  }
  root.ActionsLiveScores = { dateKey, parseEvent, matchEvent, parseDrive, halftimeEnd, fetchGames };
})(globalThis);
