"""Analysis tables built from graded picks."""

import sqlite3
from pathlib import Path

import pandas as pd

from actions_tracker.analysis.consensus import (consensus_games, consensus_summary, past_plays, upcoming,
                                                upcoming_board)
from actions_tracker.analysis.history import add_season, history_plays, history_summary, history_weekly, load_history
from actions_tracker.analysis.rule_report import rule_plays, rule_summary
from actions_tracker.analysis.form import expert_form, expert_form_now
from actions_tracker.analysis.experts import expert_clv, expert_habits, expert_summary, leaderboard
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
    hs = history_summary(hp)
    rp = rule_plays(conn)
    return {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Expert_CLV": expert_clv(picks, now),
        "Expert_Form": expert_form(picks, forms),
        "Expert_Form_Now": expert_form_now(forms),
        "Trend_Weekly": weekly_trend(cg, picks),
        "Upcoming": add_season(upcoming(cg, cs, now), hs),
        "Upcoming_Board": upcoming_board(picks, now),
        "Past_Plays": past_plays(cg),
        "Leaderboard": lb,
        "Rule_Summary": rule_summary(rp),
        "Rule_Plays": rp,
        "History_Plays": hp,
        "History_Summary": hs,
        "History_Weekly": history_weekly(hp),
    }
