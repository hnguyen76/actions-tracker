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
            "home_id": str(teams["home"]["team"].get("id") or ""), "away_id": str(teams["away"]["team"].get("id") or ""),
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
RESULTS_SCHEMA = ("CREATE TABLE IF NOT EXISTS soccer_market_results(event_id TEXT, comp TEXT, start_time TEXT, "
                  "et_date TEXT, day_group TEXT, home_abbr TEXT, away_abbr TEXT, home_90 INTEGER, away_90 INTEGER, "
                  "market TEXT, side TEXT, open_line REAL, open_odds INTEGER, close_line REAL, close_odds INTEGER, "
                  "close_seen_at TEXT, result TEXT, profit_u REAL, graded_at TEXT, "
                  "PRIMARY KEY(event_id, market, side))")
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
    if e["state"] == "final" and e["score_90"]:
        saved = conn.execute("SELECT open_json, odds_json FROM soccer_games WHERE event_id = ?", (e["event_id"],)).fetchone()
        saved_open = json.loads(saved[0] or "{}") if saved else opened
        saved_close = json.loads(saved[1] or "{}") if saved else current
        _store_market_results(conn, e, saved_open, saved_close, now)
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


def _profit(result: str, odds: int | None) -> float | None:
    """Profit for one unit risked at American odds; quarter-line halves keep their half result."""
    if odds is None:
        return None
    win = odds / 100 if odds > 0 else 100 / -odds
    return round({"win": win, "loss": -1.0, "push": 0.0,
                  "half_win": win / 2, "half_loss": -0.5}[result], 4)


def _store_market_results(conn, e: dict, opened: dict, current: dict, now: str) -> None:
    """Freeze every offered closing side once the 90-minute score is final.

    These are market outcomes, not claims that the owner bet every side.  Keeping every side, price, line and score
    lets a later analysis join expert picks or test a new rule without reconstructing old ESPN pages.
    """
    closing = {m: {s: ([None, v, now] if m == "ml" else [*v, now]) for s, v in values.items()}
               for m, values in current.items()}
    for market, side, line, odds, seen_at in conn.execute(
            "SELECT h.market, h.side, h.line, h.odds, h.seen_at FROM soccer_line_history h "
            "WHERE h.event_id = ? AND h.seen_at = (SELECT MAX(x.seen_at) FROM soccer_line_history x "
            "WHERE x.event_id = h.event_id AND x.market = h.market AND x.side = h.side)", (e["event_id"],)):
        closing.setdefault(market, {})[side] = [line, odds, seen_at]
    local = pd.Timestamp(e["start_time"]).tz_convert(TZ)
    home, away = e["score_90"]
    for market, sides in closing.items():
        for side, close in sides.items():
            close_line, close_odds = (close + [None])[:2] if isinstance(close, list) else (None, close)
            close_seen = close[2] if isinstance(close, list) and len(close) > 2 else now
            if close_odds is None or market not in _SIDES or side not in _SIDES[market]:
                continue
            result = grade(market, side, close_line, home, away)
            raw_open = opened.get(market, {}).get(side)
            open_line, open_odds = (None, raw_open) if market == "ml" else (
                (raw_open or [None, None])[:2] if isinstance(raw_open, list) else (None, None))
            conn.execute(
                "INSERT INTO soccer_market_results(event_id, comp, start_time, et_date, day_group, "
                "home_abbr, away_abbr, home_90, away_90, market, side, open_line, open_odds, close_line, close_odds, "
                "close_seen_at, result, profit_u, graded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(event_id, market, side) DO UPDATE SET home_90=excluded.home_90, away_90=excluded.away_90, "
                "result=excluded.result, profit_u=excluded.profit_u, graded_at=excluded.graded_at",
                (e["event_id"], e["comp"], _iso(e["start_time"]), local.strftime("%Y-%m-%d"),
                 "T2-6" if local.day_of_week <= 4 else "T7-CN", e["home_abbr"], e["away_abbr"], home, away,
                 market, side, open_line, open_odds, close_line, close_odds, close_seen, result,
                 _profit(result, close_odds), now))


def _backfill_market_results(conn, now: str) -> int:
    """Archive final games already stored before this table existed, without needing ESPN to return them again."""
    games = [dict(r) for r in conn.execute(
        "SELECT g.* FROM soccer_games g WHERE g.state = 'final' AND g.home_90 IS NOT NULL AND g.away_90 IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM soccer_market_results r WHERE r.event_id = g.event_id)")]
    for g in games:
        event = {**g, "score_90": (g["home_90"], g["away_90"])}
        _store_market_results(conn, event, json.loads(g["open_json"] or "{}"), json.loads(g["odds_json"] or "{}"), now)
    return len(games)


