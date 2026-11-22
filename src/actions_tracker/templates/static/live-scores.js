(function (root) {
  "use strict";
  const PATHS = { nfl: "football/nfl", ncaaf: "football/college-football", nba: "basketball/nba" };
  // Regular-season baselines: NFL Rule 4-1-3 (13m), NCAA Rule 3-2-1-b (20m).
  // The referee's actual restart can differ; these are explicitly labelled estimates.
  const HALFTIME_MINUTES = { nfl: 13, ncaaf: 20 };
  const DRIVE_POLL_MS = 10000;
  const halftimeCache = new Map();
  const driveCache = new Map();
  const NBA_VISUAL_POLL_MS = 5000;  // follow the existing five-second live-score rhythm
  const nbaVisualCache = new Map();
  const LIVE_ODDS_POLL_MS = 60000;  // DraftKings live spread / total through ESPN, at most once a minute per game
  const liveOddsCache = new Map();
  const SECOND_HALF_POLL_MS = 60000;  // the second-half line during halftime, at most once a minute per game
  const secondHalfCache = new Map();
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
  // fetchGames only passes an event returned by matchEvent. When the collector has not persisted an ESPN id yet,
  // a unique full-team/orientation/time match is still safe for read-only ESPN detail and odds requests. A stored
  // id that disagrees remains blocked instead of silently switching to another event.
  function canFetchMatchedEvent(game, event) {
    const eventId = String(event && event.event_id || ""), stored = String(game && game.espn_event_id || "");
    return /^\d+$/.test(eventId) && (!stored || stored === eventId);
  }
  const boundedInteger = (value, min, max) => {
    if (typeof value !== "number" && (typeof value !== "string" || !/^\d+(?:\.0+)?$/.test(value.trim()))) return null;
    const n = Number(value);
    return Number.isSafeInteger(n) && n >= min && n <= max ? n : null;
  };
  const cleanText = (value, limit = 500) => typeof value === "string" && value.trim() ? value.trim().slice(0, limit) : null;
  // the two teams as ESPN names them in the summary: ids (to read who has the ball), abbreviations (to read
  // spot texts like "PIT 16") and logos
  const espnLogo = (team) => [...(team && Array.isArray(team.logos) ? team.logos.map((x) => x && x.href) : []), team && team.logo]
    .find((href) => /^https:\/\/[^/]*\.espncdn\.com\//i.test(String(href || ""))) || null;
  function gameTeams(summary, event) {
    const situation = event && event.situation || {};
    const comp = summary.header && Array.isArray(summary.header.competitions) ? summary.header.competitions[0] || {} : {};
    const teams = Array.isArray(comp.competitors) ? comp.competitors : [];
    const team = (where) => { const c = teams.find((x) => x && x.homeAway === where); return c && c.team || {}; };
    const away = team("away"), home = team("home");
    return {
      away: { id: String(situation.away_espn_id || away.id || ""), abbr: cleanText(away.abbreviation, 12), logo: espnLogo(away) },
      home: { id: String(situation.home_espn_id || home.id || ""), abbr: cleanText(home.abbreviation, 12), logo: espnLogo(home) },
    };
  }
  const sideOfTeam = (team, teams) => {
    const id = team && /^\d+$/.test(String(team.id || "")) ? String(team.id) : null;
    return id && id === teams.away.id ? "away" : id && id === teams.home.id ? "home" : null;
  };
  // "away" / "home" for the ESPN team that has the ball on a drive (null when it cannot be matched)
  const driveSide = (summary, event, drive) => sideOfTeam(drive && drive.team, gameTeams(summary, event));
  const nbaClockSeconds = (value) => {
    const raw = String(value || "").trim(), match = /^(\d{1,2}):(\d{2}(?:\.\d+)?)$/.exec(raw);
    if (match) {
      const seconds = Number(match[2]);
      return seconds < 60 ? Number(match[1]) * 60 + seconds : null;
    }
    const seconds = Number(raw);
    return Number.isFinite(seconds) && seconds >= 0 && seconds <= 720 ? seconds : null;
  };
  const nbaElapsed = (play) => {
    const period = boundedInteger(play && play.period && play.period.number, 1, 20);
    const remaining = nbaClockSeconds(play && play.clock && play.clock.displayValue);
    if (period === null || remaining === null) return null;
    const before = period <= 4 ? (period - 1) * 720 : 4 * 720 + (period - 5) * 300;
    return before + (period <= 4 ? 720 : 300) - remaining;
  };
  function nbaRun(plays, teams) {
    const scoring = [];
    for (const play of plays) {
      const side = sideOfTeam(play && play.team, teams);
      const points = boundedInteger(play && play.scoreValue, 1, 4);
      if (play && play.scoringPlay === true && side && points !== null) scoring.push({ play, side, points });
    }
    if (!scoring.length) return null;
    const side = scoring[scoring.length - 1].side, run = [];
    for (let i = scoring.length - 1; i >= 0; i--) {
      if (scoring[i].side !== side) break;
      run.unshift(scoring[i]);
    }
    const points = run.reduce((sum, item) => sum + item.points, 0);
    if (points < 6) return null;
    const first = nbaElapsed(run[0].play), last = nbaElapsed(run[run.length - 1].play);
    return { team_side: side, team_abbr: teams[side].abbr, points,
      seconds: first !== null && last !== null ? Math.max(0, Math.round(last - first)) : null };
  }
  function parseNbaVisual(summary, event, eventId) {
    if (!summary || String(summary.header && summary.header.id || "") !== String(eventId)
      || !Array.isArray(summary.plays)) return null;
    const teams = gameTeams(summary, event), valid = [];
    for (const play of summary.plays) {
      const side = sideOfTeam(play && play.team, teams), coordinate = play && play.coordinate || {};
      if (coordinate.x === null || coordinate.x === undefined || coordinate.y === null || coordinate.y === undefined) continue;
      const x = Number(coordinate.x), y = Number(coordinate.y);
      const period = boundedInteger(play && play.period && play.period.number, 1, 20);
      if (!play || play.shootingPlay !== true || !side || period === null || !Number.isFinite(x) || !Number.isFinite(y)
        || x < 0 || x > 50 || y < 0 || y > 50) continue;
      valid.push({ play, side, x, y: Math.min(47, y), period });
    }
    if (!valid.length) return null;
    const latest = valid[valid.length - 1], play = latest.play;
    // ESPN normalizes every shot to a half court (50 x 47 ft). Put it on a full court and swap ends at halftime.
    const left = latest.side === "away" ? latest.period <= 2 : latest.period > 2;
    const distance = 5 + latest.y / 47 * 45;
    const courtX = left ? distance : 100 - distance, courtY = 8 + latest.x / 50 * 84;
    let probability = null;
    for (let i = Array.isArray(summary.winprobability) ? summary.winprobability.length - 1 : -1; i >= 0; i--) {
      const home = Number(summary.winprobability[i] && summary.winprobability[i].homeWinPercentage);
      if (!Number.isFinite(home) || home < 0 || home > 1) continue;
      const side = home >= .5 ? "home" : "away";
      probability = { team_side: side, team_abbr: teams[side].abbr, pct: Math.round(Math.max(home, 1 - home) * 1000) / 10 };
      break;
    }
    const attempted = boundedInteger(play.pointsAttempted, 1, 3), scored = boundedInteger(play.scoreValue, 0, 4);
    const made = play.scoringPlay === true && scored !== null && scored > 0;
    return {
      play_id: String(play.id || ""), team_side: latest.side, team_abbr: teams[latest.side].abbr,
      team_logo: teams[latest.side].logo, made, points_attempted: attempted,
      label: cleanText(play.shortDescription, 40) || (made ? `+${scored || attempted || 2} Points` : attempted === 3 ? "Missed 3PT" : "Missed FG"),
      text: cleanText(play.text, 300), clock: cleanText(play.clock && play.clock.displayValue, 12), period: latest.period,
      away_score: score(play.awayScore), home_score: score(play.homeScore),
      court_x: Math.round(courtX * 100) / 100, court_y: Math.round(courtY * 100) / 100,
      hoop_side: left ? "left" : "right", win_probability: probability,
      run: nbaRun(summary.plays, teams),
    };
  }
  async function fetchNbaVisual(game, event, fetcher) {
    if (game.league !== "nba" || event.state !== "live" || !canFetchMatchedEvent(game, event)) return null;
    const key = "nba/" + event.event_id;
    let cached = nbaVisualCache.get(key);
    if (cached && (cached.promise || Date.now() < cached.nextTry)) return cached.promise || cached.value;
    if (!cached) cached = { value: null, nextTry: 0, promise: null };
    cached.nextTry = Date.now() + NBA_VISUAL_POLL_MS;
    nbaVisualCache.set(key, cached);
    cached.promise = (async () => {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 5000);
      try {
        const url = `https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=${encodeURIComponent(event.event_id)}`;
        const res = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
        if (res.ok) {
          const visual = parseNbaVisual(await res.json(), event, event.event_id);
          if (visual) cached.value = visual;
        }
      } catch (error) { /* Keep the last valid shot through a transient ESPN failure. */ }
      finally { clearTimeout(timeout); }
      return cached.value;
    })().finally(() => { cached.promise = null; });
    return cached.promise;
  }
  // the ball on the field axis: 0 = away goal line (left) .. 100 = home goal line (right). The spot text names the
  // half of the field ("PIT 16" = 16 yards from PIT's goal line, whoever has the ball); yardsToEndzone counts for
  // the team holding the ball at that moment (after a punt that is the receiving team)
  function spotX(point, teams, holder) {
    const spot = cleanText(point.possessionText, 50) || "";
    if (/^50$/.test(spot)) return 50;
    const m = /^(\S+)\s+(\d{1,2})$/.exec(spot);
    if (m && teams.away.abbr && m[1] === teams.away.abbr) return Number(m[2]);
    if (m && teams.home.abbr && m[1] === teams.home.abbr) return 100 - Number(m[2]);
    const toGo = boundedInteger(point.yardsToEndzone, 0, 100);
    return toGo === null || !holder ? null : holder === "away" ? 100 - toGo : toGo;
  }
  // Non-scoring big plays (scores are caught from the scoreboard): the offense of the drive lost the ball or missed.
  // A return touchdown is left to the score jump so it is announced once, as a touchdown.
  const BIG_PLAY_KINDS = [
    [/touchdown/i, null],
    [/interception/i, "interception"],
    [/fumble recovery \(opponent\)/i, "fumble_lost"],
    [/field goal missed|missed field goal|blocked field goal/i, "field_goal_missed"],
  ];
  function parseBigPlays(summary, event, eventId) {
    if (!summary || String(summary.header && summary.header.id || "") !== String(eventId)) return [];
    const drives = summary.drives || {}, previous = Array.isArray(drives.previous) ? drives.previous : [];
    const out = [], seen = new Set();
    for (const drive of [previous[previous.length - 1], drives.current]) {
      const offense = drive && Array.isArray(drive.plays) ? driveSide(summary, event, drive) : null;
      if (!offense) continue;
      for (const play of drive.plays) {
        const id = play && /^\d+$/.test(String(play.id || "")) ? String(play.id) : null;
        if (!id || seen.has(id)) continue;  // ESPN may list the current drive in "previous" too
        seen.add(id);
        // a return touchdown (typed or only flagged/described as one) is announced by the score jump
        if (play.scoringPlay === true || /touchdown|\bTD\b/i.test(String(play.text || ""))) continue;
        const match = BIG_PLAY_KINDS.find(([pattern]) => pattern.test(String(play.type && play.type.text || "")));
        if (match && match[1]) out.push({ id, kind: match[1], side: offense === "away" ? "home" : "away", text: cleanText(play.text, 300) });
      }
    }
    return out;
  }
  function parseDrive(summary, event, eventId) {
    if (!summary || String(summary.header && summary.header.id || "") !== String(eventId)) return null;
    const drive = summary.drives && summary.drives.current;
    if (!drive || !Array.isArray(drive.plays) || !drive.plays.length) return null;
    const teams = gameTeams(summary, event);
    const side = sideOfTeam(drive.team, teams);
    if (!side) return null;
    const teamId = String(drive.team.id);
    // the latest play is shown as "last play"; the position comes from the latest play that describes it,
    // because a timeout or a quarter break carries a yard line but no down & distance or spot text
    const usable = (pt) => pt && typeof pt === "object"
      && (boundedInteger(pt.yardsToEndzone, 0, 100) !== null || cleanText(pt.possessionText)) ? pt : null;
    let play = null, point = null;
    for (let i = drive.plays.length - 1; i >= 0; i--) {
      const candidate = drive.plays[i];
      if (!candidate || typeof candidate !== "object") continue;
      const candidatePoint = usable(candidate.end) || usable(candidate.start);
      if (!candidatePoint) continue;
      if (!play) { play = candidate; point = candidatePoint; }
      if (cleanText(candidatePoint.possessionText) || cleanText(candidatePoint.shortDownDistanceText)) { point = candidatePoint; break; }
    }
    if (!play || !point) return null;
    // who has the ball now: the team on that play's spot (after a punt or a turnover ESPN keeps the old drive as
    // "current" until the next snap, but the play already names the new offense)
    const offense = sideOfTeam(point.team, teams) || side;
    const ball = spotX(point, teams, offense);
    if (ball === null) return null;
    const distance = boundedInteger(point.distance, 0, 99);
    const down = boundedInteger(point.down, 1, 4);
    const first = distance === null ? null : Math.max(0, Math.min(100, ball + (offense === "away" ? distance : -distance)));
    const sameDrive = offense === side;
    // where the drive began: the spot of its first scrimmage play (a kickoff is measured for the kicking team)
    const opening = sameDrive ? drive.plays.find((p) => p && typeof p === "object" && p.start && typeof p.start === "object"
      && !/kickoff/i.test(String(p.type && p.type.text || ""))
      && (!p.start.team || String(p.start.team.id || "") === teamId)
      && (boundedInteger(p.start.yardsToEndzone, 0, 100) !== null || cleanText(p.start.possessionText))) : null;
    const startX = opening ? spotX(opening.start, teams, side) : null;
    const statYardage = typeof play.statYardage === "number" && Number.isFinite(play.statYardage)
      && play.statYardage >= -99 && play.statYardage <= 99 ? play.statYardage : null;
    return {
      team_side: offense,
      team_abbr: sameDrive ? cleanText(drive.team && drive.team.abbreviation, 12) : teams[offense].abbr,
      team_logo: sameDrive ? espnLogo(drive.team) : teams[offense].logo,
      description: sameDrive ? cleanText(drive.description, 100) : null,  // the old drive's summary is not the new offense's
      down_distance: cleanText(point.shortDownDistanceText, 50),
      spot: cleanText(point.possessionText, 50),
      ball_x: ball,
      start_x: startX,
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
    if (!["nfl", "ncaaf"].includes(game.league) || !canFetchMatchedEvent(game, event)) return null;
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
        if (res.ok) {
          const summary = await res.json(), drive = parseDrive(summary, event, event.event_id);
          cached.value = drive && { ...drive, big_plays: parseBigPlays(summary, event, event.event_id) };
        }
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
  const finite = (value) => {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  const currentPointSpread = (team) => finite(team && team.current && team.current.pointSpread
    && (team.current.pointSpread.american ?? team.current.pointSpread.alternateDisplayValue));
  const currentSpreadOdds = (team) => finite(team && (team.spreadOdds ?? (team.current && team.current.spread
    && (team.current.spread.american ?? team.current.spread.alternateDisplayValue))));
  // Full-game live market from the verified "DraftKings - Live Odds" provider. Keep spread and total separate;
  // the scoreboard later shows only the market the user actually selected.
  function parseLiveOdds(item) {
    if (!item || !/live/i.test(String(item.provider && item.provider.name || ""))) return null;
    const homeTeam = item.homeTeamOdds || {}, awayTeam = item.awayTeamOdds || {};
    let homeLine = currentPointSpread(homeTeam), awayLine = currentPointSpread(awayTeam);
    const fallbackHome = finite(item.spread);
    if (homeLine === null && fallbackHome !== null) homeLine = fallbackHome;
    if (awayLine === null && homeLine !== null) awayLine = -homeLine;
    if (homeLine === null && awayLine !== null) homeLine = -awayLine;
    const totalLine = finite(item.overUnder);
    const result = {
      provider: cleanText(item.provider && item.provider.name, 80),
      spread: homeLine === null && awayLine === null ? null : {
        away: { line: awayLine, odds: currentSpreadOdds(awayTeam) },
        home: { line: homeLine, odds: currentSpreadOdds(homeTeam) },
      },
      total: totalLine === null ? null : {
        line: totalLine,
        over_odds: finite(item.overOdds ?? (item.current && item.current.over
          && (item.current.over.american ?? item.current.over.alternateDisplayValue))),
        under_odds: finite(item.underOdds ?? (item.current && item.current.under
          && (item.current.under.american ?? item.current.under.alternateDisplayValue))),
      },
    };
    return result.spread || result.total ? result : null;
  }
  async function fetchOddsList(game, event, fetcher) {
    if (!Object.keys(PATHS).includes(game.league) || !canFetchMatchedEvent(game, event)) return null;
    const key = game.league + "/" + event.event_id;
    let cached = liveOddsCache.get(key);
    if (cached && (cached.promise || Date.now() < cached.nextTry)) return cached.promise || cached.value;
    if (!cached) cached = { value: null, nextTry: 0, promise: null };
    cached.nextTry = Date.now() + LIVE_ODDS_POLL_MS;
    liveOddsCache.set(key, cached);
    cached.promise = (async () => {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 6000);
      try {
        const id = encodeURIComponent(event.event_id);
        // ESPN's CDN can keep the canonical odds URL stale for several minutes even with browser no-store.
        // One URL per polling minute bypasses that edge-cache entry without increasing our request rate.
        const cacheMinute = Math.floor(Date.now() / LIVE_ODDS_POLL_MS);
        const url = `https://sports.core.api.espn.com/v2/sports/${PATHS[game.league].replace("/", "/leagues/")}`
          + `/events/${id}/competitions/${id}/odds?lang=en&region=us&live=${cacheMinute}`;
        const res = await fetcher(url, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
        if (res.ok) {
          const body = await res.json();
          if (Array.isArray(body && body.items)) cached.value = body.items;
        }
      } catch (error) { /* keep the last verified market through a transient ESPN failure */ }
      finally { clearTimeout(timeout); }
      return cached.value;
    })().finally(() => { cached.promise = null; });
    return cached.promise;
  }
  async function fetchLiveOdds(game, event, fetcher) {
    const items = await fetchOddsList(game, event, fetcher);
    const live = (Array.isArray(items) ? items : [])
      .find((item) => /live/i.test(String(item && item.provider && item.provider.name || "")));
    return parseLiveOdds(live);
  }
  // "2nd Half Spread" (one row per team) and "2nd Half Total" from ESPN's live prop bets (DraftKings - Live Odds)
  function parseSecondHalf(body, awayId, homeId) {
    const out = { away: null, home: null, total: null };
    for (const item of Array.isArray(body && body.items) ? body.items : []) {
      const name = String(item && item.type && item.type.name || "");
      const value = finite(item && item.current && item.current.target && item.current.target.value);
      if (value === null) continue;
      if (/^2nd half spread$/i.test(name)) {
        const id = (String(item.team && item.team.$ref || "").match(/\/teams\/(\d+)/) || [])[1];
        if (id && id === String(awayId)) out.away = value;
        else if (id && id === String(homeId)) out.home = value;
      } else if (/^2nd half total$/i.test(name) && out.total === null) out.total = value;
    }
    if (out.away === null && out.home !== null) out.away = -out.home;
    if (out.home === null && out.away !== null) out.home = -out.away;
    return out.away === null && out.total === null ? null : out;
  }
  function parseFirstHalfTotal(body) {
    for (const item of Array.isArray(body && body.items) ? body.items : []) {
      const name = String(item && item.type && item.type.name || "");
      const value = finite(item && item.current && item.current.target && item.current.target.value);
      if (/^1st half total$/i.test(name) && value !== null) return value;
    }
    return null;
  }
  function parseFirstHalf(body, awayId, homeId) {
    const out = { away: null, home: null, total: parseFirstHalfTotal(body) };
    for (const item of Array.isArray(body && body.items) ? body.items : []) {
      const name = String(item && item.type && item.type.name || "");
      const value = finite(item && item.current && item.current.target && item.current.target.value);
      if (!/^1st half spread$/i.test(name) || value === null) continue;
      const id = (String(item.team && item.team.$ref || "").match(/\/teams\/(\d+)/) || [])[1];
      if (id && id === String(awayId)) out.away = value;
      else if (id && id === String(homeId)) out.home = value;
    }
    if (out.away === null && out.home !== null) out.away = -out.home;
    if (out.home === null && out.away !== null) out.home = -out.away;
    return out.away === null && out.total === null ? null : out;
  }
  // Some ESPN games expose a live full-game market at halftime but no propBets collection (404 for the
  // 2H endpoint). Remove the first-half score from that live market to get the equivalent second-half line.
  // Mark it as implied so the scoreboard never presents it as a direct DraftKings 2H market.
  function impliedSecondHalf(live, event) {
    const awayScore = finite(event && event.away_score), homeScore = finite(event && event.home_score);
    if (!live || awayScore === null || homeScore === null) return null;
    const half = (value) => Math.round(value * 2) / 2;
    const awayFull = finite(live.spread && live.spread.away && live.spread.away.line);
    const homeFull = finite(live.spread && live.spread.home && live.spread.home.line);
    const fullTotal = finite(live.total && live.total.line);
    const away = awayFull === null ? null : half(awayScore - homeScore + awayFull);
    const home = homeFull === null ? null : half(homeScore - awayScore + homeFull);
    const total = fullTotal === null || fullTotal < awayScore + homeScore ? null : half(fullTotal - awayScore - homeScore);
    return away === null && home === null && total === null ? null : { away, home, total, implied: true };
  }
  async function fetchSecondHalf(game, event, fetcher) {
    if (!Object.keys(PATHS).includes(game.league) || !canFetchMatchedEvent(game, event)) return null;
    const key = game.league + "/" + event.event_id;
    let cached = secondHalfCache.get(key);
    if (cached && (cached.promise || Date.now() < cached.nextTry)) return cached.promise || cached.value;
    if (!cached) cached = { value: null, nextTry: 0, promise: null };
    cached.nextTry = Date.now() + SECOND_HALF_POLL_MS;
    secondHalfCache.set(key, cached);
    cached.promise = (async () => {
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 6000);
      try {
        const opts = { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal };
        const list = await fetchOddsList(game, event, fetcher);
        const markets = Array.isArray(list) ? list : [];
        const live = markets
          .find((x) => /live/i.test(String(x && x.provider && x.provider.name || "")));
        const pregame = markets.find((x) => /^draftkings$/i.test(String(x && x.provider && x.provider.name || "")));
        const propsRef = (market) => {
          const ref = String(market && market.propBets && market.propBets.$ref || "");
          return /^https?:\/\/sports\.core\.api\.espn\.com\//.test(ref)
            ? ref.replace(/^http:/, "https:") + (ref.includes("?") ? "&" : "?") + "limit=1000" : null;
        };
        const fetchProps = async (ref) => {
          if (!ref) return null;
          try { const response = await fetcher(ref, opts); return response.ok ? await response.json() : null; }
          catch (error) { return null; }
        };
        const [liveProps, pregameProps] = await Promise.all([fetchProps(propsRef(live)), fetchProps(propsRef(pregame))]);
        const situation = event.situation || {};
        const second = parseSecondHalf(liveProps, situation.away_espn_id, situation.home_espn_id);
        const first = parseFirstHalf(pregameProps, situation.away_espn_id, situation.home_espn_id);
        if (second || first) cached.value = { ...(cached.value || {}), ...(second || {}),
          ...(first ? { first_away: first.away, first_home: first.home, first_total: first.total } : {}) };
      } catch (error) { /* keep the last line through a transient ESPN failure */ }
      finally { clearTimeout(timeout); }
      return cached.value;
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
          if (e.state !== "live") {
            driveCache.delete(game.league + "/" + e.event_id);
            liveOddsCache.delete(game.league + "/" + e.event_id);
            nbaVisualCache.delete("nba/" + e.event_id);
          }
          const [liveOdds, nbaVisual] = e.state === "live"
            ? await Promise.all([fetchLiveOdds(game, e, fetcher), fetchNbaVisual(game, e, fetcher)]) : [null, null];
          // the second-half line is only shown during halftime; it is dropped as soon as the 2nd half starts
          let secondHalf = null;
          if (e.state === "live" && e.is_halftime) {
            const direct = await fetchSecondHalf(game, e, fetcher);
            const hasDirectLine = direct && (finite(direct.away) !== null || finite(direct.home) !== null || finite(direct.total) !== null);
            const implied = hasDirectLine ? null : impliedSecondHalf(liveOdds, e);
            secondHalf = direct || implied ? { ...(implied || {}), ...(direct || {}) } : null;
          }
          else secondHalfCache.delete(game.league + "/" + e.event_id);
          result.scores.push({ game_id: Number(game.game_id), away_score: e.away_score, home_score: e.home_score,
            state: e.state, detail: e.detail, situation, drive, updated_at: checked, graded: false,
            ...(liveOdds ? { live_odds: liveOdds } : {}),
            ...(nbaVisual ? { nba_visual: nbaVisual } : {}),
            ...(secondHalf ? { second_half: secondHalf } : {}) });
        }));
      } catch (error) { result.failed.push(...part.map((g) => Number(g.game_id))); }
      finally { clearTimeout(timeout); }
    }));
    return result;
  }
  root.ActionsLiveScores = { dateKey, parseEvent, matchEvent, parseDrive, parseBigPlays, parseNbaVisual, parseLiveOdds,
    parseSecondHalf, parseFirstHalf, parseFirstHalfTotal, impliedSecondHalf, halftimeEnd, fetchGames };
})(globalThis);
