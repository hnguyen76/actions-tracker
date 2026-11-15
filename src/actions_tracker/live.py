"""Live scores for games in progress, from ESPN's public scoreboard (free, no key) - display only.

Final scores and grading keep coming from The Odds API; this only fills the "Điểm" column while a game is
being played (and right after it ends, until the next Odds API scores call). One request per league and
US/Eastern date, made only when a game with picks is in progress.
"""

import sqlite3

import pandas as pd
import requests

from actions_tracker.config import TZ
from actions_tracker.matching import match_events

ESPN = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={d}",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={d}&groups=80&limit=300",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}",
}
GAME_HOURS = 12  # games kicked off within this many hours and not graded yet get a live or final score
SCHEMA = ("CREATE TABLE IF NOT EXISTS live_scores(game_id INTEGER PRIMARY KEY, away_score INTEGER, home_score INTEGER, "
          "state TEXT, detail TEXT, updated_at TEXT)")


class LiveError(Exception):
    pass


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
                    "state": status.get("state"), "detail": status.get("shortDetail")})
    return out


def games_in_progress(conn: sqlite3.Connection, league: str, now: str) -> list[dict]:
    since = (pd.Timestamp(now) - pd.Timedelta(hours=GAME_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = conn.execute(
        "SELECT id, start_time, home_name, away_name FROM games g WHERE league = ? AND start_time <= ? "
        "AND start_time >= ? AND (status IS NULL OR status != 'complete') "
        "AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id)", (league, now, since))
    return [dict(r) for r in rows]


def collect_live(conn: sqlite3.Connection, league: str, now: str, get=requests.get) -> int:
    """Store live scores for this league's games in progress; returns how many games were updated."""
    conn.execute(SCHEMA)
    games = games_in_progress(conn, league, now)
    if not games or league not in ESPN:
        return 0
    dates = sorted({pd.Timestamp(g["start_time"]).tz_convert(TZ).strftime("%Y%m%d") for g in games})
    events = []
    for d in dates:
        try:
            r = get(ESPN[league].format(d=d), timeout=30, headers={"User-Agent": "actions-tracker/1.0"})
        except requests.RequestException as e:
            raise LiveError(type(e).__name__) from None
        if r.status_code != 200:
            raise LiveError(f"HTTP {r.status_code}")
        events += parse_scoreboard(r.json())
    matched = match_events(games, events)
    rows = [(gid, e["away_score"], e["home_score"], e["state"], e["detail"], now) for gid, e in matched.items()
            if e["state"] in ("in", "post")]
    conn.executemany(
        "INSERT INTO live_scores(game_id, away_score, home_score, state, detail, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(game_id) DO UPDATE SET away_score=excluded.away_score, home_score=excluded.home_score, "
        "state=excluded.state, detail=excluded.detail, updated_at=excluded.updated_at", rows)
    # a game ESPN reports as final is graded right away; The Odds API scores later overwrite it with theirs
    finals = [(e["home_score"], e["away_score"], gid) for gid, e in matched.items()
              if e["state"] == "post" and e["home_score"] is not None and e["away_score"] is not None]
    conn.executemany("UPDATE games SET status = 'complete', home_score = ?, away_score = ? "
                     "WHERE id = ? AND (status IS NULL OR status != 'complete')", finals)
    conn.commit()
    return len(rows)


SCORE_COLS = ["game_id", "away_score", "home_score", "state", "detail", "graded"]


def scores_table(conn: sqlite3.Connection, now: str) -> pd.DataFrame:
    """Score per game of the last days: final (Odds API) first, else the live score."""
    conn.execute(SCHEMA)
    since = (pd.Timestamp(now) - pd.Timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = []
    for r in conn.execute(
            "SELECT g.id, g.status, g.away_score, g.home_score, l.away_score AS la, l.home_score AS lh, l.state, l.detail "
            "FROM games g LEFT JOIN live_scores l ON l.game_id = g.id WHERE g.start_time >= ? AND g.start_time <= ?",
            (since, now)):
        r = dict(r)
        if r["status"] == "complete" and r["away_score"] is not None:
            rows.append({"game_id": r["id"], "away_score": r["away_score"], "home_score": r["home_score"],
                         "state": "final", "detail": "Hết trận", "graded": True})
        elif r["la"] is not None:
            rows.append({"game_id": r["id"], "away_score": r["la"], "home_score": r["lh"],
                         "state": "final" if r["state"] == "post" else "live", "detail": r["detail"], "graded": False})
    return pd.DataFrame(rows, columns=SCORE_COLS)