def collect(conn, now: str, get=None) -> dict:
    """Poll ESPN for yesterday .. two days ahead (and a week ahead every FAR_EVERY_H hours) in every competition;
    store each game and every line that moved. A failed request is skipped. Never touches the other leagues."""
    import requests

    from actions_tracker import db
    get = get or requests.get
    conn.execute(GAMES_SCHEMA)
    conn.execute(LINES_SCHEMA)
    conn.execute(RESULTS_SCHEMA)
    backfilled = _backfill_market_results(conn, now)
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
    half = _capture_half(conn, [e for e in games.values() if e["state"] == "scheduled"], now, get)
    second = sum(_capture_second_half(conn, e, now, get) for e in games.values() if e["status"] == HALFTIME)
    if far:
        db.set_meta(conn, "soccer_far_at", now)
    conn.commit()
    results = conn.execute("SELECT COUNT(*) FROM soccer_market_results").fetchone()[0]
    return {"games": len(games), "errors": errors, "far": far, "half_lines": half, "second_half": second,
            "market_results": results, "backfilled_results": backfilled}


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


# --- final 90-minute outcomes grouped for the daily Soccer report ---------------------------------------------
RESULT_COLS = ["event_id", "comp", "comp_name", "start_time", "et_date", "day_group", "home_abbr", "away_abbr",
               "home_90", "away_90", "ml", "spread", "total"]
DAILY_COLS = ["et_date", "games", "home_wins", "draws", "away_wins", "overs", "unders", "total_pushes"]


def _winning_side(rows: list[dict], market: str) -> dict | None:
    market_rows = [r for r in rows if r["market"] == market]
    winner = next((r for result in ("win", "half_win") for r in market_rows if r["result"] == result), None)
    if winner:
        return {"side": winner["side"], "line": winner["close_line"], "odds": winner["close_odds"],
                "result": winner["result"]}
    if market_rows and all(r["result"] == "push" for r in market_rows):
        return {"side": "push", "line": market_rows[0]["close_line"], "odds": None, "result": "push"}
    return None


def results_table(conn) -> pd.DataFrame:
    """One auditable row per final game for the daily UI; the database keeps all individual market sides."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='soccer_market_results'").fetchone()
    if not exists:
        return pd.DataFrame(columns=RESULT_COLS)
    raw = [dict(r) for r in conn.execute(
        "SELECT * FROM soccer_market_results ORDER BY start_time DESC, event_id, market, side")]
    games = {}
    for row in raw:
        games.setdefault(row["event_id"], []).append(row)
    output = []
    for event_id, rows in games.items():
        r = rows[0]
        output.append({"event_id": event_id, "comp": r["comp"], "comp_name": COMPS.get(r["comp"], r["comp"]),
                       "start_time": r["start_time"], "et_date": r["et_date"], "day_group": r["day_group"],
                       "home_abbr": r["home_abbr"], "away_abbr": r["away_abbr"],
                       "home_90": r["home_90"], "away_90": r["away_90"],
                       "ml": _winning_side(rows, "ml"), "spread": _winning_side(rows, "spread"),
                       "total": _winning_side(rows, "total")})
    return pd.DataFrame(output, columns=RESULT_COLS).sort_values(
        ["start_time", "event_id"], ascending=[False, True], kind="stable").astype(object)


def daily_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Daily 90-minute outcome mix. This is deliberately not labelled as a betting W-L record."""
    if results is None or results.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    output = []
    for et_date, group in results.groupby("et_date", sort=False):
        ml = [r for r in group["ml"] if isinstance(r, dict)]
        totals = [r for r in group["total"] if isinstance(r, dict)]
        output.append({"et_date": et_date, "games": len(group),
                       "home_wins": sum(r["side"] == "home" for r in ml),
                       "draws": sum(r["side"] == "draw" for r in ml),
                       "away_wins": sum(r["side"] == "away" for r in ml),
                       "overs": sum(r["side"] == "over" for r in totals),
                       "unders": sum(r["side"] == "under" for r in totals),
                       "total_pushes": sum(r["side"] == "push" for r in totals)})
    return pd.DataFrame(output, columns=DAILY_COLS).astype(object)


