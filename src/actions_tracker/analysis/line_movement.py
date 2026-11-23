"""ESPN pregame line movement from snapshots captured by the phone."""

import sqlite3

import pandas as pd

from actions_tracker.config import TZ

MOVEMENT_COLS = ["game_id", "league", "start_time", "et_date", "away_abbr", "home_abbr", "market", "side",
                 "team", "line", "odds", "captured_at", "open_line", "current_line", "previous_line", "delta",
                 "delta_from_open", "change_no"]
FLIP_COLS = ["game_id", "league", "start_time", "et_date", "away_abbr", "home_abbr", "side", "team",
             "open_line", "current_line", "move", "first_seen_at", "crossed_at", "current_at"]


def _et_date(value: str) -> str:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.tz_convert(TZ).strftime("%Y-%m-%d")


def line_movement_tables(conn: sqlite3.Connection, now: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return actual line changes and spread sides that crossed from plus to minus before kickoff."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='line_snapshots'").fetchone()
    if not exists:
        return pd.DataFrame(columns=MOVEMENT_COLS), pd.DataFrame(columns=FLIP_COLS)
    raw = pd.read_sql_query(
        "SELECT s.game_id, g.league, g.start_time, g.away_abbr, g.home_abbr, s.market, s.side, s.line, "
        "s.odds, s.captured_at FROM line_snapshots s JOIN games g ON g.id = s.game_id "
        "WHERE g.start_time > ? AND g.league IN ('nfl','ncaaf','nba') "
        "AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id) "
        "ORDER BY s.game_id, s.market, s.side, s.captured_at", conn, params=(now,))
    if raw.empty:
        return pd.DataFrame(columns=MOVEMENT_COLS), pd.DataFrame(columns=FLIP_COLS)
    raw["line"] = pd.to_numeric(raw["line"], errors="coerce")
    raw = raw[raw["line"].notna()].copy()
    movements, flips = [], []
    for (game_id, market, side), group in raw.groupby(["game_id", "market", "side"], sort=True):
        group = group.sort_values("captured_at", kind="stable")
        changed = group[(group["line"].ne(group["line"].shift())) | (group["odds"].ne(group["odds"].shift()))]
        if changed.empty:
            continue
        first, current = changed.iloc[0], changed.iloc[-1]
        team = first["away_abbr"] if side == "away" else first["home_abbr"] if side == "home" else str(side).title()
        previous = None
        for change_no, (_, row) in enumerate(changed.iterrows(), 1):
            line = float(row["line"])
            movements.append({"game_id": int(game_id), "league": row["league"], "start_time": row["start_time"],
                              "et_date": _et_date(row["start_time"]), "away_abbr": row["away_abbr"],
                              "home_abbr": row["home_abbr"], "market": market, "side": side, "team": team,
                              "line": line, "odds": None if pd.isna(row["odds"]) else int(row["odds"]),
                              "captured_at": row["captured_at"], "open_line": float(first["line"]),
                              "current_line": float(current["line"]), "previous_line": previous,
                              "delta": None if previous is None else line - previous,
                              "delta_from_open": line - float(first["line"]), "change_no": change_no})
            previous = line
        if market == "spread" and float(first["line"]) > 0 and float(current["line"]) < 0:
            crossed = changed[changed["line"] < 0].iloc[0]
            flips.append({"game_id": int(game_id), "league": first["league"], "start_time": first["start_time"],
                          "et_date": _et_date(first["start_time"]), "away_abbr": first["away_abbr"],
                          "home_abbr": first["home_abbr"], "side": side, "team": team,
                          "open_line": float(first["line"]), "current_line": float(current["line"]),
                          "move": float(current["line"]) - float(first["line"]),
                          "first_seen_at": first["captured_at"], "crossed_at": crossed["captured_at"],
                          "current_at": current["captured_at"]})
    movement = pd.DataFrame(movements, columns=MOVEMENT_COLS)
    flip = pd.DataFrame(flips, columns=FLIP_COLS)
    if not movement.empty:
        movement = movement.sort_values(["start_time", "game_id", "market", "side", "captured_at"],
                                        kind="stable").reset_index(drop=True)
    if not flip.empty:
        flip = flip.sort_values(["start_time", "game_id", "side"], kind="stable").reset_index(drop=True)
    return movement, flip
