import pandas as pd

from actions_tracker import db
from actions_tracker.analysis import build_tables
from actions_tracker.analysis.consensus import consensus_games
from actions_tracker.analysis.trend import weekly_trend
from tests.helpers import make_picks


def game(gid, result, start):
    return [dict(pick_id=gid * 10 + i, expert_id=i, game_id=gid, market="spread", pick_side="home",
                 side_result=result, close_odds=-110, start_time=start) for i in range(3)]


def test_week_bucket_eastern():
    # 2026-11-10T03:00Z = Mon 22:00 ET -> week 2026-11-09; 2026-11-09T03:00Z = Sun 22:00 ET -> week 2026-11-02
    df = make_picks(game(1, "win", "2026-11-10T03:00:00.000Z") + game(2, "loss", "2026-11-09T03:00:00.000Z"))
    t = weekly_trend(consensus_games(df), df, pd.DataFrame(columns=["expert_id", "rank"]))
    assert set(t.series) <= {"consensus_60plus", "top10_experts"}
    c = t[t.series == "consensus_60plus"].set_index("week_start")
    assert (c.loc["2026-11-09"].wins, c.loc["2026-11-02"].wins) == (1, 0)


def test_build_tables_empty_db_without_public(tmp_path):
    t = build_tables(db.connect(tmp_path / "e.db"), "2026-11-09T00:00:00.000Z")
    assert set(t) == {"Picks", "Consensus", "Experts", "Expert_Habits", "Trend_Weekly", "Upcoming", "Leaderboard", "Past_Plays"}
    assert all(df.empty for df in t.values())
    assert "tickets_pct" not in t["Upcoming"].columns and "tickets_pct" not in t["Picks"].columns