# --- 1H lines, captured before kickoff: once a game is under way ESPN's pregame half props turn to leftovers ------
HALF_SCHEMA = ("CREATE TABLE IF NOT EXISTS soccer_half_lines(event_id TEXT PRIMARY KEY, first_ml TEXT, first_total TEXT, "
               "captured_at TEXT)")
HALF_WITHIN_H = 12     # games kicking off within 12 h (the phone stops at 23:00 ET; Saturday 7:30 ET games need it)
HALF_EVERY_MIN = 60    # refresh each game's 1H lines at most hourly; the last capture before kickoff stands
CORE_ODDS = ("https://sports.core.api.espn.com/v2/sports/soccer/leagues/{comp}/events/{id}/competitions/{id}/odds"
             "?lang=en&region=us&limit=100")


def _american(item: dict):
    return _int(((item.get("current") or {}).get("over") or {}).get("american"))


def _moneyline(props: dict, name: str, home_id: str, away_id: str) -> dict:
    """{home, draw, away: price} of a 3-way moneyline prop list (a price off the board is left out)."""
    out = {}
    for x in (props or {}).get("items", []):
        if not isinstance(x, dict) or (x.get("type") or {}).get("name") != name or _american(x) is None:
            continue
        m = re.search(r"/teams/(\d+)", str((x.get("team") or {}).get("$ref") or ""))
        key = "draw" if not m else "home" if m.group(1) == str(home_id) else "away" if m.group(1) == str(away_id) else None
        if key:
            out[key] = _american(x)
    return out


def _props_url(item: dict | None) -> str | None:
    ref = str(((item or {}).get("propBets") or {}).get("$ref") or "")
    if not ref.startswith(("http://sports.core.api.espn.com/", "https://sports.core.api.espn.com/")):
        return None
    return re.sub(r"^http:", "https:", ref) + ("&" if "?" in ref else "?") + "limit=1000"


def half_lines(props: dict, home_id: str, away_id: str) -> dict:
    """DraftKings 1H 3-way moneyline and main 1H total from ESPN's pregame props. Each total line is listed twice,
    over first; a line set whose over chance does not fall as the line rises is not trusted (no total)."""
    items = [x for x in (props or {}).get("items", []) if isinstance(x, dict)]
    ml = _moneyline(props, "1st Half Moneyline", home_id, away_id)
    lines: dict = {}
    for x in items:
        if (x.get("type") or {}).get("name") != "1st Half Total":
            continue
        line, price = _num(((x.get("current") or {}).get("target") or {}).get("value")), _american(x)
        if line is not None and price is not None:
            lines.setdefault(line, []).append(price)
    pairs = []
    for line in sorted(lines):
        if len(lines[line]) == 2:
            over, under = lines[line]
            p = no_vig({"over": over, "under": under})
            pairs.append({"line": line, "over": over, "under": under, "p": p["over"]})
    total = None
    if pairs and all(b["p"] < a["p"] for a, b in zip(pairs, pairs[1:])):
        main = min(pairs, key=lambda x: abs(x["p"] - 0.5))
        total = {"line": main["line"], "over": main["over"], "under": main["under"]}
    return {"first_ml": ml if len(ml) == 3 else None, "first_total": total}


def _capture_half(conn, games: list[dict], now: str, get) -> int:
    conn.execute(HALF_SCHEMA)
    t, done = pd.Timestamp(now), 0
    for e in games:
        start = pd.Timestamp(e["start_time"])
        if not (t < start <= t + pd.Timedelta(hours=HALF_WITHIN_H)):
            continue
        last = conn.execute("SELECT captured_at FROM soccer_half_lines WHERE event_id = ?", (e["event_id"],)).fetchone()
        if last and t - pd.Timestamp(last[0]) < pd.Timedelta(minutes=HALF_EVERY_MIN):
            continue
        try:
            r = get(CORE_ODDS.format(comp=e["comp"], id=e["event_id"]), timeout=30, headers=UA)
            items = r.json().get("items", []) if r.status_code == 200 else []
            dk = next((x for x in items if re.fullmatch(r"draftkings", str((x.get("provider") or {}).get("name") or ""), re.I)), None)
            ref = _props_url(dk)
            if ref is None:
                continue
            r = get(ref, timeout=30, headers=UA)
            h = half_lines(r.json() if r.status_code == 200 else {}, e["home_id"], e["away_id"])
        except Exception:  # noqa: BLE001 - 1H lines are a convenience; the next run tries again
            continue
        if h["first_ml"] or h["first_total"]:
            conn.execute("INSERT INTO soccer_half_lines(event_id, first_ml, first_total, captured_at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(event_id) DO UPDATE SET first_ml=excluded.first_ml, first_total=excluded.first_total, "
                         "captured_at=excluded.captured_at",
                         (e["event_id"], json.dumps(h["first_ml"]) if h["first_ml"] else None,
                          json.dumps(h["first_total"]) if h["first_total"] else None, now))
            done += 1
    return done


