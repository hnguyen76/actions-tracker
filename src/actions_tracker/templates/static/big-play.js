/* Big-play alert for live games the owner has a play on: touchdown, field goal, missed field goal,
   interception, lost fumble. Scores come from the 5 s scoreboard poll, the other plays from the ESPN drives
   (live-scores.js, drive.big_plays). Only plays the page sees happen are announced, each one once. */
(function (root) {
  "use strict";
  const STALE_MS = 60000;  // a look older than this (tab hidden, phone asleep) starts over without alerts

  // One jump of a team's score: 6-8 is a touchdown (with or without the try), 3 a field goal; 1-2 are tries/safeties.
  const scoreKind = (before, after) => {
    const d = after - before;
    return d >= 6 && d <= 8 ? "touchdown" : d === 3 ? "field_goal" : null;
  };
  const score = (x) => (Number.isSafeInteger(Number(x)) && x !== null && x !== "" ? Number(x) : null);

  // memory: Map(game_id -> {away, home, plays: Set, at}); returns [{game_id, kind, side}] and updates memory.
  function detect(memory, games, now) {
    const events = [];
    for (const g of games || []) {
      const id = Number(g.game_id), away = score(g.away_score), home = score(g.home_score);
      const plays = g.drive && Array.isArray(g.drive.big_plays) ? g.drive.big_plays : [];
      const seen = memory.get(id);
      const fresh = seen && now - seen.at <= STALE_MS;
      if (fresh) {
        for (const [side, before, after] of [["away", seen.away, away], ["home", seen.home, home]]) {
          const kind = before !== null && after !== null ? scoreKind(before, after) : null;
          if (kind) events.push({ game_id: id, kind, side });
        }
        for (const p of plays) if (p && p.id && !seen.plays.has(p.id)) events.push({ game_id: id, kind: p.kind, side: p.side });
      }
      const known = fresh ? seen.plays : new Set();
      for (const p of plays) if (p && p.id) known.add(p.id);
      memory.set(id, { away: away ?? (seen && seen.away), home: home ?? (seen && seen.home), plays: known, at: now });
    }
    return events;
  }

  root.ActionsBigPlay = { detect };
})(typeof window !== "undefined" ? window : globalThis);
