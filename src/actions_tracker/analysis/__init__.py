"""Analysis tables built from graded picks."""

import sqlite3

import pandas as pd

from actions_tracker.analysis.consensus import consensus_games, consensus_summary, past_plays, upcoming
from actions_tracker.analysis.experts import expert_habits, expert_summary, leaderboard
from actions_tracker.analysis.trend import weekly_trend
from actions_tracker.grading import load_graded_picks


def build_tables(conn: sqlite3.Connection, now: str) -> dict[str, pd.DataFrame]:
    picks = load_graded_picks(conn)
    cg = consensus_games(picks)
    cs = consensus_summary(cg)
    es = expert_summary(picks, now)
    lb = leaderboard(es)
    return {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Trend_Weekly": weekly_trend(cg, picks, lb),
        "Upcoming": upcoming(cg, cs, now),
        "Past_Plays": past_plays(cg),
        "Leaderboard": lb,
    }
