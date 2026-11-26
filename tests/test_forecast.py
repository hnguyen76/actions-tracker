"""Forecast for the user's method: past win rate of the same situation, shrunk to 50%, checked walk-forward."""

import pandas as pd

from actions_tracker.analysis import forecast as fc


def _play(week, result, votes=6, total=7, league="ncaaf", dg="T7-CN", start=None):
    return dict(league=league, week=week, game_id=week * 1000 + votes, start_time=start, et_date="2026-11-14",
                day_group=dg, match="A@B", crowd="B", votes=votes, total_votes=total, method="fade", pick="A",
                line=3.0, odds=-110, result=result)


def test_predict_uses_specific_situation_with_enough_plays_and_shrinks():
    hist = pd.DataFrame([_play(1, "win")] * 15 + [_play(1, "loss")] * 5)       # 20 plays, mixed, 5-7 picks: 15-5
    counts = fc.fit(hist)
    r = fc._prep(pd.DataFrame([_play(9, None)])).to_dict("records")[0]
    f = fc.predict(r, counts)
    assert f["basis_n"] == 20 and "không đồng thuận" in f["basis"] and "5-7 picks" in f["basis"]
    assert abs(f["p_win"] - (15 + 10) / 40) < 1e-9                              # 75% raw -> 62.5% after the prior
    # a unanimous play has no situation of its own -> falls back to the league x day group
    u = fc._prep(pd.DataFrame([_play(9, None, votes=5, total=5)])).to_dict("records")[0]
    assert fc.predict(u, counts)["basis"] == "NCAAF · Sat–Sun"


def test_forecast_upcoming_and_walk_forward():
    plays = [_play(w, "win" if i % 3 else "loss") for w in range(1, 6) for i in range(9)]
    plays.append(_play(6, None, start="2026-11-15T18:00:00.000Z"))
    season = pd.DataFrame(plays)
    up = fc.forecast_upcoming(season, "2026-11-14T00:00:00.000Z")
    assert list(up.columns) == fc.FORECAST_COLS and len(up) == 1 and 0.5 < up.iloc[0].p_win < 2 / 3
    bt = fc.walk_forward(season).set_index(["league", "p_bucket"])
    assert list(fc.walk_forward(season).columns) == fc.BACKTEST_COLS
    # weeks 3-5 are predicted from earlier weeks only: 27 plays, 18-9
    assert bt.loc[("ALL", "Trên hòa vốn (đặt)"), "n"] == 27 and bt.loc[("ALL", "Trên hòa vốn (đặt)"), "wins"] == 18
    assert len(fc.cells(season)) == 1
