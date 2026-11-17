"""The user's spread method: follow the crowd Mon-Fri, fade it Sat-Sun, spreads with at least 5 picks."""

import pandas as pd

from actions_tracker.analysis.my_method import (DECISION_PLAY_COLS, PLAY_COLS, SEASON_COLS, SUMMARY_COLS,
                                                decision_method_plays, my_method_plays, my_method_summary,
                                                season_plays, season_sensitivity, season_summary)


def _cg(rows):
    base = dict(market="spread", status="complete", side_odds=-110, opp_odds=-110, home_abbr="HOM", away_abbr="AWY")
    return pd.DataFrame([base | r for r in rows])


CG = _cg([
    # Thu 20:15 ET, 5 of 6 on the home side -> follow -> home won ATS
    dict(game_id=1, league="nfl", start_time="2026-11-13T01:15:00.000Z", side="home", votes=5, total_votes=6,
         side_result="win"),
    # Sat 12:00 ET, crowd on the away side -> fade (bet home) -> crowd won, so our bet lost
    dict(game_id=2, league="ncaaf", start_time="2026-11-14T17:00:00.000Z", side="away", votes=6, total_votes=7,
         side_result="win"),
    # Sat, only 4 experts -> not part of the method
    dict(game_id=3, league="ncaaf", start_time="2026-11-14T17:00:00.000Z", side="away", votes=4, total_votes=4,
         side_result="loss"),
    # Sun, upcoming -> pending
    dict(game_id=4, league="nfl", start_time="2026-11-15T18:00:00.000Z", side="home", votes=5, total_votes=5,
         side_result=None, status=None),
    # NBA is not part of it
    dict(game_id=5, league="nba", start_time="2026-11-13T01:00:00.000Z", side="home", votes=6, total_votes=6,
         side_result="win"),
])
PICKS = pd.DataFrame([
    dict(game_id=2, market="spread", pick_side="away", line=6.5, close_line=7.0),
    dict(game_id=1, market="spread", pick_side="home", line=-3.0, close_line=None),
])


def test_plays_follow_on_weekdays_and_fade_on_weekends():
    p = my_method_plays(CG, PICKS).set_index("game_id")
    assert list(p.reset_index().columns) == PLAY_COLS and set(p.index) == {1, 2, 4}
    assert (p.loc[1, "method"], p.loc[1, "pick"], p.loc[1, "line"], p.loc[1, "result"]) == ("follow", "HOM", -3.0, "win")
    # fading the away crowd: bet home at minus the away closing line
    assert (p.loc[2, "method"], p.loc[2, "pick"], p.loc[2, "line"], p.loc[2, "result"]) == ("fade", "HOM", -7.0, "loss")
    assert (p.loc[4, "status"], p.loc[4, "day_group"]) == ("pending", "T7-CN")


def test_decision_method_expands_weekdays_to_two_votes_all_markets_and_nba():
    cg = _cg([
        dict(game_id=10, league="nfl", market="spread", start_time="2026-11-17T01:15:00Z", side="away",
             votes=2, total_votes=3, side_result="win"),
        dict(game_id=11, league="nba", market="total", start_time="2026-11-18T00:00:00Z", side="under",
             votes=2, total_votes=2, side_result="loss", home_abbr="BOS", away_abbr="NYK"),
        dict(game_id=12, league="nba", market="ml", start_time="2026-11-18T01:00:00Z", side="home",
             votes=1, total_votes=1, side_result="win"),
        dict(game_id=13, league="ncaaf", market="spread", start_time="2026-11-21T17:00:00Z", side="home",
             votes=5, total_votes=6, side_result="win"),
        dict(game_id=14, league="nba", market="spread", start_time="2026-11-21T17:00:00Z", side="home",
             votes=6, total_votes=7, side_result="win"),
    ])
    picks = pd.DataFrame([
        dict(game_id=10, market="spread", pick_side="away", line=3.5, close_line=3.0),
        dict(game_id=11, market="total", pick_side="under", line=222.5, close_line=221.5),
        dict(game_id=13, market="spread", pick_side="home", line=-4.5, close_line=-4.0),
    ])
    out = decision_method_plays(cg, picks).set_index("game_id")
    assert list(out.reset_index().columns) == DECISION_PLAY_COLS and set(out.index) == {10, 11, 13}
    assert (out.loc[10, "method"], out.loc[10, "pick"], out.loc[10, "line"]) == ("follow", "AWY", 3.0)
    assert (out.loc[11, "league"], out.loc[11, "market"], out.loc[11, "pick"], out.loc[11, "line"]) == \
        ("nba", "total", "Under", 221.5)
    assert (out.loc[13, "method"], out.loc[13, "pick"], out.loc[13, "result"]) == ("fade", "AWY", "loss")


