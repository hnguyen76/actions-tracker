"""Soccer from ESPN's public scoreboards: fixtures, DraftKings lines and the 90-minute score.

Soccer bets are graded on the score after 90 minutes plus stoppage time: extra-time goals and penalty shootouts do
not count. ESPN's final score includes extra time, so for a game decided after 90 minutes the score is rebuilt from
its goal list (each goal carries its minute; own goals are credited to the team that benefits, shootout kicks are
flagged). Lines are DraftKings' (through ESPN): moneyline with the draw (1X2), spread (Asian handicap, quarter lines
split in two halves) and total goals, each with its opening and closing number.

The owner's method (like NFL): Monday-Friday US/Eastern follow the experts' majority side in every market, the draw
included, once that side has at least two experts; Saturday-Sunday fade the spread majority when at least five
experts picked the spread (moneyline and totals are not faded).
"""

import json
import math
import re

import pandas as pd

from actions_tracker.config import TZ

COMPS = {
    "eng.1": "Premier League", "uefa.champions": "Champions League", "uefa.europa": "Europa League",
    "esp.1": "La Liga", "ita.1": "Serie A", "ger.1": "Bundesliga", "fra.1": "Ligue 1", "usa.1": "MLS",
}
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{comp}/scoreboard?dates={d}"
AFTER_90 = {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}     # decided in extra time or on penalties
WEEKDAY_VOTES = 2                                       # Mon-Fri: experts on the majority side
WEEKEND_PICKS = 5                                       # Sat-Sun: experts on the spread in all
_OTHER = {"home": "away", "away": "home"}


