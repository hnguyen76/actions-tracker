"""Analysis tables built from graded picks."""

import sqlite3
from pathlib import Path

import pandas as pd

from actions_tracker.analysis.consensus import (consensus_games, consensus_summary, past_plays, pregame_picks, upcoming,
                                                upcoming_board)
from actions_tracker.analysis.history import add_season, history_plays, history_summary, history_weekly, load_history
from actions_tracker.analysis.decisions import decisions
from actions_tracker.analysis.rule_report import rule_plays, rule_summary
from actions_tracker.analysis.form import expert_form, expert_form_now
from actions_tracker.analysis.experts import expert_clv, expert_habits, expert_summary, leaderboard
from actions_tracker.analysis.trend import weekly_trend
from actions_tracker.grading import load_graded_picks


def build_tables(conn: sqlite3.Connection, now: str, history_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    picks = load_graded_picks(conn)
    eligible = pregame_picks(picks)
    late = len(picks) - len(eligible)
    graded_lines = picks[picks["expert_result"].notna() & picks["market"].isin(["spread", "total"])]
    actual = graded_lines[graded_lines["line_source"] == "odds_api_close"]
    captured = pd.to_datetime(actual["close_captured_at"], utc=True, errors="coerce")
    starts = pd.to_datetime(actual["start_time"], utc=True, errors="coerce")
    ages = (starts - captured).dt.total_seconds().div(3600).dropna()
    quality = pd.DataFrame([{
        "excluded_late_picks": late,
        "graded_line_picks": len(graded_lines),
        "actual_close_picks": len(actual),
        "proxy_line_picks": int((graded_lines["line_source"] == "median_expert_line").sum()),
        "actual_close_pct": len(actual) / len(graded_lines) if len(graded_lines) else None,
        "median_close_age_h": float(ages.median()) if len(ages) else None,
        "max_close_age_h": float(ages.max()) if len(ages) else None,
    }])
    forms = pd.read_sql_query("SELECT * FROM pick_form", conn)
    cg = consensus_games(picks)
    cs = consensus_summary(cg)
    es = expert_summary(picks, now)
    lb = leaderboard(es)
    hp = history_plays(load_history(history_dir))
    hs = history_summary(hp)
    rp = rule_plays(conn)
    rs = rule_summary(rp)
    up = add_season(upcoming(cg, cs, now), hs)
    return {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Expert_CLV": expert_clv(picks, now),
        "Expert_Form": expert_form(picks, forms),
        "Expert_Form_Now": expert_form_now(forms),
        "Trend_Weekly": weekly_trend(cg, picks),
        "Upcoming": up,
        "Decisions": decisions(rp, rs, up, now),
        "Data_Quality": quality,
        "Upcoming_Board": upcoming_board(picks, now),
        "Past_Plays": past_plays(cg),
        "Leaderboard": lb,
        "Rule_Summary": rs,
        "Rule_Plays": rp,
        "History_Plays": hp,
        "History_Summary": hs,
        "History_Weekly": history_weekly(hp),
    }