HALF_COLS = ["event_id", "first_ml", "first_total", "captured_at"]


def half_lines_table(conn, now: str) -> pd.DataFrame:
    """1H lines of games kicked off in the last 6 h or kicking off within 12 h (for the live 2H plays)."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='soccer_half_lines'").fetchone()
    if not exists:
        return pd.DataFrame(columns=HALF_COLS)
    lo, hi = _iso(pd.Timestamp(now) - pd.Timedelta(hours=6)), _iso(pd.Timestamp(now) + pd.Timedelta(hours=HALF_WITHIN_H))
    rows = [{"event_id": r[0], "first_ml": json.loads(r[1]) if r[1] else None,
             "first_total": json.loads(r[2]) if r[2] else None, "captured_at": r[3]} for r in conn.execute(
        "SELECT h.event_id, h.first_ml, h.first_total, h.captured_at FROM soccer_half_lines h "
        "JOIN soccer_games g ON g.event_id = h.event_id WHERE g.start_time >= ? AND g.start_time <= ? "
        "ORDER BY g.start_time", (lo, hi))]
    return pd.DataFrame(rows, columns=HALF_COLS).astype(object)


# --- 2H plays, like NFL: locked at the first halftime sighting, graded on the 90-minute score --------------------
# DraftKings has no live "2nd Half" soccer market at halftime but two exact equivalents: the 3-way "Moneyline - Rest
# of Game", and the live full-game total less the 1H goals (every later goal is a 2H goal). The 1H lines are the
# ones captured before kickoff (soccer_half_lines). Each price and the total are kept from the first sighting that
# has them; a later sighting only fills what was off the board.
SECOND_SCHEMA = ("CREATE TABLE IF NOT EXISTS soccer_second_half(event_id TEXT PRIMARY KEY, comp TEXT, start_time TEXT, "
                 "home_abbr TEXT, away_abbr TEXT, home_1h INTEGER, away_1h INTEGER, first_ml TEXT, first_total TEXT, "
                 "rest_home INTEGER, rest_draw INTEGER, rest_away INTEGER, live_total REAL, live_over INTEGER, "
                 "live_under INTEGER, captured_at TEXT, updated_at TEXT)")
HALFTIME = "STATUS_HALFTIME"
REST_OF_GAME = "Moneyline - Rest of Game"
LIVE_WINDOW_H = 3      # the live run polls a competition only while one of its games kicked off in the last 3 h
_TOTAL_KEYS = ("live_total", "live_over", "live_under")
_REST_KEYS = ("rest_home", "rest_draw", "rest_away")


def _price(value):
    try:
        v = float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return int(round(v)) if math.isfinite(v) and v != 0 else None


def live_total(item: dict | None) -> dict | None:
    """The live full-game total of ESPN's "DraftKings - Live Odds" item: {line, over, under} (a price can be off)."""
    line = _num((item or {}).get("overUnder"))
    if line is None:
        return None
    return {"line": line, "over": _price(item.get("overOdds")), "under": _price(item.get("underOdds"))}


