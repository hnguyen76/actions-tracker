"""Import the owner's private WagerHub score feed with strict, exact matching.

WagerHub wins only when its private snapshot is fresh and both teams match in
away@home order. ESPN remains the fallback for every missing or ambiguous row.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

from actions_tracker.matching import normalize

MAX_AGE_MINUTES = 8
LIVE_FILE = Path("data/private/wagerhub_live.json")


def _field(row: dict, names: tuple[str, ...]):
    for key, value in row.items():
        clean = re.sub(r"[^a-z0-9]+", " ", str(key).lower()).strip()
        if any(name == clean or name in clean for name in names):
            return value
    return None


def _event(row: dict, captured_at: str) -> dict | None:
    matchup = str(_field(row, ("match", "matchup", "event", "game", "teams", "description")) or "").strip()
    parts = re.split(r"\s+(?:@|at)\s+", matchup, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None  # "vs" orientation is not safe enough to overwrite a score
    score_text = str(_field(row, ("score", "current score", "result")) or "")
    score = re.search(r"(?<!\d)(\d{1,3})\s*[-:]\s*(\d{1,3})(?!\d)", score_text)
    if not score:
        return None
    status = " ".join(str(x) for x in (_field(row, ("status", "state", "period", "clock")), row.get("_source"))).lower()
    state = "post" if re.search(r"\b(final|finished|complete|ended)\b", status) else "in"
    return {"away_name": parts[0].strip(), "home_name": parts[1].strip(),
            "away_score": int(score.group(1)), "home_score": int(score.group(2)),
            "state": state, "detail": str(_field(row, ("detail", "status", "period", "clock")) or "Live"),
            "captured_at": captured_at}


def load_events(root: Path, now: str) -> list[dict]:
    path = Path(root) / LIVE_FILE
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text("utf-8"))
        captured = str(payload["updated_at"])
        age = pd.Timestamp(now) - pd.Timestamp(captured)
        if age < pd.Timedelta(0) or age > pd.Timedelta(minutes=MAX_AGE_MINUTES):
            return []
        return [event for row in payload.get("records", []) if isinstance(row, dict)
                if (event := _event(row, captured)) is not None]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def apply_scores(conn: sqlite3.Connection, root: Path, now: str) -> dict:
    events = load_events(root, now)
    if not events:
        return {"available": 0, "matched": 0, "live": 0, "final": 0}
    conn.execute("CREATE TABLE IF NOT EXISTS live_scores(game_id INTEGER PRIMARY KEY, away_score INTEGER, "
                 "home_score INTEGER, state TEXT, detail TEXT, updated_at TEXT, source TEXT)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(live_scores)")}
    if "source" not in columns:
        conn.execute("ALTER TABLE live_scores ADD COLUMN source TEXT")
    games = [dict(row) for row in conn.execute(
        "SELECT id, away_name, home_name, away_abbr, home_abbr, status FROM games "
        "WHERE status IS NULL OR status != 'complete'")]
    by_pair = {}
    for game in games:
        for away, home in ((game.get("away_name"), game.get("home_name")),
                           (game.get("away_abbr"), game.get("home_abbr"))):
            pair = (normalize(away), normalize(home))
            if pair[0] and pair[1]:
                by_pair.setdefault(pair, []).append(game)
    matched = []
    for event in events:
        candidates = by_pair.get((normalize(event["away_name"]), normalize(event["home_name"])), [])
        if len(candidates) == 1:
            matched.append((candidates[0], event))
    rows = [(game["id"], event["away_score"], event["home_score"], event["state"],
             event["detail"], event["captured_at"], "WagerHub") for game, event in matched]
    conn.executemany(
        "INSERT INTO live_scores(game_id, away_score, home_score, state, detail, updated_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(game_id) DO UPDATE SET "
        "away_score=excluded.away_score, home_score=excluded.home_score, state=excluded.state, "
        "detail=excluded.detail, updated_at=excluded.updated_at, source='WagerHub'", rows)
    finals = [(event["home_score"], event["away_score"], game["id"]) for game, event in matched
              if event["state"] == "post"]
    conn.executemany("UPDATE games SET status='complete', home_score=?, away_score=? WHERE id=?", finals)
    conn.commit()
    return {"available": len(events), "matched": len(matched),
            "live": sum(event["state"] == "in" for _, event in matched), "final": len(finals)}
