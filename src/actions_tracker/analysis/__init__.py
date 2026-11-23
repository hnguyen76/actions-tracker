"""Analysis tables built from graded picks."""

import sqlite3
from pathlib import Path

import pandas as pd

from actions_tracker.analysis.consensus import (consensus_games, consensus_summary, past_plays, pregame_picks, upcoming,
                                                upcoming_board)
from actions_tracker.analysis.history import add_season, history_plays, history_summary, history_weekly, load_history
from actions_tracker.analysis.decisions import decisions
from actions_tracker.live import live_games_table, scores_table, second_half_table
from actions_tracker.weather import weather_table
from actions_tracker.analysis.in_play import in_play
from actions_tracker.analysis.second_half import second_half_plays, second_half_summary
from actions_tracker.analysis.line_movement import line_movement_tables
from actions_tracker.analysis import forecast as fc
from actions_tracker.analysis.my_method import (WEEKDAY_DECISION_VOTES, decision_method_plays, my_method_plays,
                                                my_method_summary, season_plays, season_sensitivity, season_summary)
from actions_tracker.analysis.rule_report import rule_plays, rule_summary
from actions_tracker.analysis.form import expert_form, expert_form_now
from actions_tracker.analysis.experts import expert_clv, expert_habits, expert_summary, leaderboard
from actions_tracker.analysis.trend import weekly_trend
from actions_tracker.grading import load_graded_picks
from actions_tracker.match_news import load_news
from actions_tracker.sports_news import load_sports_news
from actions_tracker.media_picks import load_picks as load_media_picks
from actions_tracker.media_ats import load_ats
from actions_tracker.pregame_archive import load_snapshots


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
    sides = load_history(history_dir)
    hp = history_plays(sides)
    mm = my_method_plays(cg, picks)
    dm = decision_method_plays(consensus_games(picks, min_experts=WEEKDAY_DECISION_VOTES), picks)
    scores = scores_table(conn, now)
    half_plays = second_half_plays(conn)
    game_info = {int(r["id"]): dict(r) for r in conn.execute("SELECT id, week, away_score, home_score FROM games")}
    sp = season_plays(sides, mm, game_info)
    hs = history_summary(hp)
    rp = rule_plays(conn)
    rs = rule_summary(rp)
    up = add_season(upcoming(cg, cs, now), hs)
    board = upcoming_board(picks, now)
    line_movement, spread_flips = line_movement_tables(conn, now)
    tables = {
        "Picks": picks,
        "Consensus": cs,
        "Experts": es,
        "Expert_Habits": expert_habits(picks),
        "Expert_CLV": expert_clv(picks, now),
        "Expert_Form": expert_form(picks, forms),
        "Expert_Form_Now": expert_form_now(forms),
        "Trend_Weekly": weekly_trend(cg, picks),
        "Upcoming": up,
        "Decisions": decisions(rp, rs, up, now, dm),
        "Decision_Method": dm,
        "Data_Quality": quality,
        "Upcoming_Board": board,
        "Line_Movement": line_movement,
        "Spread_Flips": spread_flips,
        "Match_News": load_news(conn, board, now),
        "Sports_News": load_sports_news(conn),
        "Media_Picks": load_media_picks(conn, board, now),
        "Media_ATS": load_ats(conn, board, now),
        "Past_Plays": past_plays(cg),
        "Pregame_Snapshots": load_snapshots(conn),
        "Leaderboard": lb,
        "Rule_Summary": rs,
        "My_Method": mm,
        "My_Method_Summary": my_method_summary(mm, sides),
        "My_Method_Season": sp,
        "My_Method_Season_Summary": season_summary(sp),
        "My_Method_Sensitivity": season_sensitivity(sp),
        "Forecast": fc.forecast_upcoming(sp, now),
        "Forecast_Backtest": fc.walk_forward(sp),
        "Forecast_Cells": fc.cells(sp),
        "Rule_Plays": rp,
        "Scores": scores,
        "Weather": weather_table(conn, now),
        "Live_Games": live_games_table(conn, now),
        "Second_Half": second_half_table(conn),
        "Second_Half_Plays": half_plays,
        "Second_Half_Summary": second_half_summary(half_plays),
        "In_Play": in_play(scores, dm, rp),
        "History_Plays": hp,
        "History_Summary": hs,
        "History_Weekly": history_weekly(hp),
    }
    from actions_tracker.analysis.signals import expert_sides, include_live_decisions, signals
    from actions_tracker.game_context import context_tables
    ctx, opening = context_tables(conn)
    current = pd.read_sql_query("SELECT game_id, market, side, line FROM closing_lines", conn)
    public = pd.read_sql_query("SELECT game_id, market, side, tickets_pct, money_pct FROM public_splits", conn)
    games = pd.read_sql_query("SELECT id, league, home_abbr, away_abbr FROM games", conn)
    signal_inputs = include_live_decisions(tables["Decisions"], tables["In_Play"])
    tables["Signals"] = signals(signal_inputs, games, current, opening, ctx, public,
                                expert_sides(eligible, forms), tables["Forecast"], tables["Decision_Method"],
                                tables["History_Plays"])
    return tables
