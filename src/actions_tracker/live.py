"""ESPN's public scoreboard (free, no key) as the source of lines, live scores and final scores.

Replaces The Odds API (paid credits) since 2026-11-14:
- lines: DraftKings spread / total / moneyline as shown by ESPN, stored for every picked game that has not
  started; the last write before kickoff is the closing line (same rule as before);
- live scores: games in progress, for the "Điểm" column and the in-play card;
- finals: a game ESPN reports as final is graded right away.
One request per league and US/Eastern date that has a picked game to price or to score.
"""

import json
import math
import re
import sqlite3

import pandas as pd
import requests

from actions_tracker import db
from actions_tracker.config import TZ
from actions_tracker.matching import match_events, normalize
from actions_tracker.weather import parse_venue, store_weather
from actions_tracker.game_context import parse_open, store_context, store_open

ESPN = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={d}",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={d}&groups=80&limit=300",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}",
}
ESPN_CORE = {
    "nfl": "football/leagues/nfl",
    "ncaaf": "football/leagues/college-football",
    "nba": "basketball/leagues/nba",
}
GAME_HOURS = 72   # picked games that kicked off within this many hours and are not graded get a score
LINE_LEAD_H = 36  # picked games starting within this many hours get their lines refreshed
SCHEMA = ("CREATE TABLE IF NOT EXISTS live_scores(game_id INTEGER PRIMARY KEY, away_score INTEGER, home_score INTEGER, "
          "state TEXT, detail TEXT, updated_at TEXT)")
ID_SCHEMA = ("CREATE TABLE IF NOT EXISTS live_game_ids(game_id INTEGER PRIMARY KEY, espn_event_id TEXT NOT NULL)")
DETAIL_SCHEMA = ("CREATE TABLE IF NOT EXISTS live_details(game_id INTEGER PRIMARY KEY, details_json TEXT)")
SECOND_HALF_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS second_half_snapshots("
    "game_id INTEGER PRIMARY KEY, league TEXT NOT NULL, espn_event_id TEXT NOT NULL, captured_at TEXT NOT NULL, "
    "away_score_1h INTEGER NOT NULL, home_score_1h INTEGER NOT NULL, first_spread_away REAL, "
    "first_spread_home REAL, first_total REAL, second_spread_away REAL, second_spread_home REAL, "
    "second_total REAL)"
)


class LiveError(Exception):
    pass


def _num(v):
    if v is None or v in ("", "OFF"):
        return None
    try:
        return float(str(v).lstrip("ou").replace("+", ""))
    except ValueError:
        return None


def _odds(v):
    n = _num(v)
    return None if n is None else int(n)


def parse_odds(odds) -> list[dict]:
    """[{market, side, line, odds}] from the first provider ESPN lists (DraftKings)."""
    if not odds:
        return []
    o = odds[0]
    out = []
    ps, tot, ml = o.get("pointSpread") or {}, o.get("total") or {}, o.get("moneyline") or {}
    for side in ("home", "away"):
        c = (ps.get(side) or {}).get("close") or {}
        if _num(c.get("line")) is not None:
            out.append({"market": "spread", "side": side, "line": _num(c.get("line")), "odds": _odds(c.get("odds"))})
    if not any(x["market"] == "spread" for x in out) and o.get("spread") is not None:
        out += [{"market": "spread", "side": "home", "line": float(o["spread"]), "odds": None},
                {"market": "spread", "side": "away", "line": -float(o["spread"]), "odds": None}]
    for side in ("over", "under"):
        c = (tot.get(side) or {}).get("close") or {}
        line = _num(c.get("line")) if c.get("line") else o.get("overUnder")
        if line is not None:
            out.append({"market": "total", "side": side, "line": float(line), "odds": _odds(c.get("odds"))})
    for side in ("home", "away"):
        c = (ml.get(side) or {}).get("close") or {}
        if _odds(c.get("odds")) is not None:
            out.append({"market": "ml", "side": side, "line": None, "odds": _odds(c.get("odds"))})
    return out