def _capture_second_half(conn, e: dict, now: str, get) -> bool:
    """Lock a game seen at halftime: 1H score, its 1H lines and the live 2H prices. True when the row changed."""
    conn.execute(SECOND_SCHEMA)
    conn.execute(HALF_SCHEMA)
    if e.get("home_score") is None or e.get("away_score") is None:
        return False
    row = conn.execute("SELECT * FROM soccer_second_half WHERE event_id = ?", (e["event_id"],)).fetchone()
    old = dict(row) if row else {}
    if old and all(old.get(k) is not None for k in _REST_KEYS + _TOTAL_KEYS):
        return False                                    # everything locked: no request
    total, rest = None, {}
    try:
        r = get(CORE_ODDS.format(comp=e["comp"], id=e["event_id"]), timeout=30, headers=UA)
        items = r.json().get("items", []) if r.status_code == 200 else []
        live = next((x for x in items if isinstance(x, dict)
                     and re.search(r"live", str((x.get("provider") or {}).get("name") or ""), re.I)), None)
        total = live_total(live)
        ref = _props_url(live)
        if ref:
            r = get(ref, timeout=30, headers=UA)
            rest = _moneyline(r.json() if r.status_code == 200 else {}, REST_OF_GAME, e["home_id"], e["away_id"])
    except Exception:  # noqa: BLE001 - the next sighting during halftime tries again
        pass
    half = conn.execute("SELECT first_ml, first_total FROM soccer_half_lines WHERE event_id = ?", (e["event_id"],)).fetchone()

    def keep(key, new):
        return old[key] if old.get(key) is not None else new
    was = tuple(old.get(k) for k in _TOTAL_KEYS)
    seen = (total["line"], total["over"], total["under"]) if total else (None, None, None)
    chosen = was if None not in was else seen if None not in seen else was if was[0] is not None else seen
    merged = {"event_id": e["event_id"], "comp": e["comp"], "start_time": _iso(e["start_time"]),
              "home_abbr": e["home_abbr"], "away_abbr": e["away_abbr"],
              "home_1h": keep("home_1h", e["home_score"]), "away_1h": keep("away_1h", e["away_score"]),
              "first_ml": keep("first_ml", half[0] if half else None),
              "first_total": keep("first_total", half[1] if half else None),
              **{k: keep(k, rest.get(k[5:])) for k in _REST_KEYS}, **dict(zip(_TOTAL_KEYS, chosen)),
              "captured_at": old.get("captured_at") or now}
    if all(merged[k] == old.get(k) for k in merged):
        return False
    merged["updated_at"] = now
    conn.execute(f"INSERT OR REPLACE INTO soccer_second_half({', '.join(merged)}) VALUES ({', '.join('?' * len(merged))})",
                 tuple(merged.values()))
    return True


def live_poll(conn, now: str, get) -> dict:
    """The 5-minute live run: today's scoreboard of each competition with a game kicked off in the last LIVE_WINDOW_H
    hours and not final yet (no request otherwise); stores scores and finals, and locks games at halftime."""
    for schema in (GAMES_SCHEMA, LINES_SCHEMA, RESULTS_SCHEMA, HALF_SCHEMA, SECOND_SCHEMA):
        conn.execute(schema)
    t = pd.Timestamp(now)
    lo, hi = _iso(t - pd.Timedelta(hours=LIVE_WINDOW_H)), _iso(t + pd.Timedelta(minutes=5))
    rows = conn.execute("SELECT DISTINCT comp, start_time FROM soccer_games WHERE start_time >= ? AND start_time <= ? "
                        "AND state != 'final'", (lo, hi)).fetchall()
    boards = sorted({(comp, pd.Timestamp(start).tz_convert(TZ).strftime("%Y%m%d")) for comp, start in rows})
    out = {"polled": 0, "live": 0, "final": 0, "halftime": 0, "changed": 0, "errors": 0}
    for comp, d in boards:
        out["polled"] += 1
        try:
            r = get(SCOREBOARD.format(comp=comp, d=d), timeout=30, headers=UA)
            if r.status_code != 200:
                out["errors"] += 1
                continue
            events = parse_events(r.json(), comp)
        except Exception:  # noqa: BLE001 - one competition never stops the live run
            out["errors"] += 1
            continue
        for e in events:
            before = conn.execute("SELECT state FROM soccer_games WHERE event_id = ?", (e["event_id"],)).fetchone()
            _store(conn, e, now)
            out["live"] += e["state"] == "live"
            if e["state"] == "final" and (before is None or before[0] != "final"):
                out["final"] += 1
                out["changed"] += 1
            if e["status"] == HALFTIME and _capture_second_half(conn, e, now, get):
                out["halftime"] += 1
                out["changed"] += 1
    conn.commit()
    return out


