"""Analysis tables built from graded picks."""

import sqlite3

import pandas as pd

from actions_tracker.analysis.consensus import consensus_games, consensus_summary, upcoming
from actions_tracker.analysis.experts import expert_habits, expert_summary, leaderboard
from actions_tracker.analysis.public import money_vs_tickets, public_games, public_summary
from actions_tracker.analysis.trend import weekly_trend
from actions_tracker.grading import load_graded_picks


def build_tables(conn: sqlite3.Connection, now: str) -> dict[str, pd.DataFrame]:
    picks = load_graded_picks(conn)
    cg = consensus_games(picks)
    cs = consensus_summary(cg)
    es = expert_summary(picks, now)
    lb = leaderboard(es)
    pg = public_games(cg)
    ps = public_summary(pg)
    mvt = money_vs_tickets(picks).assign(relation="money>tickets", heavy=None)
    frames = [f for f in (ps, mvt[ps.columns]) if not f.empty]
    evp = pd.concat(frames, ignore_index=True) if frames else ps
    return {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Expert_vs_Public": evp,
        "Trend_Weekly": weekly_trend(cg, picks, lb, pg),
        "Upcoming": upcoming(cg, cs, now),
        "Leaderboard": lb,
    }
