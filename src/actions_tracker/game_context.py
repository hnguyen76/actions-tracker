"""Context that helps judge the side being bet (free ESPN data, refreshed at most hourly per game).

- opening lines: ESPN lists the opening and the current DraftKings line; the opening one is kept here;
- rest: days since each team's previous game (ESPN game summary "lastFiveGames");
- quarterbacks: QBs listed Out / Doubtful / Questionable on the ESPN injury report.
"""

import json
import sqlite3

import pandas as pd
import requests

SUMMARY = {"nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
           "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"}
DEPTH = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/depthcharts"
REFRESH_H = 1.0
DEPTH_REFRESH_H = 24.0  # NFL depth charts are read at most once a day per team
QB_STATUSES = ("Out", "Doubtful", "Questionable")  # injured-reserve QBs are long-term backups, left out
CONTEXT_COLS = ["game_id", "home_rest_days", "away_rest_days", "home_qb", "away_qb", "updated_at"]
OPEN_COLS = ["game_id", "market", "side", "line", "odds"]


def schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS opening_lines(game_id INTEGER, market TEXT, side TEXT, line REAL,
        odds INTEGER, captured_at TEXT, PRIMARY KEY(game_id, market, side))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS game_context(game_id INTEGER PRIMARY KEY, home_rest_days REAL,
        away_rest_days REAL, home_qb TEXT, away_qb TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS depth_qb(league TEXT, team_id TEXT, qb TEXT, updated_at TEXT,
        PRIMARY KEY(league, team_id))""")


def _num(v):
    if v is None or v in ("", "OFF"):
        return None
    try:
        return float(str(v).lstrip("ou").replace("+", ""))
    except ValueError:
        return None


def parse_open(odds) -> list[dict]:
    """Opening spread / total from ESPN's odds block (DraftKings)."""
    if not odds:
        return []
    o = odds[0]
    out = []
    for market, block, sides in (("spread", o.get("pointSpread") or {}, ("home", "away")),
                                 ("total", o.get("total") or {}, ("over", "under"))):
        for side in sides:
            c = (block.get(side) or {}).get("open") or {}
            line = _num(c.get("line"))
            if line is not None:
                odds_v = _num(c.get("odds"))
                out.append({"market": market, "side": side, "line": line, "odds": None if odds_v is None else int(odds_v)})
    return out


def store_open(conn: sqlite3.Connection, rows: dict, now: str) -> None:
    """rows: {game_id: [parse_open(...) items]} - the opening line never changes, so it is written once."""
    schema(conn)
    conn.executemany("INSERT OR IGNORE INTO opening_lines VALUES (?,?,?,?,?,?)",
                     [(gid, x["market"], x["side"], x["line"], x["odds"], now) for gid, xs in rows.items() for x in xs])


def parse_summary(data: dict, kickoff: str) -> dict:
    comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
    side_of = {str(c.get("team", {}).get("id")): c.get("homeAway") for c in comp.get("competitors", [])}
    out = {"home_rest_days": None, "away_rest_days": None, "home_qb": None, "away_qb": None,
           "home_team_id": None, "away_team_id": None, "home_passer": None, "away_passer": None,
           "home_qb_injuries": [], "away_qb_injuries": []}
    for tid, side in side_of.items():
        if side in ("home", "away"):
            out[f"{side}_team_id"] = tid
    for team in data.get("leaders") or []:  # before kickoff these are season leaders
        side = side_of.get(str((team.get("team") or {}).get("id")))
        for cat in team.get("leaders") or []:
            if cat.get("name") == "passingYards" and cat.get("leaders") and side in ("home", "away"):
                out[f"{side}_passer"] = (cat["leaders"][0].get("athlete") or {}).get("displayName")
    start = pd.Timestamp(kickoff)
    for team in data.get("lastFiveGames") or []:
        side = side_of.get(str((team.get("team") or {}).get("id")))
        dates = [pd.Timestamp(ev["gameDate"]) for ev in team.get("events") or [] if ev.get("gameDate")]
        dates = [d for d in dates if d < start - pd.Timedelta(hours=6)]
        if side in ("home", "away") and dates:
            out[f"{side}_rest_days"] = round((start - max(dates)).total_seconds() / 86400, 1)
    for team in data.get("injuries") or []:
        side = side_of.get(str((team.get("team") or {}).get("id")))
        qbs = [((i.get("athlete") or {}).get("displayName"), i.get("status")) for i in team.get("injuries") or []
               if ((i.get("athlete") or {}).get("position") or {}).get("abbreviation") == "QB" and i.get("status") in QB_STATUSES]
        if side in ("home", "away"):
            out[f"{side}_qb_injuries"] = qbs
    return out


def _key(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def starter_injury(injuries, starter):
    """'Name (Status)' when the starting QB is on the injury report; backups are ignored."""
    if not starter:
        return None
    hit = [f"{n} ({st})" for n, st in injuries if _key(n) == _key(starter)]
    return hit[0] if hit else None


def nfl_starter(conn, team_id, now, get):
    """QB1 on the ESPN depth chart (cached a day); None when unavailable."""
    row = conn.execute("SELECT qb, updated_at FROM depth_qb WHERE league='nfl' AND team_id=?", (str(team_id),)).fetchone()
    if row and pd.Timestamp(now) - pd.Timestamp(row[1]) < pd.Timedelta(hours=DEPTH_REFRESH_H):
        return row[0]
    qb = None
    try:
        r = get(DEPTH.format(team=team_id), timeout=30, headers={"User-Agent": "actions-tracker/1.0"})
        if r.status_code == 200:
            for chart in r.json().get("depthchart") or []:
                athletes = ((chart.get("positions") or {}).get("qb") or {}).get("athletes") or []
                if athletes:
                    qb = athletes[0].get("displayName")
                    break
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return row[0] if row else None
    conn.execute("INSERT OR REPLACE INTO depth_qb VALUES ('nfl', ?, ?, ?)", (str(team_id), qb, now))
    return qb


def store_context(conn: sqlite3.Connection, league: str, games: dict, now: str, get=requests.get) -> int:
    """games: {game_id: {"event_id", "start_time"}}; one ESPN summary request per game, at most hourly."""
    schema(conn)
    if league not in SUMMARY:
        return 0
    done = 0
    for gid, g in games.items():
        last = conn.execute("SELECT updated_at FROM game_context WHERE game_id=?", (gid,)).fetchone()
        if last and pd.Timestamp(now) - pd.Timestamp(last[0]) < pd.Timedelta(hours=REFRESH_H):
            continue
        try:
            r = get(SUMMARY[league], params={"event": g["event_id"]}, timeout=30, headers={"User-Agent": "actions-tracker/1.0"})
            if r.status_code != 200:
                continue
            c = parse_summary(r.json(), g["start_time"])
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
        for side in ("home", "away"):
            starter = None
            if league == "nfl" and c[f"{side}_team_id"]:
                starter = nfl_starter(conn, c[f"{side}_team_id"], now, get)
            starter = starter or c[f"{side}_passer"]  # college: the season passing leader stands in for QB1
            c[f"{side}_qb"] = starter_injury(c[f"{side}_qb_injuries"], starter)
        conn.execute("INSERT OR REPLACE INTO game_context VALUES (?,?,?,?,?,?)",
                     (gid, c["home_rest_days"], c["away_rest_days"], c["home_qb"], c["away_qb"], now))
        done += 1
    conn.commit()
    return done


def context_tables(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    schema(conn)
    ctx = pd.DataFrame([dict(r) for r in conn.execute("SELECT * FROM game_context")], columns=CONTEXT_COLS)
    opn = pd.DataFrame([dict(r) for r in conn.execute("SELECT game_id, market, side, line, odds FROM opening_lines")],
                       columns=OPEN_COLS)
    return ctx, opn


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)
