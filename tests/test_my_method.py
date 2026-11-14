"""The user's spread method: follow the crowd Mon-Fri, fade it Sat-Sun, spreads with at least 5 picks."""

import pandas as pd

from actions_tracker.analysis.my_method import PLAY_COLS, SUMMARY_COLS, my_method_plays, my_method_summary


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
