"""SQLite schema and idempotent upserts (spec §5). Rows are never deleted."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS experts(
    id INTEGER PRIMARY KEY, name TEXT, username TEXT, followers INTEGER,
    first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS games(
    id INTEGER PRIMARY KEY, league TEXT, season INTEGER, week INTEGER, start_time TEXT, status TEXT,
    home_team_id INTEGER, away_team_id INTEGER, home_abbr TEXT, away_abbr TEXT,
    home_score INTEGER, away_score INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS picks(
    id INTEGER PRIMARY KEY, expert_id INTEGER, game_id INTEGER, league TEXT,
    market TEXT CHECK(market IN ('spread','ml','total')),
    pick_side TEXT CHECK(pick_side IN ('home','away','over','under')),
    line REAL, odds INTEGER, units REAL, an_result TEXT,
    created_at TEXT, starts_at TEXT, settled_at TEXT, play_text TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS closing_lines(
    game_id INTEGER, market TEXT, side TEXT, line REAL, odds INTEGER,
    tickets_pct REAL, money_pct REAL, captured_at TEXT,
    PRIMARY KEY(game_id, market, side));
CREATE TABLE IF NOT EXISTS league_status(
    league TEXT PRIMARY KEY, last_success_at TEXT, last_error TEXT, last_error_at TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS pick_form(
    pick_id INTEGER PRIMARY KEY, expert_id INTEGER, league TEXT, captured_at TEXT,
    streak_type TEXT, streak_value INTEGER, units_30 REAL, wins_30 INTEGER, losses_30 INTEGER, pushes_30 INTEGER);
CREATE TABLE IF NOT EXISTS public_splits(
    game_id INTEGER, market TEXT, side TEXT, line REAL, odds INTEGER,
    tickets_pct REAL, money_pct REAL, captured_at TEXT,
    PRIMARY KEY(game_id, market, side));
CREATE TABLE IF NOT EXISTS rule_plays(
    rule_id TEXT, game_id INTEGER, market TEXT, bet_side TEXT, line REAL, odds INTEGER, basis TEXT,
    first_logged_at TEXT, logged_at TEXT,
    PRIMARY KEY(rule_id, game_id, market));
CREATE INDEX IF NOT EXISTS picks_game ON picks(game_id, market);
"""

GAME_COLS = ["id", "league", "season", "week", "start_time", "status", "home_team_id", "away_team_id",
             "home_abbr", "away_abbr", "home_score", "away_score", "home_name", "away_name", "odds_event_id"]
_NEW_GAME_COLS = {"home_name": "TEXT", "away_name": "TEXT", "odds_event_id": "TEXT"}
PICK_COLS = ["id", "expert_id", "game_id", "league", "market", "pick_side", "line", "odds", "units",
             "an_result", "created_at", "starts_at", "settled_at", "play_text"]
PICK_UPDATABLE = ["an_result", "settled_at", "odds", "line", "units"]
FORM_COLS = ["pick_id", "expert_id", "league", "streak_type", "streak_value", "units_30", "wins_30", "losses_30",
             "pushes_30"]
LINE_COLS = ["game_id", "market", "side", "line", "odds", "tickets_pct", "money_pct"]


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Spec §12: scores, status and lines now come from The Odds API, so drop what Action Network supplied
    the first time the new columns are added (runs once per database)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(games)")}
    missing = [c for c in _NEW_GAME_COLS if c not in cols]
    if not missing:
        return
    for c in missing:
        conn.execute(f"ALTER TABLE games ADD COLUMN {c} {_NEW_GAME_COLS[c]}")
    conn.execute("UPDATE games SET status = NULL, home_score = NULL, away_score = NULL")
    conn.execute("DELETE FROM closing_lines")
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _values(rows: list[dict], cols: list[str], *extra) -> list[tuple]:
    return [tuple(r.get(c) for c in cols) + extra for r in rows]


def upsert_experts(conn: sqlite3.Connection, rows: list[dict], seen_at: str) -> None:
    conn.executemany(
        """INSERT INTO experts(id, name, username, followers, first_seen, last_seen) VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             name=COALESCE(excluded.name, name), username=COALESCE(excluded.username, username),
             followers=COALESCE(excluded.followers, followers), last_seen=excluded.last_seen""",
        _values(rows, ["id", "name", "username", "followers"], seen_at, seen_at),
    )
    conn.commit()


