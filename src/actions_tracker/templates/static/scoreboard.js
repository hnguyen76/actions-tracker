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
    const statusType = status.type && typeof status.type === "object" ? status.type : {};
    const period = integer(status.period);
    const result = {
      is_halftime: statusType.name === "STATUS_HALFTIME" || /\bhalftime\b/i.test([statusType.detail, statusType.shortDetail, statusType.description].filter(Boolean).join(" ")),
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
    return result.is_halftime || [result.possession, result.possession_text, result.down_distance, result.red_zone, result.period, result.clock, result.away_period_scores, result.home_period_scores]
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
  const halftimeLabel = (end, now = Date.now()) => {
    const remaining = Math.ceil((end - now) / 1000);
    return remaining > 0 ? "Halftime · ước tính " + String(Math.floor(remaining / 60)).padStart(2, "0") + ":" + String(remaining % 60).padStart(2, "0")
      : "Halftime · chờ hiệp 3";
  };
  let halftimeTicker = null;
  function updateHalftimeClocks() {
    if (typeof document === "undefined") return;
    let active = false;
    if (!document.hidden) for (const clock of document.querySelectorAll(".asb-halftime[data-halftime-ends-at]")) {
      if (!clock.isConnected || !clock.getClientRects().length) continue;
      const end = Date.parse(clock.dataset.halftimeEndsAt);
      if (!Number.isFinite(end)) continue;
      clock.textContent = halftimeLabel(end);
      if (end > Date.now()) active = true;
    }
    if (active && halftimeTicker === null) halftimeTicker = setInterval(updateHalftimeClocks, 1000);
    if (!active && halftimeTicker !== null) { clearInterval(halftimeTicker); halftimeTicker = null; }
  }
  if (typeof document !== "undefined") document.addEventListener("visibilitychange", updateHalftimeClocks);

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

  const fieldPercent = (yard) => (8 + yard * .84).toFixed(2) + "%";
  function driveField(game) {
    const drive = game.drive && typeof game.drive === "object" ? game.drive : null;
    if (!drive || !["NFL", "NCAAF"].includes(league(game)) || !["away", "home"].includes(drive.team_side)
      || typeof drive.ball_x !== "number" || !Number.isFinite(drive.ball_x) || drive.ball_x < 0 || drive.ball_x > 100) return null;
    const section = node("section", "asb-drive");
    section.setAttribute("aria-label", "Đợt tấn công hiện tại");
    const head = node("div", "asb-drive-head");
    const identity = node("div", "asb-drive-team");
    if (typeof drive.team_logo === "string" && /^https:\/\/[^/]*\.espncdn\.com\//i.test(drive.team_logo)) {
      const logo = node("img", "asb-drive-logo");
      logo.setAttribute("src", drive.team_logo);
      logo.setAttribute("alt", "");
      logo.setAttribute("loading", "lazy");
      identity.append(logo);
    }
    identity.append(node("strong", "", "ĐỢT TẤN CÔNG HIỆN TẠI"));
    head.append(identity, node("span", "asb-drive-summary", text(drive.description) || ""));
    section.append(head);

    const facts = node("div", "asb-drive-facts");
    const down = text(drive.down_distance), spot = text(drive.spot);
    if (down) facts.append(node("strong", "", down));
    if (spot) facts.append(node("span", "", "Bóng tại " + spot));
    section.append(facts);

    const field = node("div", "asb-field");
    field.setAttribute("role", "img");
    field.setAttribute("aria-label", [drive.team_abbr && drive.team_abbr + " cầm bóng", down, spot && "bóng tại " + spot].filter(Boolean).join(", "));
    const turf = node("div", "asb-turf");
    turf.append(node("span", "asb-endzone asb-endzone-away", abbreviation(game, "away")));
    turf.append(node("span", "asb-endzone asb-endzone-home", abbreviation(game, "home")));
    const labels = [10, 20, 30, 40, 50, 60, 70, 80, 90];
    for (const yard of labels) {
      const line = node("span", "asb-yardline", yard === 50 ? "50" : String(yard <= 50 ? yard : 100 - yard));
      line.setAttribute("style", "left:" + fieldPercent(yard));
      turf.append(line);
    }
    const scrimmage = node("span", "asb-scrimmage");
    scrimmage.setAttribute("style", "left:" + fieldPercent(drive.ball_x));
    turf.append(scrimmage);
    if (typeof drive.first_down_x === "number" && Number.isFinite(drive.first_down_x)
      && drive.first_down_x >= 0 && drive.first_down_x <= 100 && drive.distance > 0) {
      const first = node("span", "asb-first-down");
      first.setAttribute("style", "left:" + fieldPercent(drive.first_down_x));
      first.setAttribute("title", "Vạch first down");
      turf.append(first);
    }
    const marker = node("span", "asb-ball-marker");
    marker.setAttribute("style", "left:" + fieldPercent(drive.ball_x));
    marker.append(node("b", "", text(drive.team_abbr) || abbreviation(game, drive.team_side)));
    if (typeof drive.play_yards === "number" && Number.isFinite(drive.play_yards)) {
      marker.append(node("small", "", (drive.play_yards > 0 ? "+" : "") + drive.play_yards + " yd"));
    }
    turf.append(marker);
    field.append(turf);
    section.append(field);

    const play = text(drive.last_play);
    if (play) {
      const last = node("div", "asb-last-play");
      const label = [text(drive.play_clock), text(drive.play_type)].filter(Boolean).join(" · ");
      if (label) last.append(node("strong", "", label));
      last.append(node("span", "", play));
      section.append(last);
    }
    return section;
  }

  function scorecard(game) {
    const situation = game.situation && typeof game.situation === "object" ? game.situation : {};
    const final = game.state === "final", live = game.state === "live";
    const period = integer(situation.period);
    const halftime = live && (period === null || period < 3) && (situation.is_halftime === true || /\bhalftime\b|STATUS_HALFTIME/i.test(String(game.detail || "")));
    const card = node("article", "asb-card");
    card.dataset.gameId = String(game.game_id);
    card.setAttribute("aria-label", league(game) + " " + abbreviation(game, "away") + " tại " + abbreviation(game, "home"));
    const meta = node("div", "asb-meta");
    meta.append(node("span", "asb-league", league(game)));
    let clock = text(game.detail) || (live ? "Đang đá" : "Chờ kết quả");
    if (final) clock = game.graded ? "Hết trận" : "Hết trận · chờ chấm";
    else if (live && text(situation.clock) && integer(situation.period) !== null && situation.period > 0
      && (!text(game.detail) || String(game.detail).includes(situation.clock)
        || situation.period >= 3 && /\bhalftime\b|STATUS_HALFTIME/i.test(String(game.detail)))) {
      clock = situation.clock + " · " + (situation.period > 4 ? periodName(situation.period) : "Hiệp " + situation.period);
    }
    const clockNode = node("strong", "asb-clock", clock);
    const halftimeEnd = text(situation.halftime_ends_at);
    if (halftime && halftimeEnd && Number.isFinite(Date.parse(halftimeEnd))) {
      clockNode.classList.add("asb-halftime");
      clockNode.dataset.halftimeEndsAt = halftimeEnd;
      clockNode.setAttribute("aria-live", "off");
      clockNode.textContent = halftimeLabel(Date.parse(halftimeEnd));
    }
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
      const possesses = live && !halftime && situation.possession === side;
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
    if (live && !halftime) {
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
      const drive = driveField(game);
      if (drive) card.append(drive);
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
    updateHalftimeClocks();
  }

  window.ActionsScoreboard = { parseSituation, render };
})();
