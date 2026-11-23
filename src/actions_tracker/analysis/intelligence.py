"""Compact trend, pick-ratio, equity and spread-flip reports for the dashboard."""

import sqlite3

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, american_profit, summarize, with_all
from actions_tracker.config import TZ


RADAR_COLS = ["league", "market", "day_group", "as_of", "current_start", "prior_start", "prior_end"] \
    + [f"current_{key}" for key in SUMMARY_KEYS] + [f"prior_{key}" for key in SUMMARY_KEYS] \
    + ["delta_win_pct", "delta_roi", "trend"]
RATIO_COLS = ["league", "market", "day_group", "method", "ratio", "votes", "total_votes"] + SUMMARY_KEYS
EQUITY_COLS = ["sequence", "game_id", "start_time", "et_date", "league", "market", "day_group", "match",
               "pick", "result", "odds", "play_units", "cumulative_units", "peak_units", "drawdown"]
EQUITY_SUMMARY_COLS = SUMMARY_KEYS + ["max_drawdown", "current_streak", "best_streak", "worst_streak"]
FLIP_RESULT_COLS = ["game_id", "league", "start_time", "et_date", "away_abbr", "home_abbr", "side", "team",
                    "open_line", "crossed_line", "close_line", "move_to_cross", "clv", "first_seen_at",
                    "crossed_at", "close_at", "held_negative", "odds", "away_score", "home_score", "result",
                    "units"]
FLIP_SUMMARY_COLS = ["league"] + SUMMARY_KEYS + ["pending", "held_negative", "reverted"]


def _prefix(values: dict, prefix: str) -> dict:
    return {f"{prefix}_{key}": values.get(key) for key in SUMMARY_KEYS}


def trend_radar(plays: pd.DataFrame) -> pd.DataFrame:
    """Compare the last seven completed ET dates with the preceding seven for the user's method."""
    graded = plays[plays["result"].isin(["win", "loss", "push"])].copy() if not plays.empty else plays.copy()
    if graded.empty:
        return pd.DataFrame(columns=RADAR_COLS)
    dates = pd.to_datetime(graded["et_date"], errors="coerce").dropna()
    if dates.empty:
        return pd.DataFrame(columns=RADAR_COLS)
    as_of = dates.max().normalize()
    current_start, prior_end, prior_start = as_of - pd.Timedelta(days=6), as_of - pd.Timedelta(days=7), as_of - pd.Timedelta(days=13)
    graded["_date"] = pd.to_datetime(graded["et_date"], errors="coerce").dt.normalize()
    graded = with_all(graded, ["league", "market", "day_group"])
    rows = []
    for key, group in graded.groupby(["league", "market", "day_group"], sort=True):
        current = group[group["_date"].between(current_start, as_of)]
        prior = group[group["_date"].between(prior_start, prior_end)]
        if current.empty and prior.empty:
            continue
        cur = summarize(current["result"].tolist(), current["odds"].tolist())
        prev = summarize(prior["result"].tolist(), prior["odds"].tolist())
        delta_wp = cur["win_pct"] - prev["win_pct"] if cur["n"] and prev["n"] else None
        delta_roi = cur["roi"] - prev["roi"] if cur["n"] and prev["n"] else None
        if not cur["n"]:
            trend = "gone"
        elif not prev["n"]:
            trend = "new"
        else:
            trend = "up" if delta_roi > 0.05 else "down" if delta_roi < -0.05 else "flat"
        rows.append(dict(zip(["league", "market", "day_group"], key)) | {
            "as_of": as_of.strftime("%Y-%m-%d"), "current_start": current_start.strftime("%Y-%m-%d"),
            "prior_start": prior_start.strftime("%Y-%m-%d"), "prior_end": prior_end.strftime("%Y-%m-%d"),
            **_prefix(cur, "current"), **_prefix(prev, "prior"), "delta_win_pct": delta_wp,
            "delta_roi": delta_roi, "trend": trend,
        })
    return pd.DataFrame(rows, columns=RADAR_COLS)


def pick_ratio_matrix(plays: pd.DataFrame) -> pd.DataFrame:
    """Results for exact majority ratios such as 2/3 or 6/7, retaining weekday/weekend method splits."""
    graded = plays[plays["result"].isin(["win", "loss", "push"])].copy() if not plays.empty else plays.copy()
    if graded.empty:
        return pd.DataFrame(columns=RATIO_COLS)
    graded["votes"] = pd.to_numeric(graded["votes"], errors="coerce").astype("Int64")
    graded["total_votes"] = pd.to_numeric(graded["total_votes"], errors="coerce").astype("Int64")
    graded = graded[graded["votes"].notna() & graded["total_votes"].notna()].copy()
    graded["ratio"] = graded["votes"].astype(str) + "/" + graded["total_votes"].astype(str)
    graded = with_all(graded, ["league", "market"])
    rows = []
    keys = ["league", "market", "day_group", "method", "ratio", "votes", "total_votes"]
    for key, group in graded.groupby(keys, sort=True):
        rows.append(dict(zip(keys, key)) | summarize(group["result"].tolist(), group["odds"].tolist()))
    out = pd.DataFrame(rows, columns=RATIO_COLS)
    return out.sort_values(["league", "market", "day_group", "votes", "total_votes"], kind="stable").reset_index(drop=True)


def _streaks(results: list[str]) -> tuple[int, int, int]:
    current = best = worst = 0
    run = 0
    previous = None
    for result in results:
        if result == "push":
            continue
        sign = 1 if result == "win" else -1
        run = run + sign if previous == sign else sign
        previous = sign
        best, worst = max(best, run), min(worst, run)
    return run, best, worst


