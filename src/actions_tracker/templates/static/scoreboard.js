(function () {
  "use strict";

  const text = (value) => typeof value === "string" && value.trim() ? value.trim() : null;
  const integer = (value) => {
    if (typeof value !== "number" && (typeof value !== "string" || !/^\d+(?:\.0+)?$/.test(value.trim()))) return null;
    const n = Number(value);
    return Number.isSafeInteger(n) && n >= 0 ? n : null;
  };
  const teamId = (competitor) => {
    const value = competitor && ((competitor.team || {}).id ?? competitor.id);
    return value === null || value === undefined || typeof value === "boolean" || !/^\d+$/.test(String(value)) ? null : String(value);
  };
  const periodScores = (competitor) => {
    const scores = [];
    for (const row of competitor && Array.isArray(competitor.linescores) ? competitor.linescores : []) {
      if (!row || typeof row !== "object") continue;
      const period = integer(row.period), value = integer(row.value);
      if (period === null || period < 1 || period > 20 || value === null) continue;
      while (scores.length < period) scores.push(null);
      scores[period - 1] = value;
    }
    return scores.length ? scores : null;
  };

  function parseSituation(event) {
    const comp = event && Array.isArray(event.competitions) ? event.competitions[0] || {} : {};
    const competitors = Array.isArray(comp.competitors) ? comp.competitors.filter((c) => c && typeof c === "object") : [];
    const away = competitors.find((c) => c.homeAway === "away"), home = competitors.find((c) => c.homeAway === "home");
    const awayId = teamId(away), homeId = teamId(home);
    const raw = comp.situation && typeof comp.situation === "object" ? comp.situation : {};
    const possessionId = integer(raw.possession) === null ? null : String(raw.possession);
    const status = comp.status && typeof comp.status === "object" ? comp.status : event && event.status || {};
    const period = integer(status.period);
    const result = {
      possession: possessionId && awayId !== homeId ? (possessionId === awayId ? "away" : possessionId === homeId ? "home" : null) : null,
      possession_text: text(raw.possessionText),
      down_distance: text(raw.shortDownDistanceText) || text(raw.downDistanceText),
      red_zone: typeof raw.isRedZone === "boolean" ? raw.isRedZone : null,
      period: period !== null && period > 0 && period <= 20 ? period : null,
      clock: text(status.displayClock),
      away_period_scores: periodScores(away),
      home_period_scores: periodScores(home),
      away_espn_id: awayId,
      home_espn_id: homeId,
    };
    return [result.possession, result.possession_text, result.down_distance, result.red_zone, result.period, result.clock, result.away_period_scores, result.home_period_scores]
      .some((value) => value !== null) ? result : null;
  }

  const node = (tag, className, content) => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (content !== null && content !== undefined) result.textContent = String(content);
    return result;
  };
  const league = (game) => String(game.league || "").toUpperCase();
  const abbreviation = (game, side) => text(game[side + "_abbr"]) || text(game[side + "_name"]) || (side === "away" ? "Đội khách" : "Đội nhà");
  const periodName = (period) => period <= 4 ? String(period) : period === 5 ? "OT" : "OT" + (period - 4);

  function quarterTable(game, situation) {
    const away = Array.isArray(situation.away_period_scores) ? situation.away_period_scores : [];
    const home = Array.isArray(situation.home_period_scores) ? situation.home_period_scores : [];
    const available = Math.max(away.length, home.length);
    if (!available) return null;
    const periods = Math.min(20, Math.max(4, available));
    const scroll = node("div", "asb-quarters");
    const table = node("table", "asb-quarter-table");
    table.setAttribute("aria-label", "Điểm từng hiệp " + abbreviation(game, "away") + " và " + abbreviation(game, "home"));
    const head = node("tr");
    head.append(node("th", "", ""));
    for (let i = 1; i <= periods; i++) head.append(node("th", "", periodName(i)));
    head.append(node("th", "asb-total", "T"));
    const thead = node("thead"), tbody = node("tbody");
    thead.append(head);
    for (const [side, values] of [["away", away], ["home", home]]) {
      const row = node("tr"), name = node("th", "", abbreviation(game, side));
      name.scope = "row";
      row.append(name);
      for (let i = 0; i < periods; i++) row.append(node("td", "", integer(values[i]) === null ? "–" : values[i]));
      row.append(node("td", "asb-total", integer(game[side + "_score"]) === null ? "–" : game[side + "_score"]));
      tbody.append(row);
    }
    table.append(thead, tbody);
    scroll.append(table);
    return scroll;
  }

  function scorecard(game) {
    const situation = game.situation && typeof game.situation === "object" ? game.situation : {};
    const final = game.state === "final", live = game.state === "live";
    const card = node("article", "asb-card");
    card.dataset.gameId = String(game.game_id);
    card.setAttribute("aria-label", league(game) + " " + abbreviation(game, "away") + " tại " + abbreviation(game, "home"));
    const meta = node("div", "asb-meta");
    meta.append(node("span", "asb-league", league(game)));
    let clock = text(game.detail) || (live ? "Đang đá" : "Chờ kết quả");
    if (final) clock = game.graded ? "Hết trận" : "Hết trận · chờ chấm";
    else if (live && text(situation.clock) && integer(situation.period) !== null && situation.period > 0
      && (!text(game.detail) || String(game.detail).includes(situation.clock))) {
      clock = situation.clock + " · " + (situation.period > 4 ? periodName(situation.period) : "Hiệp " + situation.period);
    }
    const clockNode = node("strong", "asb-clock", clock);
    meta.append(clockNode);
    const stamp = new Date(game.updated_at);
    const checked = game.updated_at && Number.isFinite(stamp.getTime())
      ? "ESPN · " + stamp.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "ESPN";
    meta.append(node("span", "asb-updated", checked));
    card.append(meta);
    const main = node("div", "asb-main");
    for (const side of ["away", "home"]) {
      const section = node("div", "asb-team asb-" + side);
      const identity = node("div", "asb-identity");
      const name = text(game[side + "_name"]) || abbreviation(game, side);
      const title = node("div", "asb-name", name);
      const possesses = live && situation.possession === side;
      if (possesses) {
        const dot = node("span", "asb-possession");
        dot.setAttribute("role", "img");
        dot.setAttribute("aria-label", name + " đang cầm bóng");
        dot.title = name + " đang cầm bóng";
        title.append(dot);
      }
      identity.append(title, node("span", "asb-abbr", abbreviation(game, side)));
      const score = integer(game[side + "_score"]);
      section.append(identity, node("strong", "asb-score", score === null ? "–" : score));
      main.append(section);
      if (side === "away") {
        const quarters = quarterTable(game, situation);
        if (quarters) main.append(quarters);
        else main.append(node("div", "asb-quarters asb-quarters-empty"));
      }
    }
    card.append(main);
    if (live) {
      const items = [];
      if (situation.possession === "away" || situation.possession === "home") items.push(abbreviation(game, situation.possession) + " đang cầm bóng");
      const down = text(situation.down_distance), spot = text(situation.possession_text);
      if (down) items.push(down);
      if (spot && (!down || !down.includes(spot))) items.push("Bóng tại " + spot);
      if (situation.red_zone === true) items.push("Red zone");
      if (items.length) {
        const status = node("div", "asb-situation" + (situation.red_zone === true ? " asb-red-zone" : ""), items.join(" · "));
        card.append(status);
      }
    }
    return card;
  }

  function render(host, games) {
    if (!host || typeof host.replaceChildren !== "function") return;
    const seen = new Set(), cards = [];
    for (const game of Array.isArray(games) ? games : []) {
      if (!game || seen.has(String(game.game_id))) continue;
      seen.add(String(game.game_id));
      cards.push(scorecard(game));
    }
    host.classList.add("asb-list");
    host.replaceChildren(...cards);
    host.hidden = !cards.length;
  }

  window.ActionsScoreboard = { parseSituation, render };
})();
