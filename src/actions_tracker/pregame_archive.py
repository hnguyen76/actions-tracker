"""Persist the pregame context shown on the dashboard for later comparison."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd


SCHEMA = """
CREATE TABLE IF NOT EXISTS pregame_snapshots (
    game_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    start_time TEXT,
    league TEXT,
    match TEXT,
    captured_at TEXT NOT NULL,
    capture_phase TEXT NOT NULL DEFAULT 'pregame',
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY (game_id, market)
)
"""


def _records(frame: pd.DataFrame, game_id: int, market: str | None = None) -> list[dict]:
    if frame is None or frame.empty or "game_id" not in frame.columns:
        return []
    selected = frame[pd.to_numeric(frame["game_id"], errors="coerce") == game_id]
    if market is not None and "market" in selected.columns:
        selected = selected[selected["market"].astype(str) == market]
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _pregame_comments(frame: pd.DataFrame, game_id: int, market: str, start_time: object) -> list[dict]:
    records = _records(frame, game_id, market)
    start = _parse_time(start_time)
    return [r for r in records if r.get("expert_note") and (
        start is None or (created := _parse_time(r.get("created_at"))) is None or created <= start
    )]


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        return None if pd.isna(parsed) else parsed.to_pydatetime()
    except (TypeError, ValueError):
        return None


def capture_snapshots(conn: sqlite3.Connection, tables: dict[str, pd.DataFrame], now: str) -> int:
    """Save the latest pregame view. A snapshot is never overwritten after kickoff."""
    conn.execute(SCHEMA)
    candidates: dict[tuple[int, str], dict] = {}
    board = tables.get("Upcoming_Board", pd.DataFrame())
    for row in json.loads(board.to_json(orient="records", date_format="iso")):
        game_id, market = int(row["game_id"]), str(row["market"])
        row["match"] = f'{row.get("away_abbr", "")}@{row.get("home_abbr", "")}'
        candidates[(game_id, market)] = row

    # A lightweight live refresh may be the first run after kickoff. Its news/picks are
    # already timestamp-validated as pregame, so preserve them once without overwriting.
    in_play = tables.get("In_Play", pd.DataFrame())
    if in_play is not None and not in_play.empty:
        for row in json.loads(in_play.to_json(orient="records", date_format="iso")):
            if row.get("source") != "Cách của bạn":
                continue
            key = (int(row["game_id"]), str(row["market"]))
            candidates.setdefault(key, row)

    now_dt = _parse_time(now) or datetime.now(timezone.utc)
    # Preserve newly completed rows too. The news/pick loaders keep only their
    # timestamp-validated pregame records for the first 12 hours after kickoff.
    past = tables.get("Past_Plays", pd.DataFrame())
    if past is not None and not past.empty:
        for row in json.loads(past.to_json(orient="records", date_format="iso")):
            start = _parse_time(row.get("start_time"))
            if start and now_dt - timedelta(hours=12) <= start <= now_dt:
                candidates.setdefault((int(row["game_id"]), str(row["market"])), row)

    written = 0
    for (game_id, market), row in candidates.items():
        start = _parse_time(row.get("start_time"))
        phase = "pregame" if start and now_dt < start else "late_archive"
        exists = conn.execute(
            "SELECT 1 FROM pregame_snapshots WHERE game_id=? AND market=?", (game_id, market)
        ).fetchone()
        if phase != "pregame" and exists:
            continue
        board_records = _records(board, game_id, market)
        snapshot = {
            "board": board_records or _records(past, game_id, market),
            "decisions": _records(tables.get("Decisions"), game_id, market),
            "signals": _records(tables.get("Signals"), game_id, market),
            "news": _records(tables.get("Match_News"), game_id),
            "ats": _records(tables.get("Media_ATS"), game_id),
            "winner": _records(tables.get("Media_Picks"), game_id),
            "weather": _records(tables.get("Weather"), game_id),
            "comments": _pregame_comments(tables.get("Picks"), game_id, market, row.get("start_time")),
        }
        conn.execute(
            """INSERT INTO pregame_snapshots
               (game_id, market, start_time, league, match, captured_at, capture_phase, snapshot_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(game_id, market) DO UPDATE SET
                 start_time=excluded.start_time, league=excluded.league, match=excluded.match,
                 captured_at=excluded.captured_at, capture_phase=excluded.capture_phase,
                 snapshot_json=excluded.snapshot_json""",
            (game_id, market, row.get("start_time"), row.get("league"), row.get("match"), now, phase,
             json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))),
        )
        written += 1
    conn.commit()
    return written


def load_snapshots(conn: sqlite3.Connection) -> pd.DataFrame:
    conn.execute(SCHEMA)
    return pd.read_sql_query(
        "SELECT game_id, market, start_time, league, match, captured_at, capture_phase, snapshot_json "
        "FROM pregame_snapshots ORDER BY start_time DESC, game_id, market", conn
    )


def refresh_snapshots(conn: sqlite3.Connection, tables: dict[str, pd.DataFrame], now: str) -> int:
    written = capture_snapshots(conn, tables, now)
    tables["Pregame_Snapshots"] = load_snapshots(conn)
    return written
