"""Forward tracking for the user's halftime 2H method, using persisted exact sportsbook lines."""

import sqlite3

import pandas as pd

from actions_tracker.config import TZ
from actions_tracker.live import second_half_table

PLAY_COLS = ["game_id", "et_date", "league", "start_time", "match", "market", "pick_side", "pick",
             "line", "first_line", "score_1h", "score_2h", "first_result", "result", "units",
             "captured_at", "first_source", "second_source"]
SUMMARY_COLS = ["scope", "et_date", "league", "market", "tracked", "pending", "wins", "losses",
                "pushes", "graded", "win_pct", "units", "roi"]


def _result(margin: float) -> str:
    return "win" if margin > 0 else "loss" if margin < 0 else "push"


def _units(result: str) -> float | None:
    return 10 / 11 if result == "win" else -1.0 if result == "loss" else 0.0 if result == "push" else None


def second_half_plays(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per recorded 2H spread/total play; finals are graded from the persisted 1H score."""
    snapshots = second_half_table(conn)
    if snapshots.empty:
        return pd.DataFrame(columns=PLAY_COLS)
    games = {int(row["id"]): dict(row) for row in conn.execute(
        "SELECT id, start_time, away_abbr, home_abbr, away_name, home_name, status, away_score, home_score "
        "FROM games")}
    rows = []
    for snapshot in snapshots.to_dict("records"):
        game = games.get(int(snapshot["game_id"]))
        if not game:
            continue
        away = game.get("away_abbr") or game.get("away_name") or "AWAY"
        home = game.get("home_abbr") or game.get("home_name") or "HOME"
        start = pd.Timestamp(game["start_time"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        et_date = start.tz_convert(TZ).strftime("%Y-%m-%d")
        away_1h, home_1h = int(snapshot["away_score_1h"]), int(snapshot["home_score_1h"])
        final = game.get("status") == "complete" and game.get("away_score") is not None \
            and game.get("home_score") is not None
        away_2h = int(game["away_score"]) - away_1h if final else None
        home_2h = int(game["home_score"]) - home_1h if final else None
        valid_final = final and away_2h >= 0 and home_2h >= 0
        common = {"game_id": int(snapshot["game_id"]), "et_date": et_date, "league": snapshot["league"],
                  "start_time": game["start_time"], "match": f"{away} @ {home}",
                  "score_1h": f"{away_1h}-{home_1h}",
                  "score_2h": f"{away_2h}-{home_2h}" if valid_final else None,
                  "captured_at": snapshot["captured_at"],
                  "first_source": snapshot.get("first_source") or "ESPN",
                  "second_source": snapshot.get("second_source") or "ESPN"}

        first_away, first_home = snapshot["first_spread_away"], snapshot["first_spread_home"]
        if pd.notna(first_away) and pd.notna(first_home):
            away_margin = away_1h - home_1h + float(first_away)
            if away_margin != 0:
                side = "away" if away_margin < 0 else "home"
                line = snapshot[f"second_spread_{side}"]
                if pd.notna(line):
                    own_2h, other_2h = (away_2h, home_2h) if side == "away" else (home_2h, away_2h)
                    result = _result(own_2h + float(line) - other_2h) if valid_final else "pending"
                    first_line = first_away if side == "away" else first_home
                    rows.append(common | {"market": "spread", "pick_side": side,
                                          "pick": f"{away if side == 'away' else home}", "line": float(line),
                                          "first_line": float(first_line),
                                          "first_result": f"{away if side == 'away' else home} thua ATS",
                                          "result": result, "units": _units(result)})

        first_total, second_total = snapshot["first_total"], snapshot["second_total"]
        if pd.notna(first_total) and pd.notna(second_total):
            points_1h = away_1h + home_1h
            if points_1h != float(first_total):
                first_result = "under" if points_1h < float(first_total) else "over"
                side = "over" if first_result == "under" else "under"
                points_2h = away_2h + home_2h if valid_final else None
                margin = (points_2h - float(second_total)) * (1 if side == "over" else -1) \
                    if valid_final else None
                result = _result(margin) if margin is not None else "pending"
                rows.append(common | {"market": "total", "pick_side": side, "pick": side.title(),
                                      "line": float(second_total), "first_line": float(first_total),
                                      "first_result": f"1H {first_result.title()}", "result": result,
                                      "units": _units(result)})
    return pd.DataFrame(rows, columns=PLAY_COLS).sort_values(
        ["start_time", "game_id", "market"], ascending=[False, False, True], kind="stable").reset_index(drop=True)


def _summary_row(scope: str, et_date: str, league: str, market: str, part: pd.DataFrame) -> dict:
    wins = int((part["result"] == "win").sum())
    losses = int((part["result"] == "loss").sum())
    pushes = int((part["result"] == "push").sum())
    pending = int((part["result"] == "pending").sum())
    decisions = wins + losses
    units = float(part["units"].fillna(0).sum())
    return {"scope": scope, "et_date": et_date, "league": league, "market": market,
            "tracked": int(len(part)), "pending": pending, "wins": wins, "losses": losses, "pushes": pushes,
            "graded": wins + losses + pushes, "win_pct": wins / decisions if decisions else None,
            "units": units, "roi": units / decisions if decisions else None}


def second_half_summary(plays: pd.DataFrame) -> pd.DataFrame:
    """Daily and cumulative records, including league/market splits and still-pending plays."""
    if plays.empty:
        return pd.DataFrame(columns=SUMMARY_COLS)
    rows = []
    periods = [("all", "ALL", plays)]
    periods += [("day", str(day), part) for day, part in plays.groupby("et_date", sort=True)]
    for scope, et_date, period in periods:
        groups = [("ALL", "ALL", period)]
        groups += [(str(league), "ALL", part) for league, part in period.groupby("league", sort=True)]
        groups += [("ALL", str(market), part) for market, part in period.groupby("market", sort=True)]
        groups += [(str(league), str(market), part)
                   for (league, market), part in period.groupby(["league", "market"], sort=True)]
        rows.extend(_summary_row(scope, et_date, league, market, part)
                    for league, market, part in groups)
    return pd.DataFrame(rows, columns=SUMMARY_COLS)
