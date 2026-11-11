"""Analysis tables built from graded picks."""

import sqlite3
from pathlib import Path

import pandas as pd

from actions_tracker.analysis.consensus import consensus_games, consensus_summary, past_plays, upcoming
from actions_tracker.analysis.history import history_plays, history_summary, history_weekly, load_history
from actions_tracker.analysis.form import expert_form, expert_form_now
from actions_tracker.analysis.experts import expert_habits, expert_summary, leaderboard
from actions_tracker.analysis.trend import weekly_trend
from actions_tracker.grading import load_graded_picks


def build_tables(conn: sqlite3.Connection, now: str, history_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    picks = load_graded_picks(conn)
    forms = pd.read_sql_query("SELECT * FROM pick_form", conn)
    cg = consensus_games(picks)
    cs = consensus_summary(cg)
    es = expert_summary(picks, now)
    lb = leaderboard(es)
    hp = history_plays(load_history(history_dir))
    return {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Expert_Form": expert_form(picks, forms),
        "Expert_Form_Now": expert_form_now(forms),
        "Trend_Weekly": weekly_trend(cg, picks),
        "Upcoming": upcoming(cg, cs, now),
        "Past_Plays": past_plays(cg),
        "Leaderboard": lb,
        "History_Plays": hp,
        "History_Summary": history_summary(hp),
        "History_Weekly": history_weekly(hp),
    }
