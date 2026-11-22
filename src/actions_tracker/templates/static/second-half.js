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

  // User rule: take the team trailing at halftime with its ESPN 2H spread. When the actual first-half
  // points are below ESPN's pregame 1H total, take Over at ESPN's current 2H total.
  function decide(game) {
    if (!isHalftime(game)) return null;
    const awayScore = finite(game.away_score), homeScore = finite(game.home_score);
    const odds = game.second_half && typeof game.second_half === "object" ? game.second_half : {};
    if (awayScore === null || homeScore === null) return null;
    const firstPoints = awayScore + homeScore;
    const firstTotal = finite(odds.first_total), secondTotal = finite(odds.total);
    let spread = null;
    if (awayScore !== homeScore) {
      const side = awayScore < homeScore ? "away" : "home";
      const line = finite(odds[side]);
      if (line !== null) spread = { side, line };
    }
    const firstResult = firstTotal === null ? "missing" : firstPoints < firstTotal ? "under"
      : firstPoints > firstTotal ? "over" : "push";
    const total = firstResult === "under" && secondTotal !== null ? { side: "over", line: secondTotal } : null;
    return { spread, total, first_points: firstPoints, first_total: firstTotal, first_result: firstResult,
      implied: odds.implied === true };
  }

  root.ActionsSecondHalf = { isHalftime, decide };
})(globalThis);