def _int(value):
    try:
        return int(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _num(value):
    try:
        return float(str(value).lstrip("ou").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _minute(display) -> int | None:
    """ "90'+3'" -> 90 (stoppage time of the second half), "114'" -> 114."""
    m = re.match(r"\s*(\d+)", str(display or ""))
    return int(m.group(1)) if m else None


def score_90(competition: dict, status: str) -> tuple[int, int] | None:
    """(home, away) after 90 minutes, or None while the game is not final or its goal list is missing."""
    teams = {c.get("homeAway"): c for c in competition.get("competitors") or []}
    if "home" not in teams or "away" not in teams:
        return None
    home, away = _int(teams["home"].get("score")), _int(teams["away"].get("score"))
    if status not in AFTER_90:
        return (home, away) if home is not None and away is not None else None
    details = competition.get("details")
    if not isinstance(details, list):
        return None
    ids = {str(teams["home"].get("team", {}).get("id")): 0, str(teams["away"].get("team", {}).get("id")): 1}
    goals = [0, 0]
    for play in details:
        if not play.get("scoringPlay") or play.get("shootout"):
            continue
        minute, side = _minute((play.get("clock") or {}).get("displayValue")), ids.get(str((play.get("team") or {}).get("id")))
        if minute is not None and minute <= 90 and side is not None:
            goals[side] += 1
    return goals[0], goals[1]


def parse_odds(odds: list) -> dict:
    """DraftKings 1X2 / spread / total with opening and closing numbers (empty when ESPN has no line)."""
    items = [o for o in odds or [] if isinstance(o, dict)]
    dk = next((o for o in items if re.search(r"draftkings", str((o.get("provider") or {}).get("name") or ""), re.I)),
              items[0] if items else None)
    if not isinstance(dk, dict):
        return {}
    out = {}
    ml = dk.get("moneyline") or {}
    out["ml"] = {side: {when: _int((ml.get(side) or {}).get(when, {}).get("odds")) for when in ("open", "close")}
                 for side in ("home", "draw", "away") if ml.get(side)}
    for market, key, sides in (("spread", "pointSpread", ("home", "away")), ("total", "total", ("over", "under"))):
        block = dk.get(key) or {}
        out[market] = {side: {when: {"line": _num((block.get(side) or {}).get(when, {}).get("line")),
                                     "odds": _int((block.get(side) or {}).get(when, {}).get("odds"))}
                              for when in ("open", "close")} for side in sides if block.get(side)}
    return {k: v for k, v in out.items() if v}


def parse_events(data: dict, comp: str) -> list[dict]:
    out = []
    for e in (data or {}).get("events", []):
        competition = (e.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in competition.get("competitors") or []}
        if "home" not in teams or "away" not in teams:
            continue
        status = (e.get("status") or {}).get("type") or {}
        state = {"pre": "scheduled", "in": "live", "post": "final"}.get(status.get("state"), "scheduled")
        name = status.get("name") or ""
        out.append({
            "event_id": str(e.get("id")), "comp": comp, "short": e.get("shortName"), "start_time": e.get("date"),
            "state": state, "status": name, "detail": status.get("shortDetail"),
            "home_name": teams["home"]["team"].get("displayName"), "away_name": teams["away"]["team"].get("displayName"),
            "home_abbr": teams["home"]["team"].get("abbreviation"), "away_abbr": teams["away"]["team"].get("abbreviation"),
            "home_score": _int(teams["home"].get("score")), "away_score": _int(teams["away"].get("score")),
            "score_90": score_90(competition, name) if state == "final" else None,
            "odds": parse_odds(competition.get("odds")),
        })
    return out


def _single(market: str, side: str, line: float | None, home: int, away: int) -> str:
    if market == "ml":
        diff = home - away
        return "win" if (diff > 0 and side == "home") or (diff < 0 and side == "away") or (diff == 0 and side == "draw") \
            else "loss"
    if market == "spread":
        own = (home - away) if side == "home" else (away - home)
        value = own + line
    else:
        value = (home + away - line) if side == "over" else (line - home - away)
    return "win" if value > 0 else "loss" if value < 0 else "push"


def grade(market: str, side: str, line: float | None, home: int, away: int) -> str:
    """win / loss / push on the 90-minute score; a quarter line (x.25 / x.75) is two half bets on the lines
    either side of it: half_win (a win and a push) or half_loss (a loss and a push)."""
    if market != "ml" and line is not None and (abs(line) * 4) % 2 == 1:
        a, b = _single(market, side, line - 0.25, home, away), _single(market, side, line + 0.25, home, away)
        if a == b:
            return a
        pair = {a, b}
        return "half_win" if pair == {"win", "push"} else "half_loss" if pair == {"loss", "push"} else "push"
    return _single(market, side, line, home, away)


def method_plays(groups: list[dict]) -> list[dict]:
    """groups: one row per game x market with the majority side (no tie): game_id, start_time, market, side, votes,
    total_votes. Returns the plays the owner's method makes, with method / bet_side / ET date and day group."""
    plays = []
    for g in groups:
        local = pd.Timestamp(g["start_time"]).tz_convert(TZ)
        weekday = local.day_of_week <= 4
        if weekday:
            if int(g["votes"]) < WEEKDAY_VOTES:
                continue
            method, bet = "follow", g["side"]
        else:
            if g["market"] != "spread" or int(g["total_votes"]) < WEEKEND_PICKS or g["side"] not in _OTHER:
                continue
            method, bet = "fade", _OTHER[g["side"]]
        plays.append({**g, "method": method, "bet_side": bet, "et_date": local.strftime("%Y-%m-%d"),
                      "day_group": "T2-6" if weekday else "T7-CN"})
    return plays


# --- the phone's poll: every game of the next week, every DraftKings line move ---------------------------------
GAMES_SCHEMA = ("CREATE TABLE IF NOT EXISTS soccer_games(event_id TEXT PRIMARY KEY, comp TEXT, start_time TEXT, "
                "home_name TEXT, away_name TEXT, home_abbr TEXT, away_abbr TEXT, state TEXT, status TEXT, detail TEXT, "
                "home_score INTEGER, away_score INTEGER, home_90 INTEGER, away_90 INTEGER, open_json TEXT, "
                "odds_json TEXT, updated_at TEXT)")
LINES_SCHEMA = ("CREATE TABLE IF NOT EXISTS soccer_line_history(event_id TEXT, market TEXT, side TEXT, line REAL, "
                "odds INTEGER, seen_at TEXT, PRIMARY KEY(event_id, market, side, seen_at))")
NEAR_DAYS = 3        # today and the next two days, every run (lines move most close to kickoff)
FAR_DAYS = 8         # up to a week ahead ...
FAR_EVERY_H = 2      # ... every two hours
BOARD_DAYS = 7
STRONG, MEDIUM = 6.0, 3.0    # market move, percentage points of no-vig probability
UA = {"User-Agent": "actions-tracker/1.0"}
_SIDES = {"ml": ("home", "draw", "away"), "spread": ("home", "away"), "total": ("over", "under")}


def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _days(now: str, upto: int) -> list[str]:
    today = pd.Timestamp(now).tz_convert(TZ).normalize()
    return [(today + pd.Timedelta(days=i)).strftime("%Y%m%d") for i in range(-1, upto)]


def _split(odds: dict, when: str) -> dict:
    """{market: {side: value}}; value is the price for 1X2, [line, price] for spread and total."""
    out = {}
    for market, sides in odds.items():
        for side, v in sides.items():
            value = v.get(when) if market == "ml" else [v.get(when, {}).get("line"), v.get(when, {}).get("odds")]
            if value is not None and value != [None, None]:
                out.setdefault(market, {})[side] = value
    return out


def _store(conn, e: dict, now: str) -> None:
    opened, current = _split(e["odds"], "open"), _split(e["odds"], "close")
    h90, a90 = e["score_90"] if e["score_90"] else (None, None)
    conn.execute(
        "INSERT INTO soccer_games(event_id, comp, start_time, home_name, away_name, home_abbr, away_abbr, state, status, "
        "detail, home_score, away_score, home_90, away_90, open_json, odds_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_id) DO UPDATE SET "
        "comp=excluded.comp, start_time=excluded.start_time, home_name=excluded.home_name, away_name=excluded.away_name, "
        "home_abbr=excluded.home_abbr, away_abbr=excluded.away_abbr, state=excluded.state, status=excluded.status, "
        "detail=excluded.detail, home_score=excluded.home_score, away_score=excluded.away_score, "
        "home_90=excluded.home_90, away_90=excluded.away_90, "
        "open_json=COALESCE(soccer_games.open_json, excluded.open_json), "
        "odds_json=COALESCE(excluded.odds_json, soccer_games.odds_json), updated_at=excluded.updated_at",
        (e["event_id"], e["comp"], _iso(e["start_time"]), e["home_name"], e["away_name"], e["home_abbr"], e["away_abbr"],
         e["state"], e["status"], e["detail"], e["home_score"], e["away_score"], h90, a90,
         json.dumps(opened) if opened else None, json.dumps(current) if current else None, now))
    if e["state"] != "scheduled":
        return
    for market, sides in current.items():
        for side, value in sides.items():
            line, price = (None, value) if market == "ml" else value
            last = conn.execute("SELECT line, odds FROM soccer_line_history WHERE event_id = ? AND market = ? AND side = ? "
                                "ORDER BY seen_at DESC LIMIT 1", (e["event_id"], market, side)).fetchone()
            if last is None or (last[0], last[1]) != (line, price):
                conn.execute("INSERT OR IGNORE INTO soccer_line_history(event_id, market, side, line, odds, seen_at) "
                             "VALUES (?, ?, ?, ?, ?, ?)", (e["event_id"], market, side, line, price, now))


def collect(conn, now: str, get=None) -> dict:
    """Poll ESPN for yesterday .. two days ahead (and a week ahead every FAR_EVERY_H hours) in every competition;
    store each game and every line that moved. A failed request is skipped. Never touches the other leagues."""
    import requests

    from actions_tracker import db
    get = get or requests.get
    conn.execute(GAMES_SCHEMA)
    conn.execute(LINES_SCHEMA)
    last_far = db.get_meta(conn, "soccer_far_at")
    far = last_far is None or pd.Timestamp(now) - pd.Timestamp(last_far) >= pd.Timedelta(hours=FAR_EVERY_H)
    games, errors = {}, 0
    for comp in COMPS:
        for d in _days(now, FAR_DAYS if far else NEAR_DAYS):
            try:
                r = get(SCOREBOARD.format(comp=comp, d=d), timeout=30, headers=UA)
                if r.status_code != 200:
                    errors += 1
                    continue
                for e in parse_events(r.json(), comp):
                    games[e["event_id"]] = e
            except Exception:  # noqa: BLE001 - one day of one competition never stops the poll
                errors += 1
    for e in games.values():
        _store(conn, e, now)
    if far:
        db.set_meta(conn, "soccer_far_at", now)
    conn.commit()
    return {"games": len(games), "errors": errors, "far": far}


# --- the board: upcoming games, their lines and line history, ranked by how far the market moved ----------------
def _prob(price) -> float | None:
    if price is None:
        return None
    price = float(price)
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def no_vig(prices: dict) -> dict:
    """Implied probabilities with the bookmaker's margin taken out (they sum to 1)."""
    raw = {k: _prob(v) for k, v in prices.items()}
    if any(v is None for v in raw.values()) or not raw:
        return {}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def _over(goals_expected: float, line: float) -> float:
    """P(more goals than the line) for Poisson goals; a whole line refunds on exactly that many goals."""
    k = math.floor(line)
    cdf = sum(math.exp(-goals_expected) * goals_expected ** i / math.factorial(i) for i in range(k + 1))
    if line == k:
        exact = math.exp(-goals_expected) * goals_expected ** k / math.factorial(k)
        return (1 - cdf) / (1 - exact) if exact < 1 else 0.5
    return 1 - cdf


def goals(line: float, p_over: float) -> float:
    """Expected goals that price the over at this line (Poisson, by bisection)."""
    lo, hi = 0.05, 12.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _over(mid, line) < p_over else (lo, mid)
    return (lo + hi) / 2


def _total_shift(o_t: dict, n_t: dict) -> float | None:
    """Over move in points at today's line: today's no-vig over minus the over the opening prices imply at that
    line. DraftKings sometimes moves the main total to another line (3,5 -> 2,5); this compares like with like."""
    if not ({"over", "under"} <= o_t.keys() and {"over", "under"} <= n_t.keys()):
        return None
    o_line, n_line = o_t["over"][0], n_t["over"][0]
    o_p = no_vig({"over": o_t["over"][1], "under": o_t["under"][1]})
    n_p = no_vig({"over": n_t["over"][1], "under": n_t["under"][1]})
    if o_line is None or n_line is None or not o_p or not n_p:
        return None
    before = o_p["over"] if o_line == n_line else _over(goals(o_line, o_p["over"]), n_line)
    return round((n_p["over"] - before) * 100, 1)


def _fmt(v: float, sign: bool = True) -> str:
    text = f"{abs(v):g}".replace(".", ",")
    return ("−" if v < 0 else "+" if v > 0 and sign else "") + text


def _signals(game: dict, opened: dict, current: dict) -> list[dict]:
    out = []
    label = {"home": game["home_abbr"], "away": game["away_abbr"], "draw": "Hoà"}
    o_ml, n_ml = no_vig(opened.get("ml", {})), no_vig(current.get("ml", {}))
    if o_ml and n_ml and o_ml.keys() == n_ml.keys():
        side = max(n_ml, key=lambda s: n_ml[s] - o_ml[s])
        delta = round((n_ml[side] - o_ml[side]) * 100, 1)
        if delta > 0:
            out.append({"market": "ml", "side": side, "label": label[side], "delta": delta,
                        "text": f"{label[side]} +{_fmt(delta, False)}%"})
    o_t, n_t = opened.get("total", {}), current.get("total", {})
    d = _total_shift(o_t, n_t)
    if d:
        side = "over" if d > 0 else "under"
        out.append({"market": "total", "side": side, "label": side.title(), "delta": abs(d),
                    "text": f"{side.title()} +{_fmt(abs(d), False)}%"})
    if d is not None and o_t["over"][0] != n_t["over"][0]:      # the line itself moved: shown, not scored twice
        o_line, n_line = o_t["over"][0], n_t["over"][0]
        out.append({"market": "total", "side": "over" if n_line > o_line else "under", "label": "Total",
                    "delta": None, "text": f"Total {_fmt(o_line, False)}→{_fmt(n_line, False)}"})
    o_s, n_s = opened.get("spread", {}).get("home"), current.get("spread", {}).get("home")
    if o_s and n_s and o_s[0] is not None and n_s[0] is not None and o_s[0] != n_s[0]:
        out.append({"market": "spread", "side": "home" if n_s[0] < o_s[0] else "away",
                    "label": game["home_abbr"], "delta": None,
                    "text": f"{game['home_abbr']} {_fmt(o_s[0])}→{_fmt(n_s[0])}"})
    return sorted(out, key=lambda s: -(s["delta"] if s["delta"] is not None else -1))


BOARD_COLS = ["event_id", "comp", "comp_name", "start_time", "et_date", "home_abbr", "away_abbr", "home_name",
              "away_name", "now", "open", "moves", "history", "signals", "score", "tone", "signal_rank"]


def _moves(opened: dict, current: dict) -> dict:
    """Change of each price since the open, in points of no-vig probability (+ = the market moved toward it)."""
    out = {}
    o_ml, n_ml = no_vig(opened.get("ml", {})), no_vig(current.get("ml", {}))
    if o_ml and n_ml and o_ml.keys() == n_ml.keys():
        out["ml"] = {k: round((n_ml[k] - o_ml[k]) * 100, 1) for k in n_ml}
    d = _total_shift(opened.get("total", {}), current.get("total", {}))
    if d is not None:
        out["total"] = {"over": d, "under": -d}
    return out


def board_table(conn, now: str) -> pd.DataFrame:
    """Games that have not kicked off, within BOARD_DAYS, with lines now and at open, every line seen, and the
    market-move signals; signal_rank 1 = the game whose market moved most."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='soccer_games'").fetchone()
    if not exists:
        return pd.DataFrame(columns=BOARD_COLS)
    until = _iso(pd.Timestamp(now) + pd.Timedelta(days=BOARD_DAYS))
    games = [dict(r) for r in conn.execute(
        "SELECT * FROM soccer_games WHERE state = 'scheduled' AND start_time > ? AND start_time <= ? "
        "AND odds_json IS NOT NULL ORDER BY start_time, event_id", (_iso(now), until))]
    rows = []
    for g in games:
        opened, current = json.loads(g["open_json"] or "{}"), json.loads(g["odds_json"] or "{}")
        history = {}
        for market, side, line, price, seen in conn.execute(
                "SELECT market, side, line, odds, seen_at FROM soccer_line_history WHERE event_id = ? "
                "ORDER BY seen_at", (g["event_id"],)):
            seq = history.setdefault(market, {}).setdefault(side, [])
            if not seq and side in opened.get(market, {}):
                seq.append(["open", opened[market][side]])
            seq.append([seen, price if market == "ml" else [line, price]])
        signals = _signals(g, opened, current)
        score = max([s["delta"] for s in signals if s["delta"] is not None], default=0.0)
        spread, total = current.get("spread", {}), current.get("total", {})
        rows.append({
            "event_id": g["event_id"], "comp": g["comp"], "comp_name": COMPS.get(g["comp"], g["comp"]),
            "start_time": g["start_time"], "et_date": pd.Timestamp(g["start_time"]).tz_convert(TZ).strftime("%Y-%m-%d"),
            "home_abbr": g["home_abbr"], "away_abbr": g["away_abbr"], "home_name": g["home_name"], "away_name": g["away_name"],
            "now": {"ml": current.get("ml", {}),
                    "spread": {s: {"line": v[0], "odds": v[1]} for s, v in spread.items()},
                    "total": {"line": (total.get("over") or [None])[0], "over": (total.get("over") or [None, None])[1],
                              "under": (total.get("under") or [None, None])[1]} if total else {}},
            "open": opened, "moves": _moves(opened, current), "history": history, "signals": signals, "score": score,
            "tone": "strong" if score >= STRONG else "medium" if score >= MEDIUM else "weak"})
    out = pd.DataFrame(rows, columns=BOARD_COLS)
    if out.empty:
        return out
    order = out.sort_values(["score", "start_time"], ascending=[False, True], kind="stable").index
    out.loc[order, "signal_rank"] = range(1, len(out) + 1)
    out["signal_rank"] = out["signal_rank"].astype(int)
    return out.astype(object)
