import pandas as pd

from actions_tracker import db, live
from actions_tracker.analysis.second_half import second_half_plays, second_half_summary


def _database(tmp_path):
    conn = db.connect(tmp_path / "second-half.db")
    db.upsert_games(conn, [
        dict(id=1, league="ncaaf", start_time="2026-11-23T00:30:00.000Z", away_abbr="AWY", home_abbr="HOM",
             away_name="Away", home_name="Home", status="complete", away_score=30, home_score=28),
        dict(id=2, league="nba", start_time="2026-11-23T02:00:00.000Z", away_abbr="A2", home_abbr="H2",
             away_name="Away 2", home_name="Home 2"),
    ], "t")
    conn.execute(live.SECOND_HALF_SCHEMA)
    conn.executemany(
        "INSERT INTO second_half_snapshots(game_id, league, espn_event_id, captured_at, away_score_1h, "
        "home_score_1h, first_spread_away, first_spread_home, first_total, second_spread_away, "
        "second_spread_home, second_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, "ncaaf", "101", "2026-11-23T01:45:00.000Z", 10, 14, 2.5, -2.5, 27.5, 4.5, -4.5, 24.5),
            (2, "nba", "102", "2026-11-23T03:15:00.000Z", 50, 50, 1.5, -1.5, 100.0, 2.5, -2.5, 110.5),
        ])
    conn.commit()
    return conn


def test_second_half_plays_grade_from_saved_half_score_and_final(tmp_path):
    plays = second_half_plays(_database(tmp_path))
    game = plays[plays.game_id == 1].set_index("market")
    assert set(game.index) == {"spread", "total"}
    assert game.loc["spread", "pick"] == "AWY" and game.loc["spread", "line"] == 4.5
    assert game.loc["spread", "score_1h"] == "10-14" and game.loc["spread", "score_2h"] == "20-14"
    assert game.loc["spread", "result"] == "win" and game.loc["spread", "units"] == 10 / 11
    assert game.loc["total", "pick_side"] == "over" and game.loc["total", "result"] == "win"
    pending = plays[plays.game_id == 2]
    assert len(pending) == 1  # 1H total push creates no total play
    assert pending.iloc[0].result == "pending" and pd.isna(pending.iloc[0].score_2h)
    assert set(plays.et_date) == {"2026-11-22"}  # game dates are grouped in Eastern time


def test_second_half_summary_keeps_daily_cumulative_and_splits(tmp_path):
    summary = second_half_summary(second_half_plays(_database(tmp_path)))
    daily = summary.query("scope == 'day' and league == 'ALL' and market == 'ALL'").iloc[0]
    assert (daily.wins, daily.losses, daily.pushes, daily.pending, daily.tracked) == (2, 0, 0, 1, 3)
    assert daily.win_pct == 1 and daily.units == 20 / 11 and daily.roi == 10 / 11
    cumulative = summary.query("scope == 'all' and league == 'ALL' and market == 'ALL'").iloc[0]
    assert cumulative.et_date == "ALL" and cumulative.tracked == 3
    assert len(summary.query("scope == 'day' and league == 'ncaaf' and market == 'spread'")) == 1


def test_second_half_analysis_empty_without_snapshots(tmp_path):
    conn = db.connect(tmp_path / "empty.db")
    assert second_half_plays(conn).empty
    assert second_half_summary(second_half_plays(conn)).empty
