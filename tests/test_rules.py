"""Frozen betting rules: public splits parsed and stored before kickoff, matching plays logged, graded after."""

import pathlib

import pytest

from actions_tracker import db
from actions_tracker.analysis.rule_report import PLAY_COLS, SUMMARY_COLS, rule_plays, rule_summary
from actions_tracker.parse import ParseError, extract_next_data, parse_public_page
from actions_tracker.rules import RULES, evaluate, sync_rule_plays

F = pathlib.Path(__file__).parent / "fixtures"
NOW = "2026-11-13T12:00:00.000Z"
SAT_DAY = "2026-11-14T17:00:00.000Z"    # Sat 12:00 ET
SAT_NIGHT = "2026-11-15T00:30:00.000Z"  # Sat 19:30 ET


def test_parse_public_page_real():
    html = (F / "ncaaf_public.html").read_text("utf-8")
    raw = extract_next_data(html)["props"]["pageProps"]["scoreboardResponse"]["games"]
    games, splits = parse_public_page(html, "ncaaf")
    assert len(games) == len(raw) and all(g["league"] == "ncaaf" and g["home_name"] for g in games)
    by = {(s["game_id"], s["market"], s["side"]): s for s in splits}
    under = by[(289944, "total", "under")]  # KENT@BGSU: 16% of bets but 50% of money on the under
    assert (under["line"], under["tickets_pct"], under["money_pct"]) == (41.5, 16, 50)
    assert by[(289944, "total", "over")]["tickets_pct"] == 84
    assert all(s["line"] is None for s in splits if s["market"] == "ml")
    assert {s["market"] for s in splits} == {"spread", "total", "ml"}


def test_parse_public_page_no_data_is_none_and_structure_change_raises():
    html = (F / "ncaaf_public.html").read_text("utf-8")
    _, splits = parse_public_page(html, "ncaaf")
    # a market where both sides show 0% has no public data yet (game 289987, spread)
    empty = [s for s in splits if s["game_id"] == 289987 and s["market"] == "spread"]
    assert len(empty) == 2 and all(s["tickets_pct"] is None and s["money_pct"] is None for s in empty)
    assert all(s["line"] is not None for s in empty)
    with pytest.raises(ParseError):
        parse_public_page('<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{}}}</script>',
                          "ncaaf")


def _conn(tmp_path):
    c = db.connect(tmp_path / "a.db")
    games = [dict(id=1, league="ncaaf", start_time=SAT_DAY, home_abbr="HOM", away_abbr="AWY"),
             dict(id=2, league="ncaaf", start_time=SAT_NIGHT, home_abbr="NHM", away_abbr="NAW"),
             dict(id=3, league="nfl", start_time=SAT_DAY, home_abbr="NFH", away_abbr="NFA")]
    db.upsert_games(c, games, "t")
    return c


def _picks(c, game, market, sides, line=None, league="ncaaf", start=100):
    rows = [dict(id=start + game * 100 + i + (50 if market == "total" else 0), expert_id=i, game_id=game,
                 league=league, market=market, pick_side=s, line=line.get(s) if line else None, odds=-110,
                 created_at="2026-11-12T10:00:00.000Z") for i, s in enumerate(sides)]
    db.upsert_picks(c, rows, "t")


def _split(game, market, side, line, tickets, money, odds=-110):
    return dict(game_id=game, market=market, side=side, line=line, odds=odds, tickets_pct=tickets, money_pct=money)


def test_public_splits_frozen_at_kickoff(tmp_path):
    c = _conn(tmp_path)
    db.upsert_public(c, [_split(1, "total", "over", 50.5, 70, 60)], NOW)
    db.upsert_public(c, [_split(1, "total", "over", 52.5, 80, 60)], "2026-11-14T18:00:00.000Z")  # after kickoff
    assert [tuple(r) for r in c.execute("select line, tickets_pct from public_splits")] == [(50.5, 70.0)]


