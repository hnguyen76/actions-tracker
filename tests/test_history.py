"""Season history tables stay separate from the live consensus and carry their source labels."""

import pandas as pd

from actions_tracker.analysis.history import (COUNT_BASIS, LINE_SOURCE, PLAY_COLS, add_season, history_plays,
                                              history_summary, history_weekly, load_history)


def side(game, market, s, picks, opp, result, day="T7-CN", week=1, league="ncaaf"):
    return dict(league=league, week=week, game_id=game, et_date="2026-09-06", day_group=day, away="AWY", home="HOM",
                away_score=20, home_score=10, market=market, side=s, picks=picks, opp_picks=opp, line=3.5,
                odds=-110, opp_odds=-110, tickets_pct=55, money_pct=60, fav_dog="underdog", result=result)


SIDES = pd.DataFrame([
    side(1, "spread", "away", 6, 2, "win"), side(1, "spread", "home", 2, 6, "loss"),
    side(1, "total", "over", 2, 2, "win"), side(1, "total", "under", 2, 2, "loss"),  # tie: no play
    side(2, "spread", "home", 2, 0, "loss"), side(2, "spread", "away", 0, 2, "win"),  # 2 picks: below minimum
    side(3, "ml", "home", 3, 1, "push", day="T2-6", week=2), side(3, "ml", "away", 1, 3, "push", day="T2-6", week=2),
])


def test_plays_majority_only_with_labels():
    p = history_plays(SIDES)
    assert list(p.columns) == PLAY_COLS
    assert sorted((r.game_id, r.market, r.pick, r.majority_pct) for r in p.itertuples()) == [
        (1, "spread", "AWY", 75.0), (3, "ml", "HOM", 75.0)]
    assert set(p.count_basis) == {COUNT_BASIS} and set(p.line_source) == {LINE_SOURCE}
    assert set(p.bucket) == {"75-90"}


def test_summary_counts_pushes_and_fade():
    s = history_summary(history_plays(SIDES)).set_index(["league", "day_group", "market", "bucket"])
    all_ = s.loc[("ALL", "ALL", "ALL", "ALL")]
    assert (all_.wins, all_.losses, all_.pushes) == (1, 0, 1)
    assert s.loc[("ncaaf", "T7-CN", "spread", "75-90")].fade_win_pct == 0.0


def test_weekly_per_league_week():
    w = history_weekly(history_plays(SIDES)).set_index(["league", "week", "day_group"])
    assert w.loc[("ncaaf", 1, "ALL")].wins == 1 and w.loc[("ncaaf", 2, "T2-6")].pushes == 1


def test_load_history_missing_dir_and_files(tmp_path):
    assert load_history(None).empty and load_history(tmp_path / "nope").empty
    SIDES.to_csv(tmp_path / "ncaaf_sides.csv", index=False)
    assert len(load_history(tmp_path)) == len(SIDES)
    assert history_plays(pd.DataFrame()).empty and history_summary(pd.DataFrame(columns=PLAY_COLS)).empty


def test_add_season_matches_day_group():
    summary = history_summary(history_plays(SIDES))
    up = pd.DataFrame([
        dict(league="ncaaf", market="spread", bucket="75-90", start_time="2026-11-14T17:00:00.000Z"),  # Sat
        dict(league="ncaaf", market="spread", bucket="75-90", start_time="2026-11-12T00:30:00.000Z"),  # Wed ET
        dict(league="nba", market="spread", bucket="75-90", start_time="2026-11-14T17:00:00.000Z"),
    ])
    out = add_season(up, summary)
    assert list(out.day_group) == ["T7-CN", "T2-6", "T7-CN"]
    assert out.season_n.iloc[0] == 1 and out.season_win_pct.iloc[0] == 1.0
    assert pd.isna(out.season_n.iloc[1]) and pd.isna(out.season_n.iloc[2])
    empty = add_season(up, pd.DataFrame())
    assert "season_win_pct" in empty.columns and empty.season_n.isna().all()
