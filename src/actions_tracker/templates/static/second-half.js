(function (root) {
  "use strict";

  const finite = (value) => {
    const number = Number(value);
    return value !== null && value !== "" && Number.isFinite(number) ? number : null;
  };

  function isHalftime(game) {
    const situation = game && game.situation || {};
    const period = finite(situation.period);
    return game && game.state === "live" && (period === null || period < 3)
      && (situation.is_halftime === true || /\bhalftime\b|STATUS_HALFTIME/i.test(String(game.detail || "")));
  }

  // First-half score: the saved halftime snapshot, the score at halftime, or Q1+Q2 once the second half has
  // begun. Before halftime the second quarter is still running, so there is no first-half score yet.
  function firstHalfScore(game, snapshot) {
    if (snapshot) return [Number(snapshot.away_score_1h), Number(snapshot.home_score_1h)];
    if (isHalftime(game)) return [finite(game.away_score), finite(game.home_score)];
    const situation = game && game.situation || {}, period = finite(situation.period);
    if (!(period !== null && period >= 3) && !(game && game.state === "final")) return null;
    const away = situation.away_period_scores, home = situation.home_period_scores;
    const complete = (scores) => Array.isArray(scores) && scores.length >= 2 && scores.slice(0, 2).every((v) => finite(v) !== null);
    return complete(away) && complete(home)
      ? [finite(away[0]) + finite(away[1]), finite(home[0]) + finite(home[1])] : null;
  }

  // User rule: grade the first half against ESPN's actual 1H spread/total, then take the opposite result
  // with ESPN's 2H line. A raw scoreboard deficit alone never decides the spread play. A 2H line implied from
  // the live full-game market is not a real 2H market (and is not recorded by the tracker), so it gives no pick.
  function decide(game) {
    if (!isHalftime(game)) return null;
    const awayScore = finite(game.away_score), homeScore = finite(game.home_score);
    const odds = game.second_half && typeof game.second_half === "object" ? game.second_half : {};
    if (awayScore === null || homeScore === null) return null;
    const firstPoints = awayScore + homeScore;
    const implied = odds.implied === true;
    const firstTotal = finite(odds.first_total), secondTotal = implied ? null : finite(odds.total);
    const firstAway = finite(odds.first_away), firstHome = finite(odds.first_home);
    let spread = null, firstSpreadResult = "missing";
    if (firstAway !== null && firstHome !== null) {
      const awayMargin = awayScore - homeScore + firstAway;
      firstSpreadResult = awayMargin === 0 ? "push" : awayMargin < 0 ? "away_loss" : "home_loss";
      if (awayMargin !== 0) {
        const side = awayMargin < 0 ? "away" : "home", line = implied ? null : finite(odds[side]);
        if (line !== null) spread = { side, line, first_line: side === "away" ? firstAway : firstHome };
      }
    }
    const firstResult = firstTotal === null ? "missing" : firstPoints < firstTotal ? "under"
      : firstPoints > firstTotal ? "over" : "push";
    const total = ["under", "over"].includes(firstResult) && secondTotal !== null
      ? { side: firstResult === "under" ? "over" : "under", line: secondTotal } : null;
    return { spread, total, first_points: firstPoints, first_total: firstTotal, first_result: firstResult,
      first_spread_result: firstSpreadResult, implied };
  }

  // The phone locks the half lines at its first halftime sighting, the same run that sends the Telegram alert.
  // Once that snapshot is published, show those lines instead of the browser's newer ones, so the tab, the
  // Telegram message and the graded record agree. A locked 2H line is a real ESPN market, never implied.
  function withLockedLines(game, snapshot) {
    if (!snapshot) return game;
    const pairs = { away: "second_spread_away", home: "second_spread_home", total: "second_total",
      first_away: "first_spread_away", first_home: "first_spread_home", first_total: "first_total" };
    const locked = {};
    for (const [key, column] of Object.entries(pairs)) if (finite(snapshot[column]) !== null) locked[key] = finite(snapshot[column]);
    if (!Object.keys(locked).length) return game;
    if ("away" in locked || "home" in locked || "total" in locked) locked.implied = false;
    return { ...game, second_half: { ...(game.second_half || {}), ...locked } };
  }

  // Live 2H win chance. The rest of the 2H is a normal variable: its mean comes from the 2H line itself (the
  // line already prices the half: expected own margin = -line, expected points = line), its spread shrinks
  // with the square root of the time left. Full-game spread of finals around the closing line, from this
  // tracker's graded games (Nov 2026): NBA 13,6 / 18,1 (n=90), NCAAF 16,0 / 14,2 (n=124), NFL 11,3 / 12,7
  // (n=23, few games -> the usual ~13). Overtime counts in 2H bets.
  const LIVE_MODEL = {
    nfl: { quarter: 15, margin_sd: 13, total_sd: 13 },
    ncaaf: { quarter: 15, margin_sd: 16, total_sd: 14 },
    nba: { quarter: 12, margin_sd: 13.5, total_sd: 18 },
  };
  function clockMinutes(clock) {
    const text = String(clock || "").trim(), mmss = /^(\d{1,2}):(\d{2})$/.exec(text);
    if (mmss) return Number(mmss[1]) + Number(mmss[2]) / 60;
    return /^\d+(\.\d+)?$/.test(text) ? Number(text) / 60 : null;   // NBA under a minute: "45.3"
  }
  // game minutes left: the rest of this quarter plus the quarters after it; in overtime, what is left of it
  function minutesLeft(league, period, clock) {
    const model = LIVE_MODEL[league], p = finite(period), c = clockMinutes(clock);
    if (!model || p === null || c === null) return null;
    return p <= 4 ? (4 - p) * model.quarter + c : c;
  }
  const normalCdf = (z) => {   // Abramowitz-Stegun 7.1.26, |error| < 1.5e-7
    const x = Math.abs(z) / Math.SQRT2, t = 1 / (1 + 0.3275911 * x);
    const erf = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    if (z === 0) return 0.5;
    return Math.min(1, Math.max(0, z > 0 ? (1 + erf) / 2 : (1 - erf) / 2));
  };
  // play: {market, pick_side, line}; firstHalf: [away, home] at halftime; game: live score, state, situation
  function winChance(play, firstHalf, game) {
    const league = game && game.league || play && play.league, model = LIVE_MODEL[league];
    const situation = game && game.situation || {}, period = finite(situation.period);
    const line = finite(play && play.line), half = firstHalf || [];
    const away = finite(game && game.away_score), home = finite(game && game.home_score);
    const away1 = finite(half[0]), home1 = finite(half[1]);
    if (!model || line === null || [away, home, away1, home1].includes(null)) return null;
    const final = game.state === "final";
    if (!final && (period === null || period < 3)) return null;            // the second half has not started
    const away2 = away - away1, home2 = home - home1;
    if (away2 < 0 || home2 < 0) return null;
    const left = final ? 0 : minutesLeft(league, period, situation.clock);
    if (left === null) return null;
    const rest = Math.min(1, left / (2 * model.quarter)), share = Math.sqrt(left / (4 * model.quarter));
    let now, mean, sd;
    if (play.market === "spread") {
      const own = play.pick_side === "away" ? away2 - home2 : home2 - away2;
      now = own + line;                          // cover margin if the game ended now
      mean = own + line * (1 - rest);
      sd = model.margin_sd * share;
    } else {
      const sign = play.pick_side === "under" ? -1 : 1;
      now = sign * (away2 + home2 - line);
      mean = sign * (away2 + home2 - line * (1 - rest));
      sd = model.total_sd * share;
    }
    const p = sd > 0 ? normalCdf(mean / sd) : mean > 0 ? 1 : mean < 0 ? 0 : 0.5;
    return { p, now, minutes: left, away_2h: away2, home_2h: home2 };
  }

  root.ActionsSecondHalf = { isHalftime, firstHalfScore, decide, withLockedLines, minutesLeft, winChance };
})(globalThis);
