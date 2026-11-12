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
    t = weekly_trend(consensus_games(df), df)
    assert set(t.series) <= {"consensus_60plus", "top10_experts"}
    c = t[t.series == "consensus_60plus"].set_index("week_start")
    assert (c.loc["2026-11-09"].wins, c.loc["2026-11-02"].wins) == (1, 0)


def test_build_tables_empty_db_without_public(tmp_path):
    t = build_tables(db.connect(tmp_path / "e.db"), "2026-11-09T00:00:00.000Z")
    assert set(t) == {"Picks", "Consensus", "Experts", "Expert_Habits", "Trend_Weekly", "Upcoming", "Leaderboard", "Past_Plays",
                      "Expert_Form", "Expert_Form_Now",
                      "History_Plays", "History_Summary", "History_Weekly",
                      "Upcoming_Board", "Rule_Summary", "Rule_Plays", "Expert_CLV", "Decisions"}
    assert all(df.empty for name, df in t.items() if name != "Rule_Summary")
    assert len(t["Rule_Summary"]) == 3 and (t["Rule_Summary"].n == 0).all()  # one row per rule, no plays yet
    assert "tickets_pct" not in t["Upcoming"].columns and "tickets_pct" not in t["Picks"].columns


def test_top10_ranked_only_on_earlier_weeks():
    wk1, wk2 = "2026-11-03T01:00:00.000Z", "2026-11-10T01:00:00.000Z"  # Mon 2 Nov / Mon 9 Nov ET
    picks = [dict(pick_id=i, expert_id=1, game_id=i, market="spread", pick_side="home", expert_result="win",
                  start_time=wk1) for i in range(20)]
    picks += [dict(pick_id=100 + i, expert_id=e, game_id=100 + i, market="spread", pick_side="home",
                   expert_result=r, start_time=wk2) for i, (e, r) in enumerate([(1, "loss"), (1, "loss"), (2, "win")])]
    picks += [dict(pick_id=200 + i, expert_id=2, game_id=200 + i, market="spread", pick_side="home",
                   expert_result="win", start_time=wk2) for i in range(30)]
    df = make_picks(picks)
    top = weekly_trend(consensus_games(df), df).query("series == 'top10_experts'").set_index("week_start")
    # week 1: nobody had 20 graded picks before it; week 2: only expert 1 qualified (expert 2's picks are all in week 2)
    assert "2026-11-02" not in top.index
    assert (top.loc["2026-11-09"].n, top.loc["2026-11-09"].wins) == (2, 0)
