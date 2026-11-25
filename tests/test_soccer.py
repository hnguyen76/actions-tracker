"""Soccer from ESPN: DraftKings 1X2 / spread / total, the 90-minute score bets are graded on, and the owner's method
(Mon-Fri ET follow the expert majority; Sat-Sun fade the spread majority with at least five experts)."""

import json
from pathlib import Path

import pytest

from actions_tracker import soccer

FX = Path(__file__).parent / "fixtures"
EPL = json.loads((FX / "espn_soccer_epl.json").read_text("utf-8"))
EXTRA = json.loads((FX / "espn_soccer_extra_time.json").read_text("utf-8"))


def _event(events, short):
    return next(e for e in events if e["short"] == short)


def test_parse_events_reads_the_draftkings_1x2_spread_and_total():
    events = soccer.parse_events(EPL, "eng.1")
    lee = _event(events, "COV @ LEE")
    assert (lee["comp"], lee["event_id"], lee["start_time"], lee["state"]) == ("eng.1", lee["event_id"], "2026-11-28T15:00Z", "scheduled")
    assert (lee["home_name"], lee["away_name"], lee["home_abbr"], lee["away_abbr"]) == ("Leeds United", "Coventry City", "LEE", "COV")
    odds = lee["odds"]
    assert odds["ml"] == {"home": {"open": -165, "close": -210}, "draw": {"open": 300, "close": 350},
                          "away": {"open": 400, "close": 500}}
    assert odds["spread"]["home"] == {"open": {"line": -0.5, "odds": -185}, "close": {"line": -1.5, "odds": 120}}
    assert odds["spread"]["away"]["close"] == {"line": 1.5, "odds": -180}
    assert odds["total"]["over"]["close"] == {"line": 2.5, "odds": -160}
    assert odds["total"]["under"]["close"] == {"line": 2.5, "odds": 125}
    assert lee["score_90"] is None                                        # not played yet


@pytest.mark.parametrize("short,final,ninety,status", [
    ("LYON @ MAN", (5, 4), (2, 2), "STATUS_FINAL_AET"),     # 5-4 after extra time, 2-2 at 90'
    ("BODO @ LAZ", (3, 1), (2, 0), "STATUS_FINAL_PEN"),     # 90'+3' counts, 99'/109' do not, nor the shootout
    ("RMA @ ATM", (1, 0), (1, 0), "STATUS_FINAL_PEN"),
    ("DOR @ LILL", (1, 2), (1, 2), "STATUS_FULL_TIME"),
])
def test_score_after_90_minutes_ignores_extra_time_and_penalties(short, final, ninety, status):
    e = _event(soccer.parse_events(EXTRA, "uefa.europa"), short)
    assert (e["home_score"], e["away_score"]) == final and e["status"] == status
    assert e["score_90"] == ninety and e["state"] == "final"


@pytest.mark.parametrize("market,side,line,score,result", [
    ("ml", "draw", None, (2, 2), "win"), ("ml", "home", None, (2, 2), "loss"), ("ml", "away", None, (1, 2), "win"),
    ("spread", "home", -1.5, (2, 0), "win"), ("spread", "away", 1.5, (2, 0), "loss"),
    ("spread", "home", -1.0, (1, 0), "push"), ("spread", "home", -0.25, (1, 1), "half_loss"),
    ("spread", "away", 0.25, (1, 1), "half_win"), ("spread", "away", 0.75, (2, 1), "half_loss"),
    ("total", "over", 2.5, (2, 1), "win"), ("total", "under", 2.5, (2, 1), "loss"), ("total", "over", 3.0, (2, 1), "push"),
    ("total", "over", 2.75, (2, 1), "half_win"), ("total", "under", 2.25, (1, 1), "half_win"),
])
def test_grade_on_the_90_minute_score(market, side, line, score, result):
    assert soccer.grade(market, side, line, *score) == result


def _group(start, market, side, votes, total, game_id=1):
    return {"game_id": game_id, "start_time": start, "market": market, "side": side, "votes": votes, "total_votes": total}


def test_weekday_follows_the_majority_with_two_experts_in_every_market_draw_included():
    wed = "2026-11-25T20:00:00.000Z"                         # Wednesday 15:00 ET
    plays = soccer.method_plays([_group(wed, "ml", "draw", 2, 3), _group(wed, "total", "under", 2, 2),
                                 _group(wed, "spread", "home", 1, 1), _group(wed, "ml", "home", 3, 5, game_id=2)])
    got = {(p["game_id"], p["market"]): (p["method"], p["bet_side"], p["day_group"]) for p in plays}
    assert got == {(1, "ml"): ("follow", "draw", "T2-6"), (1, "total"): ("follow", "under", "T2-6"),
                   (2, "ml"): ("follow", "home", "T2-6")}


def test_weekend_fades_the_spread_majority_with_five_experts_only():
    sat = "2026-11-28T15:00:00.000Z"                         # Saturday 10:00 ET
    sun_late = "2026-11-30T01:30:00.000Z"                    # Sunday 20:30 ET (Monday in UTC)
    plays = soccer.method_plays([_group(sat, "spread", "home", 5, 5), _group(sat, "spread", "away", 3, 4, game_id=2),
                                 _group(sat, "ml", "home", 6, 6, game_id=3), _group(sat, "total", "over", 5, 6, game_id=4),
                                 _group(sun_late, "spread", "away", 4, 6, game_id=5)])
    got = {p["game_id"]: (p["method"], p["bet_side"], p["day_group"], p["et_date"]) for p in plays}
    assert got == {1: ("fade", "away", "T7-CN", "2026-11-28"), 5: ("fade", "home", "T7-CN", "2026-11-29")}
