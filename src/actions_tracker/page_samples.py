"""A recent copy of Action Network pages that are not parsed yet (soccer).

The phone fetches them on the home network like every other league page and keeps them, gzip-compressed, in the
committed database, so their parser can be written and tested against the real page. Nothing else reads them.
"""

import gzip
import json
import sqlite3
from collections import Counter

import pandas as pd

from actions_tracker.fetch import fetch_bygame, fetch_picks
from actions_tracker.parse import extract_next_data

SCHEMA = ("CREATE TABLE IF NOT EXISTS page_samples(name TEXT PRIMARY KEY, fetched_at TEXT, html_gz BLOB, "
          "error TEXT)")
STATS_SCHEMA = ("CREATE TABLE IF NOT EXISTS page_sample_stats(name TEXT, fetched_at TEXT, profiles INTEGER, "
                "games INTEGER, games_with_experts INTEGER, picks INTEGER, types TEXT, PRIMARY KEY(name, fetched_at))")
EVERY_H = 2             # often enough to see when the soccer experts post their picks
LEAGUES = ("soccer",)


def _save(conn: sqlite3.Connection, name: str, now: str, html: str | None = None, error: str | None = None) -> None:
    blob = gzip.compress(html.encode("utf-8")) if html is not None else None
    conn.execute("INSERT INTO page_samples(name, fetched_at, html_gz, error) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(name) DO UPDATE SET fetched_at=excluded.fetched_at, html_gz=excluded.html_gz, "
                 "error=excluded.error", (name, now, blob, error))


def _board(html: str) -> tuple[list, list]:
    """(expert profiles with their picks, games on the board with their experts) of an Action Network picks page."""
    props = extract_next_data(html).get("props", {}).get("pageProps", {})
    profiles = ((props.get("initialExpertsResponse") or {}).get("response") or {}).get("profiles") or []
    games = ((props.get("scoreboardResponse") or {}).get("response") or {}).get("games") or []
    return profiles, games


def _stats(html: str) -> dict:
    """How much the page holds: experts, games, games with an expert, picks by type (unknown types included)."""
    profiles, games = _board(html)
    types = Counter(str(k.get("type")) for pr in profiles for k in pr.get("picks") or [])
    types.update(str(k.get("type")) for g in games for pr in g.get("experts") or [] for k in pr.get("picks") or [])
    return {"profiles": len(profiles), "games": len(games),
            "games_with_experts": sum(1 for g in games if g.get("experts")), "picks": sum(types.values()),
            "types": json.dumps(dict(types), sort_keys=True)}


def _first_game_id(html: str) -> int | None:
    """A game to open the By-Game page with: one that has a pick, else one with experts, else any on the board."""
    profiles, games = _board(html)
    for pr in profiles:
        for k in pr.get("picks") or []:
            if isinstance(k.get("game_id"), int):
                return k["game_id"]
    for g in sorted(games, key=lambda g: not g.get("experts")):
        if isinstance(g.get("id"), int):
            return g["id"]
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
    """Save each league's picks and By-Game page when the last copy is older than EVERY_H hours, note how many
    experts, games and picks (by type) the picks page held, and keep the latest copy that had picks apart
    ("<league>_picks_with_picks"), so an empty page later never replaces it. A page that fails is noted with its
    error (and retried after EVERY_H hours); it never stops the run. Returns pages saved."""
    conn.execute(SCHEMA)
    conn.execute(STATS_SCHEMA)
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
            stats = _stats(html)
            conn.execute("INSERT OR REPLACE INTO page_sample_stats(name, fetched_at, profiles, games, "
                         "games_with_experts, picks, types) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (f"{league}_picks", now, stats["profiles"], stats["games"], stats["games_with_experts"],
                          stats["picks"], stats["types"]))
            if stats["picks"]:
                _save(conn, f"{league}_picks_with_picks", now, html=html)
        except Exception:  # noqa: BLE001 - the counts are a convenience
            pass
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