def method_equity(plays: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological one-unit equity curve and drawdown for the user's recorded live method."""
    graded = plays[plays["result"].isin(["win", "loss", "push"])].copy() if not plays.empty else plays.copy()
    if graded.empty:
        return pd.DataFrame(columns=EQUITY_COLS), pd.DataFrame(columns=EQUITY_SUMMARY_COLS)
    graded = graded.sort_values(["start_time", "game_id", "market"], kind="stable").reset_index(drop=True)
    cumulative = peak = 0.0
    rows = []
    for sequence, row in enumerate(graded.itertuples(), 1):
        units = american_profit(row.odds) if row.result == "win" else -1.0 if row.result == "loss" else 0.0
        cumulative += units
        peak = max(peak, cumulative)
        rows.append({"sequence": sequence, "game_id": int(row.game_id), "start_time": row.start_time,
                     "et_date": row.et_date, "league": row.league, "market": row.market,
                     "day_group": row.day_group, "match": row.match, "pick": row.pick, "result": row.result,
                     "odds": row.odds, "play_units": units, "cumulative_units": cumulative,
                     "peak_units": peak, "drawdown": cumulative - peak})
    equity = pd.DataFrame(rows, columns=EQUITY_COLS)
    summary = summarize(graded["result"].tolist(), graded["odds"].tolist())
    current, best, worst = _streaks(graded["result"].tolist())
    summary |= {"max_drawdown": float(equity["drawdown"].min()), "current_streak": current,
                "best_streak": best, "worst_streak": worst}
    return equity, pd.DataFrame([summary], columns=EQUITY_SUMMARY_COLS)


def _et_date(value: str) -> str:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.tz_convert(TZ).strftime("%Y-%m-%d")


def spread_flip_results(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Grade every recorded pregame spread crossing + to - at the first negative line S21 observed."""
    raw = pd.read_sql_query(
        "SELECT s.game_id,g.league,g.start_time,g.away_abbr,g.home_abbr,g.away_score,g.home_score,g.status,"
        "s.side,s.line,s.odds,s.captured_at FROM line_snapshots s JOIN games g ON g.id=s.game_id "
        "WHERE s.market='spread' AND s.side IN ('away','home') AND s.captured_at < g.start_time "
        "AND g.league IN ('nfl','ncaaf','nba') AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id=g.id) "
        "ORDER BY s.game_id,s.side,s.captured_at", conn)
    if raw.empty:
        return pd.DataFrame(columns=FLIP_RESULT_COLS), pd.DataFrame(columns=FLIP_SUMMARY_COLS)
    raw["line"] = pd.to_numeric(raw["line"], errors="coerce")
    raw = raw[raw["line"].notna()].copy()
    rows = []
    for (game_id, side), group in raw.groupby(["game_id", "side"], sort=True):
        group = group.sort_values("captured_at", kind="stable")
        changed = group[group["line"].ne(group["line"].shift())]
        if changed.empty or float(changed.iloc[0]["line"]) <= 0:
            continue
        negative = changed[changed["line"] < 0]
        if negative.empty:
            continue
        first, crossed, close = changed.iloc[0], negative.iloc[0], changed.iloc[-1]
        team = first["away_abbr"] if side == "away" else first["home_abbr"]
        away_score, home_score = first["away_score"], first["home_score"]
        result = None
        if pd.notna(away_score) and pd.notna(home_score):
            margin = (float(away_score) - float(home_score)) if side == "away" else (float(home_score) - float(away_score))
            ats = margin + float(crossed["line"])
            result = "win" if ats > 0 else "loss" if ats < 0 else "push"
        odds = None if pd.isna(crossed["odds"]) else int(crossed["odds"])
        units = None if result is None else american_profit(odds) if result == "win" else -1.0 if result == "loss" else 0.0
        rows.append({"game_id": int(game_id), "league": first["league"], "start_time": first["start_time"],
                     "et_date": _et_date(first["start_time"]), "away_abbr": first["away_abbr"],
                     "home_abbr": first["home_abbr"], "side": side, "team": team,
                     "open_line": float(first["line"]), "crossed_line": float(crossed["line"]),
                     "close_line": float(close["line"]), "move_to_cross": float(crossed["line"] - first["line"]),
                     "clv": float(crossed["line"] - close["line"]), "first_seen_at": first["captured_at"],
                     "crossed_at": crossed["captured_at"], "close_at": close["captured_at"],
                     "held_negative": bool(float(close["line"]) < 0), "odds": odds,
                     "away_score": None if pd.isna(away_score) else int(away_score),
                     "home_score": None if pd.isna(home_score) else int(home_score), "result": result, "units": units})
    out = pd.DataFrame(rows, columns=FLIP_RESULT_COLS)
    if out.empty:
        return out, pd.DataFrame(columns=FLIP_SUMMARY_COLS)
    out = out.sort_values(["start_time", "game_id", "side"], ascending=[False, True, True], kind="stable").reset_index(drop=True)
    summaries = []
    for league in ["ALL", *sorted(out["league"].unique())]:
        group = out if league == "ALL" else out[out["league"] == league]
        graded = group[group["result"].notna()]
        s = summarize(graded["result"].tolist(), graded["odds"].tolist())
        summaries.append({"league": league, **s, "pending": int(group["result"].isna().sum()),
                          "held_negative": int(group["held_negative"].sum()),
                          "reverted": int((~group["held_negative"]).sum())})
    return out, pd.DataFrame(summaries, columns=FLIP_SUMMARY_COLS)
