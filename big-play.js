/* Big-play alert for live games the owner has a play on: touchdown, field goal, missed field goal,
   interception, lost fumble. Scores come from the 5 s scoreboard poll, the other plays from the ESPN drives
   (live-scores.js, drive.big_plays). Only plays the page sees happen are announced, each one once. */
(function (root) {
  "use strict";
  const STALE_MS = 60000;  // a look older than this (tab hidden, phone asleep) starts over without alerts
  const FRESH_DATA_MS = 30000;  // a card whose score is older than this (failed poll after a wake-up) is left alone
  const RED_ZONE_REPEAT_MS = 180000;  // the same team back in the red zone this soon (penalty out and in) is the same drive

  // One football score jump: 6-8 is a touchdown (with or without the try), 3 a field goal.
  // NBA score changes must never be interpreted as football plays (a three-pointer used to announce "FIELD GOAL").
  const scoreKind = (before, after, league) => {
    if (String(league || "").toLowerCase() === "nba") return null;
    const d = after - before;
    return d >= 6 && d <= 8 ? "touchdown" : d === 3 ? "field_goal" : null;
  };
  const score = (x) => (Number.isSafeInteger(Number(x)) && x !== null && x !== "" ? Number(x) : null);

  // memory: Map(game_id -> {away, home, plays: Set, red, redAlert, at}); returns [{game_id, kind, side}], updates memory.
  function detect(memory, games, now) {
    const events = [];
    for (const g of games || []) {
      const dataAt = Date.parse(g.updated_at);
      if (Number.isFinite(dataAt) && now - dataAt > FRESH_DATA_MS) continue;  // neither alert nor re-baseline on old data
      const id = Number(g.game_id), away = score(g.away_score), home = score(g.home_score);
      const plays = g.drive && Array.isArray(g.drive.big_plays) ? g.drive.big_plays : [];
      const seen = memory.get(id);
      const fresh = seen && now - seen.at <= STALE_MS;
      if (fresh) {
        for (const [side, before, after] of [["away", seen.away, away], ["home", seen.home, home]]) {
          const kind = before !== null && after !== null ? scoreKind(before, after, g.league) : null;
          if (kind) events.push({ game_id: id, kind, side });
        }
        for (const p of plays) {
          if (!p || !p.id || seen.plays.has(p.id)) continue;
          seen.plays.add(p.id);  // a play listed twice in one poll is still one alert
          events.push({ game_id: id, kind: p.kind, side: p.side });
        }
      } else if (seen) {
        // back after a gap (phone locked, another app): no replay of the plays, one line with the score change
        const up = (before, after) => (Number.isFinite(before) && after !== null && after > before ? after - before : 0);
        const dAway = up(seen.away, away), dHome = up(seen.home, home);
        if (dAway || dHome) events.push({ game_id: id, kind: "catch_up", away: dAway, home: dHome });
      }
      // red zone: only the moment a team gets in (ESPN without the flag is "unknown", not "out")
      const situation = g.situation || {};
      const red = situation.red_zone === true ? true : situation.red_zone === false ? false : null;
      let redAlert = seen ? seen.redAlert : null;
      if (fresh && red === true && seen.red !== true) {
        const side = situation.possession === "home" || situation.possession === "away" ? situation.possession : null;
        if (!(redAlert && redAlert.side === side && now - redAlert.at < RED_ZONE_REPEAT_MS)) {
          events.push({ game_id: id, kind: "red_zone", side });
          redAlert = { side, at: now };
        }
      }
      const known = fresh ? seen.plays : new Set();
      for (const p of plays) if (p && p.id) known.add(p.id);
      memory.set(id, { away: away ?? (seen && seen.away), home: home ?? (seen && seen.home), plays: known,
        red: red ?? (seen ? seen.red : null), redAlert, at: now });
    }
    return events;
  }

  // ---------- the alert: full-screen overlay, fireworks in the team colour, chime, vibration ----------
  const SHOW_MS = 4000;
  const LABEL = { touchdown: "TOUCHDOWN", field_goal: "FIELD GOAL", field_goal_missed: "FIELD GOAL MISSED",
    interception: "INTERCEPTION", fumble_lost: "FUMBLE" };
  const other = (side) => (side === "home" ? "away" : "home");
  const abbr = (card, side) => String(card[side + "_abbr"] || (side === "home" ? "Đội nhà" : "Đội khách"));
  function who(event, card) {
    const team = abbr(card, event.side), loser = abbr(card, other(event.side));
    return { interception: team + " cướp banh", fumble_lost: loser + " mất banh", field_goal_missed: loser + " đá trượt" }[event.kind] || team;
  }
  // green when the play helps the side the owner bet, red when it hurts
  const tone = (event, card) => (card.bet_side === "home" || card.bet_side === "away"
    ? (event.side === card.bet_side ? "bp-good" : "bp-bad") : "bp-neutral");
  function betLine(card) {
    const board = root.ActionsScoreboard, b = board && board.betStatus ? board.betStatus(card) : null;
    return b ? `Bạn đặt ${b.pick} · đang ${{ win: "thắng", loss: "thua", push: "hòa" }[b.state] || ""}` : "";
  }
  const el = (tag, cls, text) => {
    const n = root.document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  };

  function fireworks(canvas, color) {
    const ctx = canvas.getContext && canvas.getContext("2d"), raf = root.requestAnimationFrame;
    if (!ctx || !raf) return () => {};
    const dpr = Math.min(2, root.devicePixelRatio || 1), w = root.innerWidth || 400, h = root.innerHeight || 700;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const rgb = /^#[0-9a-f]{6}$/i.test(color) ? [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)) : [255, 211, 77];
    const team = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] < 60 ? "#ffffff" : color;  // black/navy sparks vanish on the dark backdrop
    const colors = [team, "#ffffff", "#ffd34d", team], sparks = [];
    const burst = () => {
      const x = w * (0.15 + Math.random() * 0.7), y = h * (0.12 + Math.random() * 0.38), n = 48;
      for (let i = 0; i < n; i++) {
        const a = Math.PI * 2 * i / n + Math.random() * 0.2, v = 2 + Math.random() * 3.4;
        sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 1, c: colors[i % colors.length] });
      }
    };
    let running = true, last = 0, elapsed = 0, nextBurst = 0;
    const tick = (ts) => {
      if (!running) return;
      const dt = last ? Math.min(3, (ts - last) / 16.7) : 1;
      last = ts; elapsed += dt;
      if (elapsed >= nextBurst && elapsed < 170) { burst(); nextBurst = elapsed + 20 + Math.random() * 14; }
      ctx.clearRect(0, 0, w, h);
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i];
        s.x += s.vx * dt; s.y += s.vy * dt; s.vy += 0.05 * dt; s.vx *= 0.985; s.vy *= 0.985; s.life -= 0.013 * dt;
        if (s.life <= 0) { sparks.splice(i, 1); continue; }
        ctx.globalAlpha = s.life; ctx.fillStyle = s.c;
        ctx.beginPath(); ctx.arc(s.x, s.y, 2.3, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf(tick);
    };
    raf(tick);
    return () => { running = false; };
  }

  // sound needs one tap on the page first (iPhone/Chrome autoplay rules)
  let audio = null;
  const unlock = () => {
    try {
      const AC = root.AudioContext || root.webkitAudioContext;
      if (!audio && AC) audio = new AC();
      if (audio && audio.state !== "running") {  // "suspended", or "interrupted" on iPhone after a lock or a call
        const resumed = audio.resume();
        if (resumed && resumed.catch) resumed.catch(() => {});
      }
    } catch (e) { audio = null; }
  };
  if (root.document && root.document.addEventListener) {
    for (const type of ["pointerdown", "touchend", "keydown"]) root.document.addEventListener(type, unlock, { passive: true });
  }
  function chime(good) {
    if (!audio || audio.state !== "running") return;
    const t0 = audio.currentTime;
    (good ? [784, 1047, 1319] : [523, 392]).forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain(), t = t0 + i * 0.12;
      o.type = "sine"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      o.connect(g); g.connect(audio.destination);
      o.start(t); o.stop(t + 0.4);
    });
  }
  function buzz() {
    const nav = root.navigator;  // Android; iPhone Safari has no vibration for web pages
    if (nav && typeof nav.vibrate === "function") nav.vibrate([180, 80, 180]);
  }

  const queue = [];
  let current = null;
  function show(event, card) {
    const mood = tone(event, card);
    const overlay = el("div", `bp-overlay bp-${event.kind} ${mood}`);
    overlay.setAttribute("role", "alert");
    const calm = root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let stop = () => {};
    if (!calm) {
      const canvas = el("canvas", "bp-fx");
      overlay.append(canvas);
      const situation = card.situation || {};
      stop = fireworks(canvas, situation[event.side + "_color"] || "#ffd34d");
    }
    const box = el("div", "bp-card");
    box.append(el("div", "bp-kind", LABEL[event.kind] || event.kind), el("div", "bp-team", who(event, card)),
      el("div", "bp-score", `${abbr(card, "away")} ${card.away_score} – ${card.home_score} ${abbr(card, "home")}`));
    const bet = betLine(card);
    if (bet) box.append(el("div", "bp-bet", bet));
    box.append(el("div", "bp-hint", "Chạm để tắt"));
    overlay.append(box);
    let timer = null;
    const close = () => {
      if (current !== overlay) return;
      stop(); root.clearTimeout(timer); overlay.remove(); current = null; next();
    };
    overlay.addEventListener("click", close);
    root.document.body.append(overlay);
    current = overlay;
    timer = root.setTimeout(close, SHOW_MS);
    chime(mood !== "bp-bad");
    buzz();
  }
  function next() {
    if (current || !queue.length) return;
    const [event, card] = queue.shift();
    show(event, card);
  }
  // queue one alert (also handy to preview the look from the console)
  function announce(event, card) { queue.push([event, card]); next(); }

  // red zone: one small line at the top for 3 s (no sound, no vibration, never blocks the page)
  const TOAST_MS = 3000, CATCH_UP_MS = 6000;
  // small top lines (red zone, catch-up) stack in one tray instead of covering each other
  let tray = null;
  const topLine = (cls, ms, previous) => {
    if (!tray || !tray.parentNode) { tray = el("div", "bp-tray"); root.document.body.append(tray); }
    if (previous) previous.remove();
    const node = el("div", cls);
    node.setAttribute("role", "status");
    tray.append(node);
    root.setTimeout(() => node.remove(), ms);
    return node;
  };
  let toastNode = null;
  function toast(event, card) {
    const situation = card.situation || {};
    const parts = [event.side ? abbr(card, event.side) : null, situation.down_distance, situation.possession_text].filter(Boolean);
    toastNode = topLine("bp-toast", TOAST_MS, toastNode);
    toastNode.append(el("b", "", "RED ZONE"), el("span", "", parts.length ? " · " + parts.join(" · ") : ""));
  }
  // "TD  PIT 11 – 31 CIN": the new score after a gap, the changed number flashing (green helps the bet, red hurts it)
  let catchNode = null;
  function catchUp(items) {
    if (!items.length) return;
    catchNode = topLine("bp-toast bp-catchup", CATCH_UP_MS, catchNode);
    for (const [event, card] of items) {
      const line = el("div", "bp-line");
      const one = event.away && !event.home ? event.away : event.home && !event.away ? event.home : 0;
      const tag = String(card.league || "").toLowerCase() === "nba" ? ""
        : one >= 6 && one <= 8 ? "TD" : one === 3 ? "FG" : "";
      if (tag) line.append(el("b", "bp-tag", tag));
      const num = (side) => {
        if (!event[side]) return el("span", "bp-num", String(card[side + "_score"]));
        const tone = card.bet_side === side ? " bp-up-good" : card.bet_side === "home" || card.bet_side === "away" ? " bp-up-bad" : "";
        return el("span", "bp-num bp-flash" + tone, String(card[side + "_score"]));
      };
      line.append(el("span", "", abbr(card, "away") + " "), num("away"), el("span", "", " – "), num("home"), el("span", "", " " + abbr(card, "home")));
      catchNode.append(line);
    }
  }

  // cards: the merged live cards of the games on the "Đang đá" card, after each live poll
  const memory = new Map();
  function observe(cards) {
    try {
      const byId = new Map((cards || []).map((c) => [Number(c.game_id), c]));
      const missed = [];
      for (const event of detect(memory, cards, Date.now())) {
        const card = byId.get(event.game_id);
        if (!card) continue;
        if (event.kind === "red_zone") toast(event, card);
        else if (event.kind === "catch_up") missed.push([event, card]);
        else announce(event, card);
      }
      catchUp(missed);
    } catch (error) { /* an alert must never break or slow the live score polling */ }
  }

  root.ActionsBigPlay = { detect, observe, announce, toast };
})(typeof window !== "undefined" ? window : globalThis);