def test_rules_match_expected_plays(tmp_path):
    c = _conn(tmp_path)
    # game 1 (day): experts 3-1 on the over -> R1 fades to the under; away dog has 3/4 spread picks -> R3 bets home
    _picks(c, 1, "total", ["over", "over", "over", "under"])
    _picks(c, 1, "spread", ["away", "away", "away", "home"], line={"away": 6.5, "home": -6.5})
    # game 2 (night): same expert split -> R1 does not apply; money far above tickets on the under -> R2
    _picks(c, 2, "total", ["over", "over", "over"])
    # game 3 is NFL: no rule applies
    _picks(c, 3, "total", ["over", "over", "over"], league="nfl")
    db.upsert_public(c, [
        _split(1, "total", "over", 50.5, 60, 62), _split(1, "total", "under", 50.5, 40, 38),
        _split(1, "spread", "away", 7.0, 55, 50), _split(1, "spread", "home", -7.0, 45, 50),
        _split(2, "total", "over", 44.5, 84, 60), _split(2, "total", "under", 44.5, 16, 40),
        _split(3, "total", "over", 41.5, 20, 60), _split(3, "total", "under", 41.5, 80, 40),
    ], NOW)
    got = {(p["rule_id"], p["game_id"]): p for p in evaluate(c, NOW)}
    assert set(got) == {("ncaaf_total_day_fade", 1), ("ncaaf_spread_away_dog_fade", 1), ("ncaaf_total_money", 2)}
    assert (got[("ncaaf_total_day_fade", 1)]["bet_side"], got[("ncaaf_total_day_fade", 1)]["line"]) == ("under", 50.5)
    assert (got[("ncaaf_spread_away_dog_fade", 1)]["bet_side"], got[("ncaaf_spread_away_dog_fade", 1)]["line"]) \
        == ("home", -7.0)
    assert got[("ncaaf_total_money", 2)]["bet_side"] == "under"
    assert {r["id"] for r in RULES} == {"ncaaf_total_day_fade", "ncaaf_total_money", "ncaaf_spread_away_dog_fade"}


def test_no_play_for_tie_few_experts_or_away_favourite(tmp_path):
    c = _conn(tmp_path)
    _picks(c, 1, "total", ["over", "over", "under", "under"])                      # tie
    _picks(c, 1, "spread", ["away", "away", "away"], line={"away": -3.5})           # away is the favourite
    assert evaluate(c, NOW) == []


def test_sync_updates_until_kickoff_then_freezes(tmp_path):
    c = _conn(tmp_path)
    _picks(c, 1, "total", ["over", "over", "over"])
    sync_rule_plays(c, NOW)
    assert [tuple(r) for r in c.execute("select rule_id, bet_side, first_logged_at from rule_plays")] \
        == [("ncaaf_total_day_fade", "under", NOW)]
    # three more experts take the under before kickoff: consensus is now a 3-3 tie -> the play is withdrawn
    db.upsert_picks(c, [dict(id=900 + i, expert_id=10 + i, game_id=1, league="ncaaf", market="total",
                             pick_side="under", created_at="2026-11-13T13:00:00.000Z") for i in range(3)], "t")
    sync_rule_plays(c, "2026-11-13T14:00:00.000Z")
    assert c.execute("select count(*) from rule_plays").fetchone()[0] == 0
    # a fourth under flips the consensus -> the rule now bets the over; after kickoff nothing changes any more
    db.upsert_picks(c, [dict(id=950, expert_id=20, game_id=1, league="ncaaf", market="total", pick_side="under",
                             created_at="2026-11-13T15:00:00.000Z")], "t")
    sync_rule_plays(c, "2026-11-13T16:00:00.000Z")
    db.upsert_picks(c, [dict(id=960 + i, expert_id=30 + i, game_id=1, league="ncaaf", market="total",
                             pick_side="over", created_at="2026-11-14T18:00:00.000Z") for i in range(5)], "t")
    sync_rule_plays(c, "2026-11-14T18:30:00.000Z")
    assert [tuple(r) for r in c.execute("select bet_side, logged_at from rule_plays")] \
        == [("over", "2026-11-13T16:00:00.000Z")]


def test_report_grades_at_closing_line_and_summarises(tmp_path):
    c = _conn(tmp_path)
    _picks(c, 1, "total", ["over", "over", "over"])
    db.upsert_public(c, [_split(1, "total", "under", 50.5, 40, 38), _split(1, "total", "over", 50.5, 60, 62)], NOW)
    sync_rule_plays(c, NOW)
    assert rule_plays(c).iloc[0].status == "pending"
    # closing line (The Odds API) moved to 48.5; final 27-21 = 48 -> under 48.5 wins, the logged 50.5 is not used
    db.upsert_lines(c, [dict(game_id=1, market="total", side="under", line=48.5, odds=-105)], NOW)
    db.upsert_games(c, [dict(id=1, status="complete", home_score=27, away_score=21)], "t2")
    plays = rule_plays(c)
    assert list(plays.columns) == PLAY_COLS
    p = plays.iloc[0]
    assert (p.status, p.result, p.line, p.line_source, p.pick) == ("graded", "win", 48.5, "odds_api_close", "Under")
    s = rule_summary(plays)
    assert list(s.columns) == SUMMARY_COLS and len(s) == len(RULES)
    r = s.set_index("rule_id").loc["ncaaf_total_day_fade"]
    assert (r.wins, r.losses, r.pending, r.decision) == (1, 0, 0, "collecting")
    assert s.set_index("rule_id").loc["ncaaf_total_money"].n == 0