def _second_half_plays(r: dict) -> list[dict]:
    """The owner's 2H plays (soccer-live.js decide2H): the 1H moneyline favourite at -0,5 that does not lead at halftime
    is backed in the 2H, else the other team; 1H goals under the main 1H total -> 2H Over, over it -> Under, exactly on
    a whole line -> none. A play needs its locked price."""
    plays, home, away = [], r["home_1h"], r["away_1h"]
    ml = json.loads(r["first_ml"]) if r.get("first_ml") else None
    if ml and ml.get("home") is not None and ml.get("away") is not None and ml["home"] != ml["away"]:
        favourite = "home" if ml["home"] < ml["away"] else "away"
        covered = (home - away if favourite == "home" else away - home) >= 1
        team = _OTHER[favourite] if covered else favourite
        if r.get(f"rest_{team}") is not None:
            plays.append({"market": "ml", "pick_side": team, "line": None, "price": r[f"rest_{team}"],
                          "favourite": r[f"{favourite}_abbr"], "covered": covered, "first_line": None, "first_goals": None})
    first = json.loads(r["first_total"]) if r.get("first_total") else None
    goals = home + away
    if first and first.get("line") is not None and goals != first["line"] and r.get("live_total") is not None:
        side = "over" if goals < first["line"] else "under"
        if r.get(f"live_{side}") is not None:
            plays.append({"market": "total", "pick_side": side, "line": r["live_total"] - goals, "price": r[f"live_{side}"],
                          "favourite": None, "covered": None, "first_line": first["line"], "first_goals": goals})
    return plays


SECOND_COLS = ["event_id", "comp", "start_time", "et_date", "home_abbr", "away_abbr", "home_1h", "away_1h", "home_2h",
               "away_2h", "state", "market", "pick_side", "pick", "line", "price", "favourite", "covered", "first_line",
               "first_goals", "result", "units", "captured_at"]
SECOND_SUMMARY_COLS = ["scope", "et_date", "market", "tracked", "pending", "wins", "losses", "pushes", "graded",
                       "win_pct", "units", "roi"]


def second_half_table(conn) -> pd.DataFrame:
    """Every locked 2H play, newest first; graded on the 90-minute score less the 1H score, at the locked price."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='soccer_second_half'").fetchone()
    if not exists:
        return pd.DataFrame(columns=SECOND_COLS)
    out = []
    for r in map(dict, conn.execute(
            "SELECT s.*, g.state, g.home_90, g.away_90 FROM soccer_second_half s "
            "LEFT JOIN soccer_games g ON g.event_id = s.event_id ORDER BY s.start_time DESC, s.event_id")):
        if r["home_1h"] is None or r["away_1h"] is None:
            continue
        final = r["state"] == "final" and r["home_90"] is not None and r["away_90"] is not None
        h2, a2 = (r["home_90"] - r["home_1h"], r["away_90"] - r["away_1h"]) if final else (None, None)
        for p in _second_half_plays(r):
            result = grade(p["market"], p["pick_side"], p["line"], h2, a2) if final else "pending"
            out.append({"event_id": r["event_id"], "comp": r["comp"], "start_time": r["start_time"],
                        "et_date": pd.Timestamp(r["start_time"]).tz_convert(TZ).strftime("%Y-%m-%d"),
                        "home_abbr": r["home_abbr"], "away_abbr": r["away_abbr"], "home_1h": r["home_1h"],
                        "away_1h": r["away_1h"], "home_2h": h2, "away_2h": a2, "state": r["state"], **p,
                        "pick": r[f"{p['pick_side']}_abbr"] if p["market"] == "ml" else p["pick_side"].capitalize(),
                        "result": result, "units": None if result == "pending" else _profit(result, p["price"]),
                        "captured_at": r["captured_at"]})
    return pd.DataFrame(out, columns=SECOND_COLS).astype(object)


def second_half_summary(plays: pd.DataFrame) -> pd.DataFrame:
    """W-L and units at the locked prices: all days and each US/Eastern day, for both markets and each one."""
    if plays is None or plays.empty:
        return pd.DataFrame(columns=SECOND_SUMMARY_COLS)
    groups = [("all", "ALL", plays)] + [("day", d, g) for d, g in sorted(plays.groupby("et_date"), reverse=True)]
    out = []
    for scope, date, group in groups:
        for market in ("ALL", "ml", "total"):
            part = group if market == "ALL" else group[group["market"] == market]
            if part.empty:
                continue
            res = list(part["result"])
            wins = sum(x in ("win", "half_win") for x in res)
            losses = sum(x in ("loss", "half_loss") for x in res)
            pending = res.count("pending")
            graded = len(res) - pending
            units = round(float(sum(u for u in part["units"] if u is not None and u == u)), 4)
            out.append({"scope": scope, "et_date": date, "market": market, "tracked": len(res), "pending": pending,
                        "wins": wins, "losses": losses, "pushes": res.count("push"), "graded": graded,
                        "win_pct": wins / (wins + losses) if wins + losses else None, "units": units,
                        "roi": units / graded if graded else None})
    return pd.DataFrame(out, columns=SECOND_SUMMARY_COLS).astype(object)
