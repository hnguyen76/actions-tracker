import pandas as pd

from actions_tracker.analysis.decisions import DECISION_COLS, decisions

NOW = "2026-11-14T15:00:00.000Z"
LATER = "2026-11-14T20:00:00.000Z"  # Sat 15:00 ET
PAST = "2026-11-14T12:00:00.000Z"


def play(rule, game, side, pick, line=50.5, market="total", start=LATER, status="pending", name=None):
    return dict(rule_id=rule, rule_name=name or rule, league="ncaaf", game_id=game, start_time=start, match="A@H",
                market=market, bet_side=side, pick=pick, line=line, basis=f"basis {rule}", status=status)


def summary(**states):
    return pd.DataFrame([dict(rule_id=r, decision=d, hist_record="10-5", wins=0, losses=0, pushes=0, n=0,
                              target_n=100) for r, d in states.items()])


UP = pd.DataFrame([dict(game_id=9, league="nfl", market="spread", start_time=LATER, side="home", home_abbr="KC",
                        away_abbr="BUF", votes=3, total_votes=4),
                   dict(game_id=1, league="ncaaf", market="total", start_time=LATER, side="over", home_abbr="H",
                        away_abbr="A", votes=3, total_votes=3)])


def test_collecting_rule_is_paper_consensus_is_skip_and_covered_once():
    rp = pd.DataFrame([play("r1", 1, "under", "Under")])
    d = decisions(rp, summary(r1="collecting"), UP, NOW)
    assert list(d.columns) == DECISION_COLS
    assert [(r.game_id, r.action, r.stake_u) for r in d.itertuples()] == [(1, "paper", 0.0), (9, "skip", 0.0)]
    assert d.iloc[0].pick == "Under 50,5" and "basis r1" in d.iloc[0].reason
    assert d.iloc[1].pick == "Đa số chọn KC (3/4)"


def test_passed_rule_bets_one_unit_and_failed_rule_skips():
    rp = pd.DataFrame([play("r1", 1, "under", "Under"), play("r2", 2, "home", "H", line=-3.5, market="spread")])
    d = decisions(rp, summary(r1="pass", r2="fail"), pd.DataFrame(), NOW).set_index("game_id")
    assert (d.loc[1].action, d.loc[1].stake_u) == ("bet", 1.0)
    assert (d.loc[2].action, d.loc[2].pick) == ("skip", "H -3,5")


def test_opposite_rules_conflict_and_started_games_drop_out():
    rp = pd.DataFrame([play("r1", 1, "under", "Under"), play("r2", 1, "over", "Over"),
                       play("r1", 3, "under", "Under", start=PAST)])
    d = decisions(rp, summary(r1="pass", r2="pass"), pd.DataFrame(), NOW)
    assert len(d) == 1 and d.iloc[0].action == "conflict" and d.iloc[0].stake_u == 0.0


def test_empty_inputs():
    assert decisions(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), NOW).empty
