import pandas as pd

from actions_tracker import db
from actions_tracker.analysis import build_tables
from actions_tracker.analysis.consensus import consensus_games
from actions_tracker.analysis.public import money_vs_tickets, public_games, public_summary
from actions_tracker.analysis.trend import weekly_trend
from tests.helpers import make_picks


def game(gid, tickets, result, start="2026-11-06T01:00:00.000Z", money=None):
    return [dict(pick_id=gid * 10 + i, expert_id=i, game_id=gid, market="spread", pick_side="home",
                 side_result=result, close_odds=-110, tickets_pct=tickets,
                 money_pct=tickets if money is None else money, start_time=start) for i in range(3)]


def test_relation_and_heavy():
    pg = public_games(consensus_games(make_picks(game(1, 70, "win") + game(2, 30, "loss") + game(3, 50, "win"))))
    r = pg.set_index("game_id")
    assert list(r.index) == [1, 2]
    assert (r.loc[1].relation, r.loc[1].heavy) == ("agree", True)
    assert (r.loc[2].relation, r.loc[2].heavy, r.loc[2].public_side) == ("contrarian", True, "away")
    s = public_summary(pg)
    assert s[(s.league == "ALL") & (s.market == "ALL") & (s.relation == "contrarian")].iloc[0].losses == 1


def test_money_vs_tickets_gap():
    df = make_picks(game(1, 35, "win", money=60) + game(2, 40, "loss", money=50))
    m = money_vs_tickets(df)
    row = m[(m.league == "ALL") & (m.market == "ALL")].iloc[0]
    assert (row.n, row.wins) == (1, 1)


def test_week_bucket_eastern():
    # 2026-11-10T03:00Z = Mon 22:00 ET -> week 2026-11-09; 2026-11-09T03:00Z = Sun 22:00 ET -> week 2026-11-02
    df = make_picks(game(1, 70, "win", "2026-11-10T03:00:00.000Z") + game(2, 70, "loss", "2026-11-09T03:00:00.000Z"))
    cg = consensus_games(df)
    t = weekly_trend(cg, df, pd.DataFrame(columns=["expert_id", "rank"]), public_games(cg))
    c = t[t.series == "consensus_60plus"].set_index("week_start")
    assert (c.loc["2026-11-09"].wins, c.loc["2026-11-02"].wins) == (1, 0)


def test_build_tables_empty_db(tmp_path):
    t = build_tables(db.connect(tmp_path / "e.db"), "2026-11-09T00:00:00.000Z")
    assert set(t) == {"Picks", "Consensus", "Experts", "Expert_Habits", "Expert_vs_Public", "Trend_Weekly",
                      "Upcoming", "Leaderboard"}
    assert all(df.empty for df in t.values())
