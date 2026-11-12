import math

from actions_tracker.analysis.consensus import consensus_games, consensus_summary, upcoming
from tests.helpers import make_picks

FLIP = {"win": "loss", "loss": "win", "push": "push"}


def votes(game, sides, result_home="win", status="complete", market="spread"):
    return [dict(pick_id=game * 100 + i, expert_id=i, game_id=game, market=market, pick_side=s, status=status,
                 side_result=(result_home if s == "home" else FLIP[result_home]),
                 close_odds=-110, opp_close_odds=-110, start_time="2026-11-20T01:00:00.000Z")
            for i, s in enumerate(sides)]


def test_bucket_votes_and_min_experts():
    df = make_picks(votes(1, ["home"] * 3 + ["away"]) + votes(2, ["home", "away"])
                    + votes(3, ["home", "home", "away", "away"]))
    cg = consensus_games(df)
    assert list(cg.game_id) == [1]
    r = cg.iloc[0]
    assert (r.side, r.votes, r.total_votes, r.majority_pct, r.bucket) == ("home", 3, 4, 75.0, "75-90")


def test_latest_pick_per_expert_counts_once():
    rows = votes(1, ["home", "home", "home"])
    rows[0]["created_at"] = "2026-11-09T10:00:00.000Z"
    rows.append(dict(rows[0], pick_id=999, pick_side="away", created_at="2026-11-09T23:00:00.000Z"))
    r = consensus_games(make_picks(rows)).iloc[0]
    assert (r.votes, r.total_votes) == (2, 3)


def test_summary_follow_and_fade():
    df = make_picks(votes(1, ["home"] * 3, "win") + votes(2, ["home"] * 3, "loss") + votes(3, ["home"] * 3, "win"))
    s = consensus_summary(consensus_games(df))
    row = s[(s.league == "nfl") & (s.market == "spread") & (s.bucket == "90-100")].iloc[0]
    assert (row.n, row.wins) == (3, 2) and math.isclose(row.fade_win_pct, 1 / 3)
    tot = s[(s.league == "ALL") & (s.market == "ALL") & (s.bucket == "90-100")].iloc[0]
    assert tot.n == 3


def test_upcoming_excludes_past_and_completed():
    df = make_picks(votes(1, ["home"] * 3, status="scheduled") + votes(2, ["away"] * 3, status="postponed")
                    + [dict(r, start_time="2026-11-01T00:00:00.000Z")
                       for r in votes(3, ["home"] * 3, status="scheduled")])
    cg = consensus_games(df)
    up = upcoming(cg, consensus_summary(cg), now="2026-11-10T00:00:00.000Z")
    assert list(up.game_id) == [1, 2]


def test_empty_inputs():
    cg = consensus_games(make_picks([]))
    s = consensus_summary(cg)
    up = upcoming(cg, s, now="2026-11-10T00:00:00.000Z")
    assert cg.empty and s.empty and up.empty
    assert "bucket" in cg.columns and "hist_win_pct" in up.columns


def test_past_plays_day_groups_and_labels():
    from actions_tracker.analysis.consensus import past_plays
    rows = (votes(1, ["home"] * 3, "win") + votes(2, ["away"] * 3, "loss") + votes(3, ["home"] * 3, status="scheduled"))
    for r in rows:
        r.update(home_abbr=f"H{r['game_id']}", away_abbr=f"A{r['game_id']}")
        # game 1: Thu 20:15 ET; game 2: Sun 22:00 ET (= Mon 03:00 UTC); game 3: not played
        r["start_time"] = {1: "2026-11-06T01:15:00.000Z", 2: "2026-11-09T03:00:00.000Z", 3: "2026-11-20T01:00:00.000Z"}[r["game_id"]]
    total = [dict(pick_id=900 + i, expert_id=i, game_id=1, market="total", pick_side="under", side_result="loss",
                  home_abbr="H1", away_abbr="A1", start_time="2026-11-06T01:15:00.000Z") for i in range(3)]
    pp = past_plays(consensus_games(make_picks(rows + total))).set_index(["game_id", "market"])
    assert set(pp.index) == {(1, "spread"), (1, "total"), (2, "spread")}
    assert pp.loc[(1, "spread")].day_group == "T2-6" and pp.loc[(2, "spread")].day_group == "T7-CN"
    assert (pp.loc[(1, "spread")].pick, pp.loc[(2, "spread")].pick, pp.loc[(1, "total")].pick) == ("H1", "A2", "Under")
    assert pp.loc[(2, "spread")].et_date == "2026-11-08" and pp.loc[(1, "spread")].match == "A1@H1"


def test_past_plays_empty():
    from actions_tracker.analysis.consensus import past_plays
    out = past_plays(consensus_games(make_picks([])))
    assert out.empty and {"day_group", "pick", "match"} <= set(out.columns)


def test_upcoming_board_lists_every_game_with_status():
    from actions_tracker.analysis.consensus import BOARD_COLS, upcoming_board
    rows = (votes(1, ["home"] * 3 + ["away"], status=None)                       # majority
            + votes(2, ["home", "home", "home", "away", "away", "away"], status=None)  # 3-3 split
            + votes(3, ["over", "over"], status=None, market="total")             # only 2 experts
            + votes(4, ["home"] * 3, status="complete"))                          # already played: not listed
    for r in rows:
        r["line"] = {"home": -1.5, "away": 2.5, "over": 43.5}[r["pick_side"]]
    b = upcoming_board(make_picks(rows), "2026-11-19T00:00:00.000Z")
    assert list(b.columns) == BOARD_COLS
    got = {(r.game_id, r.market): r for r in b.itertuples()}
    assert set(got) == {(1, "spread"), (2, "spread"), (3, "total")}
    assert (got[(1, "spread")].status, got[(1, "spread")].b_votes, got[(1, "spread")].a_votes) == ("majority", 3, 1)
    assert (got[(2, "spread")].status, got[(2, "spread")].a_line, got[(2, "spread")].b_line) == ("split", 2.5, -1.5)
    assert (got[(3, "total")].status, got[(3, "total")].a_side, got[(3, "total")].a_votes) == ("few", "over", 2)
    assert got[(3, "total")].b_votes == 0