def test_summary_live_and_season_lookback():
    sides = pd.DataFrame([
        dict(league="ncaaf", market="spread", day_group="T2-6", picks=5, opp_picks=1, result="win"),
        dict(league="ncaaf", market="spread", day_group="T7-CN", picks=6, opp_picks=0, result="win"),   # fade -> loss
        dict(league="ncaaf", market="spread", day_group="T7-CN", picks=3, opp_picks=1, result="loss"),  # < 5 picks
        dict(league="ncaaf", market="total", day_group="T2-6", picks=6, opp_picks=0, result="win"),     # not spread
    ])
    s = my_method_summary(my_method_plays(CG, PICKS), sides)
    assert list(s.columns) == SUMMARY_COLS and len(s) == 9
    r = s.set_index(["league", "day_group"])
    assert (r.loc[("ncaaf", "T2-6"), "hist_wins"], r.loc[("ncaaf", "T7-CN"), "hist_losses"]) == (1, 1)
    assert (r.loc[("ALL", "ALL"), "wins"], r.loc[("ALL", "ALL"), "losses"], r.loc[("ALL", "ALL"), "pending"]) == (1, 1, 1)
    assert r.loc[("nfl", "T2-6"), "method"] == "follow" and r.loc[("nfl", "T7-CN"), "method"] == "fade"



def test_season_uses_history_then_live_games_not_in_it():
    sides = pd.DataFrame([
        # Thu (week 10): 6 of 7 on the away side -> follow -> away covered
        dict(league="nfl", week=10, game_id=1, et_date="2026-11-12", day_group="T2-6", away="WAS", home="NYG",
             away_score=24, home_score=20, market="spread", side="away", picks=6, opp_picks=1, line=1.5, odds=-110,
             opp_odds=-110, result="win"),
        # Sat: 5 of 5 on home -> fade (bet away at +3) -> home covered, so we lose
        dict(league="ncaaf", week=11, game_id=2, et_date="2026-11-14", day_group="T7-CN", away="WF", home="SMU",
             away_score=7, home_score=49, market="spread", side="home", picks=5, opp_picks=0, line=-3.0, odds=-110,
             opp_odds=-105, result="win"),
        dict(league="ncaaf", week=11, game_id=3, et_date="2026-11-14", day_group="T7-CN", away="A", home="B",
             away_score=1, home_score=2, market="spread", side="home", picks=3, opp_picks=1, line=-3.0, odds=-110,
             opp_odds=-110, result="win"),                                     # < 5 picks -> left out
    ])
    live = my_method_plays(CG, PICKS)        # games 1 (also in history -> skipped), 2, 4 (live only)
    s = season_plays(sides, live, {4: {"week": 11, "away_score": None, "home_score": None}})
    assert list(s.columns) == SEASON_COLS
    by = s.set_index("game_id")
    assert set(by.index) == {1, 2, 4} and by.loc[1, "source"] == "history" and by.loc[4, "source"] == "live"
    assert (by.loc[2, "pick"], by.loc[2, "line"], by.loc[2, "result"], by.loc[2, "score"]) == ("WF", 3.0, "loss", "7-49")
    assert by.loc[4, "week"] == 11 and pd.isna(by.loc[4, "result"])
    summ = season_summary(s).set_index(["league", "week", "day_group"])
    assert (summ.loc[("nfl", "ALL", "ALL"), "wins"], summ.loc[("ncaaf", 11, "T7-CN"), "losses"]) == (1, 1)



def test_sensitivity_by_pick_threshold_and_crowd_type():
    plays = pd.DataFrame([
        dict(league="ncaaf", day_group="T7-CN", votes=5, total_votes=5, result="win", odds=-110),     # unanimous
        dict(league="ncaaf", day_group="T7-CN", votes=8, total_votes=9, result="loss", odds=-110),    # mixed
        dict(league="ncaaf", day_group="T2-6", votes=12, total_votes=12, result="win", odds=-110),
        dict(league="ncaaf", day_group="T2-6", votes=12, total_votes=12, result=None, odds=-110),     # pending
    ])
    s = season_sensitivity(plays).set_index(["league", "min_picks", "crowd_type", "day_group"])
    assert (s.loc[("ncaaf", 5, "ALL", "ALL"), "wins"], s.loc[("ncaaf", 5, "ALL", "ALL"), "losses"]) == (2, 1)
    assert (s.loc[("ncaaf", 5, "unanimous", "ALL"), "wins"], s.loc[("ncaaf", 5, "mixed", "ALL"), "losses"]) == (2, 1)
    assert (s.loc[("ncaaf", 9, "mixed", "T7-CN"), "losses"], s.loc[("ncaaf", 10, "unanimous", "T2-6"), "wins"]) == (1, 1)
    assert s.loc[("nfl", 8, "ALL", "ALL"), "n"] == 0
