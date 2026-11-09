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