def _score_int(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(n) if math.isfinite(n) and n >= 0 and n.is_integer() else None


def _text(value):
    return (value.strip() or None) if isinstance(value, str) else None


def _team_id(competitor):
    team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
    value = team.get("id") or competitor.get("id")
    return str(value) if value is not None and not isinstance(value, bool) and str(value).isdigit() else None


def _period_scores(competitor):
    lines = competitor.get("linescores")
    if not isinstance(lines, list):
        return None
    values = {}
    for item in lines:
        if not isinstance(item, dict):
            continue
        period, score = _score_int(item.get("period")), _score_int(item.get("value"))
        if period is not None and 1 <= period <= 20 and score is not None:
            values[period] = score
    return [values.get(period) for period in range(1, max(values) + 1)] if values else None


def parse_situation(event: dict, competition: dict | None = None) -> dict | None:
    """Only explicit scoreboard situation fields; missing quarters stay missing instead of becoming zero."""
    comp = competition if competition is not None else (event.get("competitions") or [{}])[0]
    if not isinstance(comp, dict):
        return None
    competitors = comp.get("competitors") or []
    side = {c.get("homeAway"): c for c in competitors if isinstance(c, dict)} if isinstance(competitors, list) else {}
    away, home = side.get("away", {}), side.get("home", {})
    away_id, home_id = _team_id(away), _team_id(home)
    raw = comp.get("situation") if isinstance(comp.get("situation"), dict) else {}
    raw_status = event.get("status") or comp.get("status") or {}
    status = raw_status if isinstance(raw_status, dict) else {}
    owner = str(raw["possession"]) if raw.get("possession") is not None else None
    possession = "away" if away_id and owner == away_id else "home" if home_id and owner == home_id else None
    period = _score_int(status.get("period"))
    out = {"possession": possession, "possession_text": _text(raw.get("possessionText")),
           "down_distance": _text(raw.get("shortDownDistanceText")) or _text(raw.get("downDistanceText")),
           "red_zone": raw["isRedZone"] if isinstance(raw.get("isRedZone"), bool) else None,
           "period": period if period is not None and 1 <= period <= 20 else None, "clock": _text(status.get("displayClock")),
           "away_period_scores": _period_scores(away), "home_period_scores": _period_scores(home),
           "away_espn_id": away_id, "home_espn_id": home_id}
    return out if any(v is not None for k, v in out.items() if not k.endswith("_espn_id")) else None


def parse_scoreboard(data: dict) -> list[dict]:
    out = []
    for e in data.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        side = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in side or "away" not in side:
            continue
        status = (e.get("status") or {}).get("type") or {}

        def score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None
        out.append({"event_id": str(e.get("id")), "commence_time": e.get("date"),
                    "home_name": side["home"]["team"].get("displayName"),
                    "away_name": side["away"]["team"].get("displayName"),
                    "home_score": score(side["home"]), "away_score": score(side["away"]),
                    "state": status.get("state"), "detail": status.get("shortDetail"),
                    "is_halftime": status.get("name") == "STATUS_HALFTIME"
                    or bool(re.fullmatch(r"halftime", str(status.get("shortDetail") or status.get("description") or ""), re.I)),
                    "situation": parse_situation(e, comp),
                    "venue": parse_venue(e, comp),
                    "open": parse_open(comp.get("odds")),
                    "lines": parse_odds(comp.get("odds"))})
    return out


def _fetch_json(get, url: str):
    try:
        response = get(url, timeout=30, headers={"User-Agent": "actions-tracker/1.0"})
    except Exception:  # noqa: BLE001 - halftime odds must never stop live-score collection
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    try:
        body = response.json()
    except (TypeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _prop_ref(market: dict | None) -> str | None:
    ref = str(((market or {}).get("propBets") or {}).get("$ref") or "")
    if not re.match(r"^https?://sports\.core\.api\.espn\.com/", ref):
        return None
    ref = re.sub(r"^http:", "https:", ref)
    return f"{ref}{'&' if '?' in ref else '?'}limit=1000"


def _half_props(body: dict | None, half: str, away_id: str | None, home_id: str | None) -> dict:
    out = {"away": None, "home": None, "total": None}
    for item in (body or {}).get("items", []):
        if not isinstance(item, dict):
            continue
        name = str(((item.get("type") or {}).get("name")) or "")
        value = _num((((item.get("current") or {}).get("target") or {}).get("value")))
        if value is None:
            continue
        if re.fullmatch(fr"{half} half spread", name, re.I):
            team_ref = str(((item.get("team") or {}).get("$ref")) or "")
            match = re.search(r"/teams/(\d+)", team_ref)
            team_id = match.group(1) if match else None
            if team_id and team_id == away_id:
                out["away"] = value
            elif team_id and team_id == home_id:
                out["home"] = value
        elif re.fullmatch(fr"{half} half total", name, re.I) and out["total"] is None:
            out["total"] = value
    if out["away"] is None and out["home"] is not None:
        out["away"] = -out["home"]
    if out["home"] is None and out["away"] is not None:
        out["home"] = -out["away"]
    return out


def _halftime_odds(get, league: str, event: dict) -> tuple[dict, dict]:
    empty = {"away": None, "home": None, "total": None}
    event_id = str(event.get("event_id") or "")
    if league not in ESPN_CORE or not event_id.isdigit():
        return empty.copy(), empty.copy()
    url = (f"https://sports.core.api.espn.com/v2/sports/{ESPN_CORE[league]}/events/{event_id}/"
           f"competitions/{event_id}/odds?lang=en&region=us&limit=100")
    odds = _fetch_json(get, url)
    items = odds.get("items", []) if odds else []
    pregame = next((x for x in items if re.fullmatch(r"draftkings", str(((x or {}).get("provider") or {}).get("name") or ""), re.I)), None)
    live_market = next((x for x in items if re.search(r"live", str(((x or {}).get("provider") or {}).get("name") or ""), re.I)), None)
    situation = event.get("situation") or {}
    away_id, home_id = situation.get("away_espn_id"), situation.get("home_espn_id")
    pregame_ref, live_ref = _prop_ref(pregame), _prop_ref(live_market)
    first = _half_props(_fetch_json(get, pregame_ref) if pregame_ref else None, "1st", away_id, home_id)
    second = _half_props(_fetch_json(get, live_ref) if live_ref else None, "2nd", away_id, home_id)
    return first, second


def _store_halftime_snapshots(conn: sqlite3.Connection, league: str, scored: dict, verified_ids: set[int],
                              now: str, get) -> int:
    conn.execute(SECOND_HALF_SCHEMA)
    saved = 0
    for game_id, event in scored.items():
        if game_id not in verified_ids or event.get("state") != "in" or event.get("is_halftime") is not True:
            continue
        away_score, home_score = event.get("away_score"), event.get("home_score")
        if away_score is None or home_score is None:
            continue
        first, second = _halftime_odds(get, league, event)
        values = (game_id, league, event["event_id"], now, away_score, home_score,
                  first["away"], first["home"], first["total"],
                  second["away"], second["home"], second["total"])
        conn.execute(
            "INSERT INTO second_half_snapshots(game_id, league, espn_event_id, captured_at, away_score_1h, "
            "home_score_1h, first_spread_away, first_spread_home, first_total, second_spread_away, "
            "second_spread_home, second_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(game_id) DO UPDATE SET captured_at=excluded.captured_at, "
            "away_score_1h=excluded.away_score_1h, home_score_1h=excluded.home_score_1h, "
            "first_spread_away=COALESCE(excluded.first_spread_away, second_half_snapshots.first_spread_away), "
            "first_spread_home=COALESCE(excluded.first_spread_home, second_half_snapshots.first_spread_home), "
            "first_total=COALESCE(excluded.first_total, second_half_snapshots.first_total), "
            "second_spread_away=COALESCE(excluded.second_spread_away, second_half_snapshots.second_spread_away), "
            "second_spread_home=COALESCE(excluded.second_spread_home, second_half_snapshots.second_spread_home), "
            "second_total=COALESCE(excluded.second_total, second_half_snapshots.second_total)", values)
        saved += 1
    return saved


def _iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _picked(conn: sqlite3.Connection, league: str, lo: str, hi: str, ungraded: bool) -> list[dict]:
    extra = "AND (status IS NULL OR status != 'complete') " if ungraded else ""
    rows = conn.execute(
        "SELECT id, start_time, home_name, away_name FROM games g WHERE league = ? AND start_time > ? "
        f"AND start_time <= ? {extra}AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id)", (league, lo, hi))
    return [dict(r) for r in rows]


def collect_espn(conn: sqlite3.Connection, league: str, now: str, get=requests.get, lines: bool = True) -> dict:
    """Lines for picked games about to start (unless lines=False), scores for picked games that started."""
    conn.execute(SCHEMA)
    conn.execute(ID_SCHEMA)
    conn.execute(DETAIL_SCHEMA)
    conn.execute(SECOND_HALF_SCHEMA)
    t = pd.Timestamp(now)
    started = _picked(conn, league, _iso(t - pd.Timedelta(hours=GAME_HOURS)), now, ungraded=True)
    upcoming = _picked(conn, league, now, _iso(t + pd.Timedelta(hours=LINE_LEAD_H)), ungraded=False) if lines else []
    counts = {"lines": 0, "priced_of": len(upcoming), "live": 0, "final": 0, "scored_of": len(started),
              "halftime_saved": 0}
    if league not in ESPN or not (started or upcoming):
        return counts
    dates = sorted({pd.Timestamp(g["start_time"]).tz_convert(TZ).strftime("%Y%m%d") for g in started + upcoming})
    events = []
    for d in dates:
        try:
            r = get(ESPN[league].format(d=d), timeout=30, headers={"User-Agent": "actions-tracker/1.0"})
        except requests.RequestException as e:
            raise LiveError(type(e).__name__) from None
        if r.status_code != 200:
            raise LiveError(f"HTTP {r.status_code}")
        events += parse_scoreboard(r.json())
    # lines only before kickoff (upsert_lines ignores started games), so the last write is the closing line
    priced = match_events(upcoming, [e for e in events if e["state"] == "pre"]) if upcoming else {}
    db.upsert_lines(conn, [{**x, "game_id": gid, "tickets_pct": None, "money_pct": None}
                           for gid, e in priced.items() for x in e["lines"]], now)
    if priced and league in ("nfl", "ncaaf"):  # game-time weather for the decision card; never fails the run
        try:
            starts = {g["id"]: g["start_time"] for g in upcoming}
            store_weather(conn, {gid: {"start_time": starts[gid], "venue": e.get("venue")} for gid, e in priced.items()},
                          now, get=get)
        except Exception:  # noqa: BLE001
            pass
        try:  # opening lines, rest days and quarterback status for the "Tín hiệu" column
            store_open(conn, {gid: e.get("open") or [] for gid, e in priced.items()}, now)
            store_context(conn, league, {gid: {"event_id": e["event_id"], "start_time": starts[gid]}
                                         for gid, e in priced.items()}, now, get=get)
        except Exception:  # noqa: BLE001
            pass
    scored = match_events(started, events) if started else {}
    # Browser polling can reuse a verified ESPN id without fuzzy-matching college team names.
    # Preserve the collector's existing score matching, but only retain exact normalized pairs here.
    games = {g["id"]: g for g in started + upcoming}
    ids = []
    for gid, event in (priced | scored).items():
        game = games[gid]
        event_id = event.get("event_id") or ""
        home, away = normalize(game.get("home_name")), normalize(game.get("away_name"))
        if (str(event_id).isdigit() and home and away
                and home == normalize(event.get("home_name")) and away == normalize(event.get("away_name"))):
            ids.append((gid, str(event_id)))
    conn.executemany("INSERT INTO live_game_ids(game_id, espn_event_id) VALUES (?, ?) "
                     "ON CONFLICT(game_id) DO UPDATE SET espn_event_id=excluded.espn_event_id", ids)
    counts["halftime_saved"] = _store_halftime_snapshots(conn, league, scored, {gid for gid, _ in ids}, now, get)
    rows = [(gid, e["away_score"], e["home_score"], e["state"], e["detail"], now) for gid, e in scored.items()
            if e["state"] in ("in", "post")]
    conn.executemany(
        "INSERT INTO live_scores(game_id, away_score, home_score, state, detail, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(game_id) DO UPDATE SET away_score=excluded.away_score, home_score=excluded.home_score, "
        "state=excluded.state, detail=excluded.detail, updated_at=excluded.updated_at", rows)
    conn.executemany("INSERT INTO live_details(game_id, details_json) VALUES (?, ?) "
                     "ON CONFLICT(game_id) DO UPDATE SET details_json=excluded.details_json",
                     [(gid, json.dumps(e["situation"], ensure_ascii=False, allow_nan=False))
                      for gid, e in scored.items() if e["state"] in ("in", "post")])
    finals = [(e["home_score"], e["away_score"], gid) for gid, e in scored.items()
              if e["state"] == "post" and e["home_score"] is not None and e["away_score"] is not None]
    conn.executemany("UPDATE games SET status = 'complete', home_score = ?, away_score = ? "
                     "WHERE id = ? AND (status IS NULL OR status != 'complete')", finals)
    conn.commit()
    counts.update(lines=sum(1 for e in priced.values() if e["lines"]),
                  live=sum(1 for r in rows if r[3] == "in"), final=len(finals))
    return counts


def collect_live(conn: sqlite3.Connection, league: str, now: str, get=requests.get) -> int:
    """How many started games got a live or final score (lines are refreshed too)."""
    c = collect_espn(conn, league, now, get=get)
    return c["live"] + c["final"]


LIVE_GAME_COLS = ["game_id", "league", "start_time", "home_name", "away_name", "home_abbr", "away_abbr",
                  "espn_event_id"]


def live_games_table(conn: sqlite3.Connection, now: str) -> pd.DataFrame:
    """Unfinished picked games the open dashboard may poll directly; never changes the database."""
    has_ids = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_game_ids'").fetchone()
    id_column = "i.espn_event_id" if has_ids else "NULL AS espn_event_id"
    join = "LEFT JOIN live_game_ids i ON i.game_id = g.id " if has_ids else ""
    t = pd.Timestamp(now)
    rows = conn.execute(
        "SELECT g.id AS game_id, g.league, g.start_time, g.home_name, g.away_name, g.home_abbr, g.away_abbr, "
        f"{id_column} FROM games g {join}"
        "WHERE g.league IN ('nfl', 'ncaaf', 'nba') AND (g.status IS NULL OR g.status != 'complete') "
        "AND g.start_time > ? AND g.start_time <= ? "
        "AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id) ORDER BY g.start_time, g.id",
        (_iso(t - pd.Timedelta(hours=GAME_HOURS)), _iso(t + pd.Timedelta(hours=LINE_LEAD_H))))
    return pd.DataFrame([dict(r) for r in rows], columns=LIVE_GAME_COLS)


SCORE_COLS = ["game_id", "away_score", "home_score", "state", "detail", "graded", "updated_at", "situation"]

SECOND_HALF_COLS = ["game_id", "league", "espn_event_id", "captured_at", "away_score_1h", "home_score_1h",
                    "first_spread_away", "first_spread_home", "first_total", "second_spread_away",
                    "second_spread_home", "second_total"]


def second_half_table(conn: sqlite3.Connection) -> pd.DataFrame:
    """Persisted halftime score and ESPN half markets for NFL, NCAAF and NBA."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='second_half_snapshots'").fetchone()
    if not exists:
        return pd.DataFrame(columns=SECOND_HALF_COLS)
    rows = [dict(row) for row in conn.execute(
        "SELECT game_id, league, espn_event_id, captured_at, away_score_1h, home_score_1h, first_spread_away, "
        "first_spread_home, first_total, second_spread_away, second_spread_home, second_total "
        "FROM second_half_snapshots ORDER BY captured_at DESC, game_id DESC")]
    return pd.DataFrame(rows, columns=SECOND_HALF_COLS)


def scores_table(conn: sqlite3.Connection, now: str) -> pd.DataFrame:
    """Score per game of the last days: graded final first, else the live score."""
    conn.execute(SCHEMA)
    has_details = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_details'").fetchone()
    details_column = "d.details_json" if has_details else "NULL AS details_json"
    details_join = "LEFT JOIN live_details d ON d.game_id = g.id " if has_details else ""
    since = (pd.Timestamp(now) - pd.Timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = []
    for r in conn.execute(
            "SELECT g.id, g.status, g.away_score, g.home_score, l.away_score AS la, l.home_score AS lh, l.state, l.detail, l.updated_at, "
            f"{details_column} FROM games g LEFT JOIN live_scores l ON l.game_id = g.id {details_join}"
            "WHERE g.start_time >= ? AND g.start_time <= ?",
            (since, now)):
        r = dict(r)
        try:
            situation = json.loads(r["details_json"]) if r["details_json"] else None
        except (TypeError, json.JSONDecodeError):
            situation = None
        if not isinstance(situation, dict):
            situation = None
        if r["status"] == "complete" and r["away_score"] is not None:
            rows.append({"game_id": r["id"], "away_score": r["away_score"], "home_score": r["home_score"],
                         "state": "final", "detail": "Hết trận", "graded": True, "updated_at": r["updated_at"],
                         "situation": situation})
        elif r["la"] is not None:
            rows.append({"game_id": r["id"], "away_score": r["la"], "home_score": r["lh"],
                         "state": "final" if r["state"] == "post" else "live", "detail": r["detail"], "graded": False,
                         "updated_at": r["updated_at"], "situation": situation})
    return pd.DataFrame(rows, columns=SCORE_COLS)
