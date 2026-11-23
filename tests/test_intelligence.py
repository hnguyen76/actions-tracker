"""Trend intelligence tables shown together on the dashboard."""

import pandas as pd

from actions_tracker import db
from actions_tracker.analysis.intelligence import (method_equity, pick_ratio_matrix, spread_flip_results,
                                                   trend_radar)


def _plays():
    rows = []
    for day in range(9, 23):
        current = day >= 16
        rows.append(dict(game_id=day, league="nfl", market="spread",
                         start_time=f"2026-11-{day:02d}T18:00:00.000Z", et_date=f"2026-11-{day:02d}",
                         day_group="T2-6" if day % 7 not in (0, 1) else "T7-CN", match="A@B", crowd="A",
                         votes=3 if current else 2, total_votes=3, method="follow" if current else "fade",
                         bet_side="away", pick="A", line=2.5, odds=-110, status="graded",
                         result="win" if current else "loss"))
    return pd.DataFrame(rows)


def test_trend_radar_compares_latest_completed_seven_days():
    rows = trend_radar(_plays()).set_index(["league", "market", "day_group"])
    overall = rows.loc[("ALL", "ALL", "ALL")]
    assert (overall.current_start, overall.as_of, overall.prior_start, overall.prior_end) == \
        ("2026-11-16", "2026-11-22", "2026-11-09", "2026-11-15")
    assert (overall.current_wins, overall.current_losses, overall.prior_wins, overall.prior_losses) == (7, 0, 0, 7)
    assert overall.trend == "up" and overall.delta_roi > 1


def test_ratio_matrix_and_equity_use_recorded_odds():
    plays = _plays()
    ratios = pick_ratio_matrix(plays)
    current = ratios.query("league == 'ALL' and market == 'ALL' and ratio == '3/3'")
    assert current.wins.sum() == 7 and set(current.method) == {"follow"}
    equity, summary = method_equity(plays)
    assert len(equity) == 14 and equity.iloc[-1].cumulative_units < 0
    assert summary.iloc[0].best_streak == 7 and summary.iloc[0].worst_streak == -7
    assert summary.iloc[0].max_drawdown <= -7


def test_spread_flip_is_graded_at_first_negative_line(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    db.upsert_games(conn, [dict(id=1, league="nfl", start_time="2026-11-23T18:00:00.000Z",
                                away_abbr="AWY", home_abbr="HOM", away_score=24, home_score=21,
                                status="complete")], "t")
    db.upsert_picks(conn, [dict(id=1, expert_id=1, game_id=1, league="nfl", market="spread",
                                pick_side="away", created_at="2026-11-23T10:00:00.000Z")], "t")
    for captured, away, home in [
        ("2026-11-23T10:00:00.000Z", 2.5, -2.5),
        ("2026-11-23T11:00:00.000Z", -1.5, 1.5),
        ("2026-11-23T12:00:00.000Z", -3.5, 3.5),
    ]:
        db.upsert_lines(conn, [dict(game_id=1, market="spread", side="away", line=away, odds=-110),
                               dict(game_id=1, market="spread", side="home", line=home, odds=-110)], captured)
    rows, summary = spread_flip_results(conn)
    assert len(rows) == 1
    flip = rows.iloc[0]
    assert (flip.team, flip.open_line, flip.crossed_line, flip.close_line, flip.clv) == ("AWY", 2.5, -1.5, -3.5, 2.0)
    assert flip.result == "win" and flip.held_negative
    total = summary.query("league == 'ALL'").iloc[0]
    assert (total.wins, total.losses, total.pending) == (1, 0, 0)
