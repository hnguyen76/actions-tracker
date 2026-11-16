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
  const teamColor = (competitor) => {
    const value = competitor && competitor.team && competitor.team.color;
    return typeof value === "string" && /^[0-9a-f]{6}$/i.test(value) ? "#" + value.toLowerCase() : null;
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
      away_color: teamColor(away),
      home_color: teamColor(home),
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
  // next to the game clock: 1st 2nd 3rd 4th, then OT, OT2 ...
  const periodLabel = (period) => period > 4 ? periodName(period) : ["1st", "2nd", "3rd", "4th"][period - 1];
  const halftimeLabel = (end, now = Date.now()) => {
    const remaining = Math.ceil((end - now) / 1000);
    return remaining > 0 ? "Halftime · ước tính " + String(Math.floor(remaining / 60)).padStart(2, "0") + ":" + String(remaining % 60).padStart(2, "0")
      : "Halftime · chờ 3rd";
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

  // Perspective field drawn in a 1200 x 100 box: 120 yards including both end zones, the far (top) edge 92.5% as wide
  // as the near (bottom) edge, so yard lines fan out from the 50. The ball and the drive bar sit at mid height.
  const SVG_NS = "http://www.w3.org/2000/svg";
  const FIELD_W = 1200, FIELD_TOP = 4, FIELD_NEAR = 82, FIELD_BASE = 94, FAR_INSET = 45;
  const fieldUnits = (yard) => Math.max(0, Math.min(120, yard + 10));
  const nearX = (yard) => fieldUnits(yard) * 10;
  const farX = (yard) => FAR_INSET + fieldUnits(yard) * (FIELD_W - 2 * FAR_INSET) / 120;
  // the left side edge at height y (the right one mirrors it), for the rounded corners
  const sideX = (y) => +(FAR_INSET * (FIELD_NEAR - y) / (FIELD_NEAR - FIELD_TOP)).toFixed(2);
  const midX = (yard) => (nearX(yard) + farX(yard)) / 2;
  const fieldPct = (x) => (x / FIELD_W * 100).toFixed(2) + "%";
  const svgNode = (tag, cls, attrs) => {
    const result = document.createElementNS(SVG_NS, tag);
    if (cls) result.classList.add(...cls.split(" "));
    for (const [k, v] of Object.entries(attrs || {})) result.setAttribute(k, String(v));
    return result;
  };
  const validYard = (x) => typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 100;
  function fieldSvg(drive) {
    const svg = svgNode("svg", "asb-turf-svg", { viewBox: `0 0 ${FIELD_W} 100`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" });
    const T = FIELD_TOP, N = FIELD_NEAR, B = FIELD_BASE, W = FIELD_W, I = FAR_INSET, r = 12;
    const a = sideX(T + 10), b = sideX(N - 10);  // where the rounded corners meet the slanted side edges
    const left = `M${I + r} ${T}`, leftSide = `H${r}Q0 ${N} ${b} ${N - 10}L${a} ${T + 10}Q${I} ${T} ${I + r} ${T}Z`;
    const rightSide = `H${W - I - r}Q${W - I} ${T} ${W - a} ${T + 10}L${W - b} ${N - 10}Q${W} ${N} ${W - r} ${N}`;
    svg.append(
      svgNode("path", "asb-turf-base", { d: `M0 ${N}H${W}V${B - 6}Q${W} ${B} ${W - r} ${B}H${r}Q0 ${B} 0 ${B - 6}Z` }),
      svgNode("path", "asb-ez-base", { d: `M0 ${N}H${nearX(0)}V${B}H${r}Q0 ${B} 0 ${B - 6}Z` }),
      svgNode("path", "asb-ez-base", { d: `M${nearX(100)} ${N}H${W}V${B - 6}Q${W} ${B} ${W - r} ${B}H${nearX(100)}Z` }),
      svgNode("path", "asb-turf-surface", { d: `${left}${rightSide}${leftSide}` }),
      svgNode("path", "asb-ez", { d: `${left}H${farX(0)}L${nearX(0)} ${N}${leftSide}` }),
      svgNode("path", "asb-ez", { d: `M${farX(100)} ${T}${rightSide}H${nearX(100)}Z` }));
    for (let yard = 10; yard <= 90; yard += 10) {
      svg.append(svgNode("line", "asb-yardline" + (yard === 50 ? " asb-yardline-mid" : ""),
        { x1: farX(yard), y1: T, x2: nearX(yard), y2: N }));
    }
    if (validYard(drive.first_down_x) && drive.distance > 0) {
      const first = svgNode("line", "asb-first-down", { x1: +farX(drive.first_down_x).toFixed(2), y1: T,
        x2: +nearX(drive.first_down_x).toFixed(2), y2: N });
      const title = svgNode("title");
      title.textContent = "Vạch first down";
      first.append(title);
      svg.append(first);
    }
    return svg;
  }
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
    facts.append(node("strong", "", [down, spot].filter(Boolean).join(" · ") || "Đang cập nhật vị trí bóng"));

    const field = node("div", "asb-field");
    const situation = game.situation && typeof game.situation === "object" ? game.situation : {};
    const awayColor = teamColor({ team: { color: String(situation.away_color || "").replace(/^#/, "") } }) || "#164b91";
    const homeColor = teamColor({ team: { color: String(situation.home_color || "").replace(/^#/, "") } }) || "#8d2638";
    const offenseColor = drive.team_side === "away" ? awayColor : homeColor;
    field.setAttribute("style", `--asb-away-color:${awayColor};--asb-home-color:${homeColor};--asb-offense-color:${offenseColor}`);
    field.setAttribute("role", "img");
    field.setAttribute("aria-label", [drive.team_abbr && drive.team_abbr + " cầm bóng", down, spot && "bóng tại " + spot].filter(Boolean).join(", "));
    const pitch = node("div", "asb-pitch");
    const turf = node("div", "asb-turf");
    turf.append(fieldSvg(drive));
    const ball = midX(drive.ball_x);
    if (validYard(drive.start_x)) {  // the drive so far: from where it began to the ball
      const start = midX(drive.start_x);
      const progress = node("span", "asb-drive-progress");
      progress.setAttribute("style", `left:${fieldPct(Math.min(start, ball))};width:${fieldPct(Math.abs(start - ball))}`);
      turf.append(progress);
    }
    const marker = node("span", "asb-ball-marker");
    marker.setAttribute("style", "left:" + fieldPct(ball));
    marker.setAttribute("title", `${text(drive.team_abbr) || abbreviation(game, drive.team_side)} · ${spot || "vị trí bóng"}`);
    marker.append(node("span", "asb-football-icon"));
    turf.append(marker);
    const numbers = node("div", "asb-yard-numbers");
    for (let yard = 10; yard <= 90; yard += 10) {
      const label = node("span", "asb-yard-number", String(yard <= 50 ? yard : 100 - yard));
      label.setAttribute("style", "left:" + fieldPct(nearX(yard)));
      numbers.append(label);
    }
    pitch.append(turf, numbers);
    field.append(facts, pitch);
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

  // "Bạn đặt" strip: the bet against the live score - spread margin after the line, or total vs the line
  function betStatus(game) {
    const side = text(game.bet_side), market = text(game.market) || "spread";
    if (game.line === null || game.line === undefined || game.line === "") return null;
    const line = Number(game.line);
    const away = integer(game.away_score), home = integer(game.home_score);
    if (!side || !Number.isFinite(line) || away === null || home === null) return null;
    const fmt = (x) => (x > 0 ? "+" : "") + String(x).replace(".", ",");
    if (market === "spread" && (side === "home" || side === "away")) {
      const mine = side === "home" ? home : away, theirs = side === "home" ? away : home;
      const margin = mine + line - theirs;
      const me = abbreviation(game, side), them = abbreviation(game, side === "home" ? "away" : "home");
      return {
        state: margin > 0 ? "win" : margin < 0 ? "loss" : "push",
        pick: me + " " + fmt(line),
        detail: "ATS: " + me + " " + mine + " " + (line < 0 ? "− " + String(-line).replace(".", ",") : "+ " + String(line).replace(".", ","))
          + " = " + String(mine + line).replace(".", ",") + " vs " + them + " " + theirs
          + (margin === 0 ? " → hòa" : " → " + (margin > 0 ? "hơn " : "kém ") + String(Math.abs(margin)).replace(".", ",") + " điểm"),
      };
    }
    if (market === "total" && (side === "over" || side === "under")) {
      const total = away + home, margin = (total - line) * (side === "over" ? 1 : -1);
      return {
        state: margin > 0 ? "win" : margin < 0 ? "loss" : "push",
        pick: (side === "over" ? "Over " : "Under ") + String(line).replace(".", ","),
        detail: "Tổng " + total + " vs line " + String(line).replace(".", ",")
          + (margin === 0 ? " → hòa" : " → " + (side === "over" ? (total > line ? "đã vượt " : "còn thiếu ") : (total < line ? "còn dư " : "đã vượt "))
            + String(Math.abs(total - line)).replace(".", ",") + " điểm"),
      };
    }
    return null;
  }

  function betStrip(game) {
    const b = betStatus(game);
    if (!b) return null;
    const label = { win: "ĐANG THẮNG", loss: "ĐANG THUA", push: "ĐANG HÒA" }[b.state];
    const strip = node("div", "asb-bet asb-bet-" + b.state);
    strip.append(node("span", "asb-bet-pick", "Bạn đặt " + b.pick), node("span", "asb-bet-ats", b.detail),
      node("strong", "asb-bet-state", game.state === "final" ? { win: "THẮNG", loss: "THUA", push: "HÒA" }[b.state] : label));
    return strip;
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
      clock = situation.clock + " · " + periodLabel(situation.period);
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
    const bet = betStrip(game);
    if (bet) card.append(bet);
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

  const hasClass = (element, name) => element && String(element.className || "").split(/\s+/).includes(name);
  const directChild = (parent, name) => [...(parent && parent.children || [])].find((child) => hasClass(child, name)) || null;
  const removeNode = (element) => {
    if (!element) return;
    if (typeof element.remove === "function") { element.remove(); return; }
    const parent = element.parentNode, index = parent && parent.children ? parent.children.indexOf(element) : -1;
    if (index >= 0) parent.children.splice(index, 1);
    element.parentNode = null;
  };
  const insertNode = (parent, element, before) => {
    if (typeof parent.insertBefore === "function") { parent.insertBefore(element, before || null); return; }
    if (element.parentNode && element.parentNode.children) {
      const old = element.parentNode.children.indexOf(element);
      if (old >= 0) element.parentNode.children.splice(old, 1);
    }
    const index = before ? parent.children.indexOf(before) : -1;
    parent.children.splice(index >= 0 ? index : parent.children.length, 0, element);
    element.parentNode = parent;
  };
  const replaceNode = (current, replacement) => {
    if (typeof current.replaceWith === "function") { current.replaceWith(replacement); return; }
    const parent = current.parentNode, index = parent && parent.children ? parent.children.indexOf(current) : -1;
    if (index < 0) return;
    parent.children[index] = replacement;
    replacement.parentNode = parent;
    current.parentNode = null;
  };
  const sameNode = (a, b) => typeof a.isEqualNode === "function" ? a.isEqualNode(b)
    : a.className === b.className && a.textContent === b.textContent
      && JSON.stringify(a.attributes || {}) === JSON.stringify(b.attributes || {});
  function patchBlock(parent, freshParent, name, order, preserveName = null) {
    const current = directChild(parent, name), next = directChild(freshParent, name);
    if (!next) { removeNode(current); return null; }
    if (current) {
      if (!sameNode(current, next)) { replaceNode(current, next); return next; }
      return current;
    }
    const after = order.slice(order.indexOf(name) + 1).map((key) => directChild(parent, key)).find(Boolean);
    insertNode(parent, next, after || (preserveName && directChild(parent, preserveName)) || null);
    return next;
  }
  function patchScorecard(current, fresh) {
    current.className = fresh.className;
    current.dataset.gameId = fresh.dataset.gameId;
    const label = typeof fresh.getAttribute === "function" ? fresh.getAttribute("aria-label") : fresh.attributes["aria-label"];
    if (label) current.setAttribute("aria-label", label);
    const order = ["asb-meta", "asb-main", "asb-bet", "asb-situation", "asb-drive"];
    patchBlock(current, fresh, "asb-meta", order, "live-card-pregame");
    let main = directChild(current, "asb-main"), freshMain = directChild(fresh, "asb-main");
    if (!main || !freshMain) main = patchBlock(current, fresh, "asb-main", order, "live-card-pregame");
    else for (const name of ["asb-away", "asb-quarters", "asb-home"])
      patchBlock(main, freshMain, name, ["asb-away", "asb-quarters", "asb-home"]);
    for (const name of ["asb-bet", "asb-situation", "asb-drive"])
      patchBlock(current, fresh, name, order, "live-card-pregame");
    return current;
  }

  function render(host, games) {
    if (!host || typeof host.replaceChildren !== "function") return;
    const existing = new Map([...(host.children || [])].filter((card) => hasClass(card, "asb-card"))
      .map((card) => [String(card.dataset.gameId), card]));
    const seen = new Set(), cards = [];
    for (const game of Array.isArray(games) ? games : []) {
      const key = game && String(game.game_id);
      if (!game || seen.has(key)) continue;
      seen.add(key);
      const fresh = scorecard(game), current = existing.get(key);
      cards.push(current ? patchScorecard(current, fresh) : fresh);
    }
    for (const [key, card] of existing) if (!seen.has(key)) removeNode(card);
    host.classList.add("asb-list");
    const currentOrder = [...(host.children || [])].filter((card) => hasClass(card, "asb-card"));
    if (currentOrder.length !== cards.length || currentOrder.some((card, i) => card !== cards[i])) {
      for (const card of cards) insertNode(host, card, null);
    }
    host.hidden = !cards.length;
    updateHalftimeClocks();
  }

  window.ActionsScoreboard = { parseSituation, render, betStatus };
})();
