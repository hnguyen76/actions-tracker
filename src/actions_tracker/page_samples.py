"""A recent copy of Action Network pages that are not parsed yet (soccer).

The phone fetches them on the home network like every other league page and keeps them, gzip-compressed, in the
committed database, so their parser can be written and tested against the real page. Nothing else reads them.
"""

import gzip
import sqlite3

import pandas as pd

from actions_tracker.fetch import fetch_bygame, fetch_picks
from actions_tracker.parse import extract_next_data

SCHEMA = ("CREATE TABLE IF NOT EXISTS page_samples(name TEXT PRIMARY KEY, fetched_at TEXT, html_gz BLOB, "
          "error TEXT)")
EVERY_H = 12            # one copy of each page is enough; refresh it twice a day
LEAGUES = ("soccer",)


def _save(conn: sqlite3.Connection, name: str, now: str, html: str | None = None, error: str | None = None) -> None:
    blob = gzip.compress(html.encode("utf-8")) if html is not None else None
    conn.execute("INSERT INTO page_samples(name, fetched_at, html_gz, error) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(name) DO UPDATE SET fetched_at=excluded.fetched_at, html_gz=excluded.html_gz, "
                 "error=excluded.error", (name, now, blob, error))


def _first_game_id(html: str) -> int | None:
    """Any game id on the picks page, to open its By-Game page (which lists every game on the board)."""
    stack = [extract_next_data(html)]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            value = item.get("game_id")
            if isinstance(value, int):
                return value
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


def _error(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


def capture(conn: sqlite3.Connection, fetcher, now: str, leagues=LEAGUES) -> int:
    """Save each league's picks and By-Game page when the last copy is older than EVERY_H hours. A page that
    fails is noted with its error (and retried after EVERY_H hours); it never stops the run. Returns pages saved."""
    conn.execute(SCHEMA)
    saved = 0
    for league in leagues:
        last = conn.execute("SELECT fetched_at FROM page_samples WHERE name = ?", (f"{league}_picks",)).fetchone()
        if last and last[0] and pd.Timestamp(now) - pd.Timestamp(last[0]) < pd.Timedelta(hours=EVERY_H):
            continue
        try:
            html = fetch_picks(fetcher, league)
        except Exception as e:  # noqa: BLE001 - a sample must never fail the collection run
            _save(conn, f"{league}_picks", now, error=_error(e))
            continue
        _save(conn, f"{league}_picks", now, html=html)
        saved += 1
        try:
            game_id = _first_game_id(html)
            if game_id is None:
                raise ValueError("no game id on the picks page")
            _save(conn, f"{league}_bygame", now, html=fetch_bygame(fetcher, league, game_id))
            saved += 1
        except Exception as e:  # noqa: BLE001
            _save(conn, f"{league}_bygame", now, error=_error(e))
    conn.commit()
    return saved
