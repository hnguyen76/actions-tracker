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

  // User rule: grade the first half against ESPN's actual 1H spread/total, then take the opposite result
  // with ESPN's 2H line. A raw scoreboard deficit alone never decides the spread play.
  function decide(game) {
    if (!isHalftime(game)) return null;
    const awayScore = finite(game.away_score), homeScore = finite(game.home_score);
    const odds = game.second_half && typeof game.second_half === "object" ? game.second_half : {};
    if (awayScore === null || homeScore === null) return null;
    const firstPoints = awayScore + homeScore;
    const firstTotal = finite(odds.first_total), secondTotal = finite(odds.total);
    const firstAway = finite(odds.first_away), firstHome = finite(odds.first_home);
    let spread = null, firstSpreadResult = "missing";
    if (firstAway !== null && firstHome !== null) {
      const awayMargin = awayScore - homeScore + firstAway;
      firstSpreadResult = awayMargin === 0 ? "push" : awayMargin < 0 ? "away_loss" : "home_loss";
      if (awayMargin !== 0) {
        const side = awayMargin < 0 ? "away" : "home", line = finite(odds[side]);
        if (line !== null) spread = { side, line, first_line: side === "away" ? firstAway : firstHome };
      }
    }
    const firstResult = firstTotal === null ? "missing" : firstPoints < firstTotal ? "under"
      : firstPoints > firstTotal ? "over" : "push";
    const total = ["under", "over"].includes(firstResult) && secondTotal !== null
      ? { side: firstResult === "under" ? "over" : "under", line: secondTotal } : null;
    return { spread, total, first_points: firstPoints, first_total: firstTotal, first_result: firstResult,
      first_spread_result: firstSpreadResult, implied: odds.implied === true };
  }

  root.ActionsSecondHalf = { isHalftime, decide };
})(globalThis);
