"""Soccer board: the phone polls ESPN for the next week, keeps every DraftKings line move, and ranks upcoming games by
how far the market has moved since it opened (no-vig implied probability, percentage points)."""

import copy
import json
from pathlib import Path

import pytest

from actions_tracker import db, soccer

FX = Path(__file__).parent / "fixtures"
EPL = json.loads((FX / "espn_soccer_epl.json").read_text("utf-8"))
NOW = "2026-11-25T17:30:00.000Z"        # Wednesday 12:30 ET; the fixture games are Saturday 28/11 10:00 ET


class Get:
    def __init__(self, board=EPL):
        self.board, self.urls = board, []

    def __call__(self, url, **kw):
        self.urls.append(url)
        body = self.board if "/eng.1/" in url and "dates=20261128" in url else {"events": []}

        class R:
            status_code = 200

            def json(self):
                return copy.deepcopy(body)
        return R()


def _history(conn):
    return [tuple(r) for r in conn.execute("SELECT event_id, market, side, line, odds, seen_at FROM soccer_line_history "
                                           "ORDER BY event_id, market, side, seen_at")]


def test_collect_stores_games_and_each_line_once_until_it_moves(tmp_path):
    conn, get = db.connect(tmp_path / "a.db"), Get()
    c = soccer.collect(conn, NOW, get=get)
    assert c["games"] == 2 and len(get.urls) == len(soccer.COMPS) * 9      # yesterday .. a week ahead
    game = dict(conn.execute("SELECT * FROM soccer_games WHERE event_id = '401879227'").fetchone())
    assert (game["comp"], game["home_abbr"], game["away_abbr"], game["state"]) == ("eng.1", "LEE", "COV", "scheduled")
    assert len(_history(conn)) == 14                                    # 1X2 3 + spread 2 + total 2, two games
    later = "2026-11-25T19:45:00.000Z"
    soccer.collect(conn, later, get=Get())
    assert len(_history(conn)) == 14                                    # nothing moved: nothing added
    moved = copy.deepcopy(EPL)
    moved["events"][0]["competitions"][0]["odds"][0]["moneyline"]["home"]["close"]["odds"] = "-230"
    soccer.collect(conn, "2026-11-25T22:00:00.000Z", get=Get(moved))     # 2 h after the last week-ahead poll
    rows = [r for r in _history(conn) if r[0] == "401879227" and r[1] == "ml" and r[2] == "home"]
    assert [(r[4], r[5]) for r in rows] == [(-210, NOW), (-230, "2026-11-25T22:00:00.000Z")]
    assert len(_history(conn)) == 15                                    # only that price moved