def upsert_games(conn: sqlite3.Connection, rows: list[dict], updated_at: str) -> None:
    cols = GAME_COLS + ["updated_at"]
    sets = ", ".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in cols[1:])
    conn.executemany(
        f"INSERT INTO games({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(id) DO UPDATE SET {sets}",
        _values(rows, GAME_COLS, updated_at),
    )
    conn.commit()


def upsert_picks(conn: sqlite3.Connection, rows: list[dict], updated_at: str) -> None:
    cols = PICK_COLS + ["updated_at"]
    sets = ", ".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in PICK_UPDATABLE)
    conn.executemany(
        f"INSERT INTO picks({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(id) DO UPDATE SET {sets}, updated_at=excluded.updated_at",
        _values(rows, PICK_COLS, updated_at),
    )
    conn.commit()


def upsert_lines(conn: sqlite3.Connection, rows: list[dict], captured_at: str) -> None:
    """Store line + public % only while the game has not started, so the last write is the closing line."""
    cols = LINE_COLS + ["captured_at"]
    conn.executemany(
        f"""INSERT INTO closing_lines({', '.join(cols)})
            SELECT {', '.join('?' * len(cols))}
            WHERE EXISTS (SELECT 1 FROM games WHERE id = ? AND start_time > ?)
            ON CONFLICT(game_id, market, side) DO UPDATE SET
              line=excluded.line, odds=excluded.odds, tickets_pct=excluded.tickets_pct,
              money_pct=excluded.money_pct, captured_at=excluded.captured_at""",
        [v + (v[0], captured_at) for v in _values(rows, LINE_COLS, captured_at)],
    )
    conn.commit()


def insert_pick_forms(conn: sqlite3.Connection, rows: list[dict], captured_at: str) -> None:
    """Keep the expert's form from the first time a pick is seen, and only before its game starts,
    so the pick's own result is never part of the form it is judged by."""
    cols = FORM_COLS + ["captured_at"]
    conn.executemany(
        f"""INSERT OR IGNORE INTO pick_form({', '.join(cols)})
            SELECT {', '.join('?' * len(cols))}
            WHERE EXISTS (SELECT 1 FROM picks p JOIN games g ON g.id = p.game_id
                          WHERE p.id = ? AND g.start_time > ?)""",
        [v + (v[0], captured_at) for v in _values(rows, FORM_COLS, captured_at)],
    )
    conn.commit()


def upsert_public(conn: sqlite3.Connection, rows: list[dict], captured_at: str) -> None:
    """Action Network public splits (line, % bets, % money); like closing lines, frozen once the game starts."""
    cols = LINE_COLS + ["captured_at"]
    conn.executemany(
        f"""INSERT INTO public_splits({', '.join(cols)})
            SELECT {', '.join('?' * len(cols))}
            WHERE EXISTS (SELECT 1 FROM games WHERE id = ? AND start_time > ?)
            ON CONFLICT(game_id, market, side) DO UPDATE SET
              line=excluded.line, odds=excluded.odds, tickets_pct=excluded.tickets_pct,
              money_pct=excluded.money_pct, captured_at=excluded.captured_at""",
        [v + (v[0], captured_at) for v in _values(rows, LINE_COLS, captured_at)],
    )
    conn.commit()


def mark_league(conn: sqlite3.Connection, league: str, ok: bool, at: str, error: str | None = None) -> None:
    if ok:
        conn.execute(
            """INSERT INTO league_status(league, last_success_at) VALUES (?, ?)
               ON CONFLICT(league) DO UPDATE SET last_success_at=excluded.last_success_at""",
            (league, at),
        )
    else:
        conn.execute(
            """INSERT INTO league_status(league, last_error, last_error_at) VALUES (?, ?, ?)
               ON CONFLICT(league) DO UPDATE SET last_error=excluded.last_error,
                 last_error_at=excluded.last_error_at""",
            (league, error, at),
        )
    conn.commit()
