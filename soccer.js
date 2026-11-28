/* Soccer tab helpers: sportsbook formatting of DraftKings prices and lines (via ESPN), line history text in US/Eastern
   time, and the board's order (kickoff or signal rank) and competition filter. The board itself is built in
   soccer.py (Soccer_Board): lines now and at open, every move the phone saw, and market-move signals ranked. */
(function (root) {
  "use strict";
  const MINUS = "−";
  const SHORT = { "eng.1": "EPL", "uefa.champions": "UCL", "uefa.europa": "UEL", "esp.1": "La Liga", "ita.1": "Serie A",
    "ger.1": "Bundesliga", "fra.1": "Ligue 1", "usa.1": "MLS" };
  const ORDER = ["eng.1", "esp.1", "usa.1"];
  const finite = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
  const comma = (v) => String(Math.abs(v)).replace(".", ",");

  function price(v) {
    const n = finite(v);
    return n === null ? "–" : (n < 0 ? MINUS : "+") + Math.abs(n);
  }
  // spread lines carry a sign; totals do not (signed = false)
  function line(v, signed = true) {
    const n = finite(v);
    if (n === null) return "–";
    if (!signed || n === 0) return comma(n);
    return (n < 0 ? MINUS : "+") + comma(n);
  }
  // points of no-vig probability since the open: a move of a point or more is shown
  function tone(delta) {
    const n = finite(delta);
    return n === null ? "" : n >= 1 ? "up" : n <= -1 ? "down" : "";
  }
  const etParts = (iso) => Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  // [["open", v], [iso, v], ...] -> "Mở −165 · 12:30 −210 · 26/11 17:00 −230"; v is a price, or [line, price]
  // for spread (signed) and total (signed = false)
  function history(seq, todayYmd, signed) {
    const value = (v) => Array.isArray(v) ? `${line(v[0], signed !== false)} ${price(v[1])}` : price(v);
    return (seq || []).map(([at, v]) => {
      if (at === "open") return `Mở ${value(v)}`;
      const p = etParts(at), ymd = `${p.year}-${p.month}-${p.day}`;
      return `${ymd === todayYmd ? "" : `${p.day}/${p.month} `}${p.hour}:${p.minute} ${value(v)}`;
    }).join(" · ");
  }
  function arrange(rows, comp, sort) {
    const list = (rows || []).filter((r) => comp === "ALL" || r.comp === comp);
    return list.sort(sort === "signal"
      ? (a, b) => Number(a.signal_rank) - Number(b.signal_rank)
      : (a, b) => Date.parse(a.start_time) - Date.parse(b.start_time) || Number(a.signal_rank) - Number(b.signal_rank));
  }
  const short = (comp) => SHORT[comp] || comp;

  root.ActionsSoccer = { price, line, tone, history, arrange, short, ORDER };
})(globalThis);
