"""Find past games that still lack a final score, and the scoreboard queries that would return them.

The default scoreboard only shows today (daily leagues) or the current week (NFL/NCAAF), so games
that finished between button clicks are fetched again by date or week.
"""

import sqlite3

import pandas as pd

from actions_tracker.config import TZ

WEEKLY_LEAGUES = {"nfl", "ncaaf"}
GRACE_HOURS = 4
LOOKBACK_DAYS = 10
MAX_QUERIES = 5
_DONE = ("complete", "cancelled", "postponed")


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def stale_games(conn: sqlite3.Connection, league: str, now: str) -> list[dict]:
    """Games that should be over (started > GRACE_HOURS ago, within LOOKBACK_DAYS) but are not final."""
    now_ts = pd.Timestamp(now)
    rows = conn.execute(
        f"""SELECT id, week, start_time FROM games
            WHERE league = ? AND start_time < ? AND start_time >= ?
              AND (status IS NULL OR status NOT IN ({",".join("?" * len(_DONE))}))""",
        (league, _iso(now_ts - pd.Timedelta(hours=GRACE_HOURS)), _iso(now_ts - pd.Timedelta(days=LOOKBACK_DAYS)), *_DONE),
    ).fetchall()
    return [dict(r) for r in rows]


def backfill_queries(conn: sqlite3.Connection, league: str, now: str) -> list[str]:
    """Scoreboard query strings (without '&'), oldest first, at most MAX_QUERIES."""
    games = stale_games(conn, league, now)
    if league in WEEKLY_LEAGUES:
        keys = sorted({g["week"] for g in games if g["week"] is not None})
        return [f"week={w}" for w in keys][:MAX_QUERIES]
    dates = sorted({
        pd.Timestamp(g["start_time"]).tz_convert(TZ).strftime("%Y%m%d") for g in games
    })
    return [f"date={d}" for d in dates][:MAX_QUERIES]
