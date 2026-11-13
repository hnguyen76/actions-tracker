"""Grade picks against final scores and label each pick's side (spec §6)."""

import math
import sqlite3

import pandas as pd

OPPOSITE = {"home": "away", "away": "home", "over": "under", "under": "over"}

COLUMNS = [
    "pick_id", "expert_id", "expert_name", "league", "game_id", "market", "pick_side", "line", "odds",
    "created_at", "start_time", "status", "home_abbr", "away_abbr", "home_score", "away_score",
    "close_line", "close_odds", "close_captured_at", "opp_close_odds",
    "home_away", "fav_dog", "over_under", "side_result", "expert_result", "line_source",
]

_SQL = """
SELECT p.id AS pick_id, p.expert_id, e.name AS expert_name, p.league, p.game_id, p.market, p.pick_side,
       p.line, p.odds, p.an_result, p.created_at, COALESCE(g.start_time, p.starts_at) AS start_time,
       g.status, g.home_abbr, g.away_abbr, g.home_score, g.away_score,
       cl.line AS close_line, cl.odds AS close_odds, cl.captured_at AS close_captured_at, op.odds AS opp_close_odds
FROM picks p
LEFT JOIN games g ON g.id = p.game_id
LEFT JOIN experts e ON e.id = p.expert_id
LEFT JOIN closing_lines cl ON cl.game_id = p.game_id AND cl.market = p.market AND cl.side = p.pick_side
LEFT JOIN closing_lines op ON op.game_id = p.game_id AND op.market = p.market AND op.side =
     CASE p.pick_side WHEN 'home' THEN 'away' WHEN 'away' THEN 'home' WHEN 'over' THEN 'under' ELSE 'over' END
ORDER BY p.id
"""


def opposite(side: str) -> str:
    return OPPOSITE[side]


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _v(x):
    return None if _missing(x) else x


def grade_side(market: str, side: str, line: float | None, home_score: int, away_score: int) -> str:
    """Result of one side: spread uses that side's own line, total uses the total line, ml ignores line."""
    if market == "total":
        diff = (home_score + away_score) - line
        if side == "under":
            diff = -diff
    else:
        own, other = (home_score, away_score) if side == "home" else (away_score, home_score)
        diff = own - other + (line if market == "spread" else 0)
    return "win" if diff > 0 else "loss" if diff < 0 else "push"


def _gradable(r: dict, line) -> bool:
    if r["status"] != "complete" or _missing(r["home_score"]) or _missing(r["away_score"]):
        return False
    return r["market"] == "ml" or not _missing(line)


def _fav_dog(r: dict) -> str | None:
    if r["market"] == "spread":
        line = r["close_line"] if not _missing(r["close_line"]) else r["line"]
        if _missing(line):
            return None
        return "favorite" if line < 0 else "underdog" if line > 0 else "pickem"
    if r["market"] == "ml":
        own, other = r["close_odds"], r["opp_close_odds"]
        if not _missing(own) and not _missing(other):
            return "favorite" if own < other else "underdog" if own > other else "pickem"
        if _missing(r["odds"]):
            return None
        return "favorite" if r["odds"] < 0 else "underdog"
    return None


def load_graded_picks(conn: sqlite3.Connection) -> pd.DataFrame:
    raw = [dict(row) for row in conn.execute(_SQL).fetchall()]
    if not raw:
        return pd.DataFrame(columns=COLUMNS)
    # fallback closing line: median of expert lines on the same game/market/side
    lines: dict[tuple, list[float]] = {}
    for r in raw:
        if not _missing(r["line"]):
            lines.setdefault((r["game_id"], r["market"], r["pick_side"]), []).append(r["line"])
    medians = {k: float(pd.Series(v).median()) for k, v in lines.items()}

    out = []
    for r in raw:
        close = r["close_line"]
        if r["market"] == "ml":
            line_source = "ml_no_line"
        elif not _missing(close):
            line_source = "odds_api_close"
        else:
            close = medians.get((r["game_id"], r["market"], r["pick_side"]))
            line_source = "median_expert_line" if close is not None else None
        side_result = (
            grade_side(r["market"], r["pick_side"], close, r["home_score"], r["away_score"])
            if _gradable(r, close) else None
        )
        expert_result = None  # Action Network's own result is stored but not used (spec §12.1)
        if r["status"] == "complete":
            own = r["line"] if not _missing(r["line"]) else close
            if _gradable(r, own):
                expert_result = grade_side(r["market"], r["pick_side"], own, r["home_score"], r["away_score"])
        out.append({
            **{c: _v(r.get(c)) for c in COLUMNS if c in r},
            "home_away": r["pick_side"] if r["market"] in ("spread", "ml") else None,
            "fav_dog": _fav_dog(r),
            "over_under": r["pick_side"] if r["market"] == "total" else None,
            "side_result": side_result,
            "expert_result": expert_result,
            "line_source": line_source,
        })
    return pd.DataFrame(out, columns=COLUMNS).astype(object)
