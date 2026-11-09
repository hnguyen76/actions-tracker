import pytest

from actions_tracker import db
from actions_tracker.grading import grade_side, load_graded_picks


@pytest.mark.parametrize("market,side,line,h,a,exp", [
    ("spread", "home", -3.5, 24, 20, "win"), ("spread", "home", -3.5, 23, 20, "loss"),
    ("spread", "home", -3.0, 23, 20, "push"), ("spread", "away", 3.0, 23, 20, "push"),
    ("spread", "away", 7.5, 27, 20, "win"), ("ml", "away", None, 17, 24, "win"),
    ("ml", "home", None, 20, 20, "push"), ("total", "over", 44.5, 24, 21, "win"),
    ("total", "under", 45.0, 24, 21, "push"), ("total", "under", 44.5, 24, 21, "loss")])
def test_grade_side(market, side, line, h, a, exp):
    assert grade_side(market, side, line, h, a) == exp


def _seed(tmp_path, status="complete", pick_odds=-110, an_result=None):
    c = db.connect(tmp_path / "g.db")
    db.upsert_experts(c, [dict(id=1, name="A", username="a", followers=1)], "t")
    db.upsert_games(c, [dict(id=100, league="nfl", season=2026, week=9, start_time="2026-11-10T01:00:00.000Z",
                             status="scheduled", home_team_id=10, away_team_id=20, home_abbr="HOM", away_abbr="AWY",
                             home_score=None, away_score=None)], "t")
    db.upsert_lines(c, [
        dict(game_id=100, market="spread", side="home", line=-3.0, odds=-105, tickets_pct=40, money_pct=60),
        dict(game_id=100, market="spread", side="away", line=3.0, odds=-115, tickets_pct=60, money_pct=40),
        dict(game_id=100, market="ml", side="home", line=None, odds=-150, tickets_pct=50, money_pct=50),
        dict(game_id=100, market="ml", side="away", line=None, odds=130, tickets_pct=50, money_pct=50)],
        "2026-11-09T00:00:00.000Z")
    done = status == "complete"
    db.upsert_games(c, [dict(id=100, status=status, home_score=23 if done else None,
                             away_score=20 if done else None)], "t2")
    db.upsert_picks(c, [
        dict(id=11, expert_id=1, game_id=100, league="nfl", market="spread", pick_side="home", line=-2.5,
             odds=pick_odds, units=1, an_result=an_result, created_at="2026-11-09T10:00:00.000Z", starts_at=None,
             settled_at=None, play_text=""),
        dict(id=12, expert_id=1, game_id=100, league="nfl", market="ml", pick_side="away", line=None,
             odds=130, units=1, an_result=None, created_at="2026-11-09T10:00:00.000Z", starts_at=None,
             settled_at=None, play_text="")], "t")
    return c


def test_closing_vs_expert_line(tmp_path):
    df = load_graded_picks(_seed(tmp_path)).set_index("pick_id")
    r = df.loc[11]
    assert r.side_result == "push"
    assert r.expert_result == "win"
    assert (r.fav_dog, r.home_away, r.over_under) == ("favorite", "home", None)
    assert (r.close_odds, r.opp_close_odds, r.tickets_pct) == (-105, -115, 40)
    assert r.expert_name == "A"
    assert df.loc[12].fav_dog == "underdog"
    assert df.loc[12].side_result == "loss"


def test_an_result_is_ignored_self_grade_wins(tmp_path):
    df = load_graded_picks(_seed(tmp_path, an_result="loss")).set_index("pick_id")
    assert df.loc[11].expert_result == "win"  # spec §12.1: only picks come from Action Network


def test_missing_pick_odds_does_not_break(tmp_path):
    df = load_graded_picks(_seed(tmp_path, pick_odds=None)).set_index("pick_id")
    assert df.loc[11].expert_result == "win"


@pytest.mark.parametrize("status", ["postponed", "cancelled", "inprogress"])
def test_not_complete_not_graded(tmp_path, status):
    df = load_graded_picks(_seed(tmp_path, status=status))
    assert df.side_result.isna().all() and df.expert_result.isna().all()


def test_empty_db_has_columns(tmp_path):
    df = load_graded_picks(db.connect(tmp_path / "e.db"))
    assert df.empty and {"side_result", "expert_result", "fav_dog"} <= set(df.columns)


def test_an_result_not_used_when_no_score(tmp_path):
    df = load_graded_picks(_seed(tmp_path, status="scheduled", an_result="win")).set_index("pick_id")
    assert df.loc[11].expert_result is None and df.loc[11].side_result is None


def test_an_result_ignored_for_cancelled_game(tmp_path):
    df = load_graded_picks(_seed(tmp_path, status="cancelled", an_result="win")).set_index("pick_id")
    assert df.loc[11].expert_result is None
