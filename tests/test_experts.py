from actions_tracker.analysis.experts import expert_habits, expert_summary, leaderboard
from tests.helpers import make_picks

NOW = "2026-11-09T00:00:00.000Z"


def mk(expert, n, result, fav="favorite", start="2026-11-05T00:00:00.000Z", market="spread"):
    return [dict(pick_id=expert * 1000 + i + (500 if result == "loss" else 0), expert_id=expert, game_id=i,
                 market=market, pick_side="home", expert_result=result, fav_dog=fav, home_away="home",
                 start_time=start) for i in range(n)]


def test_summary_windows():
    df = make_picks(mk(1, 20, "win") + mk(1, 15, "loss", start="2026-09-01T00:00:00.000Z"))
    s = expert_summary(df, now=NOW).set_index(["league", "market", "window"])
    assert s.loc[("ALL", "ALL", "all")].n == 35
    assert s.loc[("ALL", "ALL", "last_30_days")].n == 20
    assert s.loc[("ALL", "ALL", "last_30_picks")].wins == 20 and s.loc[("ALL", "ALL", "last_30_picks")].n == 30


def test_habits_share_and_win():
    df = make_picks(mk(1, 3, "win", fav="underdog") + mk(1, 1, "loss", fav="favorite"))
    h = expert_habits(df)
    r = h[(h.league == "ALL") & (h.label_type == "fav_dog") & (h.label == "underdog")].iloc[0]
    assert r.share == 0.75 and r.win_pct == 1.0


def test_leaderboard_min_sample_and_order():
    df = make_picks(mk(1, 25, "win") + mk(2, 25, "loss") + mk(3, 5, "win"))
    lb = leaderboard(expert_summary(df, now=NOW))
    assert list(lb.expert_id) == [1, 2] and list(lb["rank"]) == [1, 2]


def test_ungraded_picks_ignored_in_windows():
    df = make_picks(mk(1, 2, "win") + [dict(pick_id=9, expert_id=1, game_id=99, market="spread", pick_side="home",
                                             expert_result=None, start_time="2026-11-08T00:00:00.000Z")])
    s = expert_summary(df, now=NOW).set_index(["league", "market", "window"])
    assert s.loc[("ALL", "ALL", "last_30_picks")].n == 2


def test_empty():
    df = make_picks([])
    s = expert_summary(df, now=NOW)
    assert s.empty and expert_habits(df).empty and leaderboard(s).empty
    assert "rank" in leaderboard(s).columns


def test_clv_points_by_market_and_side():
    from actions_tracker.analysis.experts import CLV_COLS, expert_clv
    started = "2026-11-08T18:00:00.000Z"
    rows = [
        dict(pick_id=1, expert_id=1, game_id=1, market="spread", pick_side="away", line=3.5, close_line=2.5, start_time=started),   # +1.0
        dict(pick_id=2, expert_id=1, game_id=2, market="spread", pick_side="home", line=-3.5, close_line=-2.5, start_time=started), # -1.0
        dict(pick_id=3, expert_id=1, game_id=3, market="total", pick_side="over", line=44.5, close_line=46.5, start_time=started),  # +2.0
        dict(pick_id=4, expert_id=1, game_id=4, market="total", pick_side="under", line=44.5, close_line=44.5, start_time=started), # 0
        dict(pick_id=5, expert_id=1, game_id=5, market="ml", pick_side="home", line=None, close_line=None, start_time=started),     # ignored
        dict(pick_id=6, expert_id=1, game_id=6, market="spread", pick_side="away", line=7.0, close_line=None, start_time=started),  # no close
        dict(pick_id=7, expert_id=1, game_id=7, market="spread", pick_side="away", line=7.0, close_line=6.0,
             start_time="2026-11-30T18:00:00.000Z"),                                                                              # not started
    ]
    t = expert_clv(make_picks(rows), NOW)
    assert list(t.columns) == CLV_COLS
    r = t.set_index(["expert_id", "league", "market"]).loc[(1, "ALL", "ALL")]
    assert (r.n, r.avg_clv, r.beat, r.same, r.worse, r.beat_pct) == (4, 0.5, 2, 1, 1, 0.5)
    assert t.set_index(["expert_id", "league", "market"]).loc[(1, "nfl", "total")].avg_clv == 1.0
    assert expert_clv(make_picks([]), NOW).empty