def test_days_three_to_seven_are_polled_every_two_hours_only(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    soccer.collect(conn, NOW, get=Get())
    near = Get()
    soccer.collect(conn, "2026-11-25T18:00:00.000Z", get=near)
    assert len(near.urls) == len(soccer.COMPS) * 4                      # yesterday .. two days ahead
    assert not any("dates=20261128" in u for u in near.urls)
    far = Get()
    soccer.collect(conn, "2026-11-25T19:30:00.000Z", get=far)
    assert any("dates=20261128" in u for u in far.urls)


def test_implied_probability_without_the_margin():
    p = soccer.no_vig({"home": -165, "draw": 300, "away": 400})
    assert p["home"] == pytest.approx(0.5805, abs=1e-3) and sum(p.values()) == pytest.approx(1)


def test_board_ranks_upcoming_games_by_market_move_with_history(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    soccer.collect(conn, NOW, get=Get())
    moved = copy.deepcopy(EPL)
    moved["events"][0]["competitions"][0]["odds"][0]["moneyline"]["home"]["close"]["odds"] = "-230"
    soccer.collect(conn, "2026-11-25T21:00:00.000Z", get=Get(moved))
    board = soccer.board_table(conn, "2026-11-25T21:05:00.000Z").set_index("event_id")
    lee, man = board.loc["401879227"], board.loc["401879226"]
    assert (lee["signal_rank"], man["signal_rank"]) == (1, 2)
    assert lee["comp_name"] == "Premier League" and lee["et_date"] == "2026-11-28"
    top = lee["signals"][0]
    assert top["market"] == "ml" and top["side"] == "home" and top["label"] == "LEE"
    assert top["delta"] == pytest.approx(6.1, abs=0.1)                  # 58.1% open -> 64.2% at -230
    assert any(s["market"] == "total" and s["label"] == "Over" and s["delta"] > 5 for s in lee["signals"])
    assert any(s["market"] == "spread" and s["text"] == "LEE −0,5→−1,5" for s in lee["signals"])
    assert lee["tone"] == "strong" and man["tone"] == "weak"
    hist = lee["history"]["ml"]["home"]
    assert hist == [["open", -165], [NOW, -210], ["2026-11-25T21:00:00.000Z", -230]]
    assert lee["now"]["ml"] == {"home": -230, "draw": 350, "away": 500}
    assert lee["moves"]["ml"]["home"] == pytest.approx(6.1, abs=0.1) and lee["moves"]["ml"]["away"] < 0
    assert lee["moves"]["total"]["over"] == pytest.approx(5.6, abs=0.1)
    assert lee["now"]["total"] == {"line": 2.5, "over": -160, "under": 125}
    assert soccer.board_table(conn, "2026-11-28T15:30:00.000Z").empty   # kicked off: off the board


def test_a_total_moved_to_another_line_is_compared_at_the_same_line():
    # DraftKings moved the main total 3,5 -> 2,5: compare the over at 2,5 implied by the 3,5 prices (Poisson goals)
    game = {"home_abbr": "SLP", "away_abbr": "VIL"}
    opened = {"total": {"over": [3.5, 150], "under": [3.5, -190]}}
    same = {"total": {"over": [2.5, -150], "under": [2.5, 120]}}
    sigs = soccer._signals(game, opened, same)
    total = next(s for s in sigs if s["market"] == "total" and s["delta"] is not None)
    assert total["delta"] < 6                                   # not 22 points for a one-goal step
    assert any(s["text"] == "Total 3,5→2,5" and s["delta"] is None for s in sigs)
    assert soccer.goals(2.5, soccer.no_vig({"o": -160, "u": 125})["o"]) == pytest.approx(2.9, abs=0.15)


# --- 1H lines captured before kickoff (after it ESPN's pregame half props turn to leftovers) ---------------------
PROPS = json.loads((FX / "espn_soccer_props_pregame.json").read_text("utf-8"))      # VIL @ SLP: home 494, away 102


def test_half_lines_read_the_1h_moneyline_and_the_main_1h_total():
    h = soccer.half_lines(PROPS, "494", "102")
    assert h == {"first_ml": {"home": 215, "away": 180, "draw": 130}, "first_total": {"line": 1.5, "over": 127, "under": -166}}
    # 25/11 13:35 ET, after kickoff: two leftover items on different lines -> no total
    leftovers = {"items": [
        {"type": {"name": "1st Half Total"}, "current": {"over": {"american": "+1020"}, "target": {"value": 3.5}}},
        {"type": {"name": "1st Half Total"}, "current": {"over": {"american": "+256"}, "target": {"value": 0.5}}}]}
    assert soccer.half_lines(leftovers, "494", "102")["first_total"] is None


class CoreGet(Get):
    """ESPN scoreboard (the fixture), then the DraftKings odds list and its props for each game."""
    def __call__(self, url, **kw):
        if "sports.core.api.espn.com" not in url:
            return super().__call__(url, **kw)
        self.urls.append(url)
        body = PROPS if "propBets" in url else {"items": [
            {"provider": {"name": "DraftKings"}, "propBets": {"$ref": url.split("?")[0] + "/propBets?lang=en"}}]}

        class R:
            status_code = 200

            def json(self):
                return copy.deepcopy(body)
        return R()


def test_1h_lines_are_captured_before_kickoff_at_most_hourly_and_published(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    early = "2026-11-28T05:00:00.000Z"                    # Sat 00:00 ET: both 10:00 ET games are 10 h away
    get = CoreGet()
    soccer.collect(conn, early, get=get)
    core = [u for u in get.urls if "sports.core" in u]
    assert len(core) == 4                                  # odds list + props, two games
    again = CoreGet()
    soccer.collect(conn, "2026-11-28T05:30:00.000Z", get=again)
    assert not [u for u in again.urls if "sports.core" in u]          # captured 30 min ago: not again
    later = CoreGet()
    soccer.collect(conn, "2026-11-28T06:15:00.000Z", get=later)
    assert len([u for u in later.urls if "sports.core" in u]) == 4    # an hour on: refreshed
    table = soccer.half_lines_table(conn, "2026-11-28T15:50:00.000Z").set_index("event_id")   # in play now
    assert table.loc["401879227", "first_total"] == {"line": 1.5, "over": 127, "under": -166}
    assert table.loc["401879227", "captured_at"] == "2026-11-28T06:15:00.000Z"


def test_no_1h_capture_for_games_more_than_twelve_hours_away(tmp_path):
    conn, get = db.connect(tmp_path / "a.db"), CoreGet()
    soccer.collect(conn, "2026-11-27T20:00:00.000Z", get=get)          # 19 h before kickoff
    assert not [u for u in get.urls if "sports.core" in u]
