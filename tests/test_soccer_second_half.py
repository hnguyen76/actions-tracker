"""Soccer 2H plays, like NFL: at halftime the phone locks the first lines it sees (DraftKings "Moneyline - Rest of
Game" and the live full-game total less the 1H goals), decides the owner's 2H plays from the 1H lines captured
before kickoff, and grades them on the 90-minute score at the locked price."""

import copy
import json
from pathlib import Path

import pytest

from actions_tracker import db, soccer

FX = Path(__file__).parent / "fixtures"
ODDS = json.loads((FX / "espn_soccer_odds_live.json").read_text("utf-8"))        # live total 2,5: O -172 / U +144
REST = json.loads((FX / "espn_soccer_props_live_ht.json").read_text("utf-8"))    # SAB (21922) +1100, BAR (83) -450, X +400
KICKOFF = "2026-11-25T17:45:00.000Z"
HT = "2026-11-25T18:35:00.000Z"


def event(status="STATUS_HALFTIME", state="in", home=0, away=1, eid="401915300"):
    return {"id": eid, "date": KICKOFF, "shortName": "BAR @ SAB",
            "status": {"type": {"state": state, "name": status, "shortDetail": "HT"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": str(home), "team": {"id": "21922", "abbreviation": "SAB", "displayName": "Sabadell"}},
                {"homeAway": "away", "score": str(away), "team": {"id": "83", "abbreviation": "BAR", "displayName": "Barcelona"}}],
                "odds": []}]}


class Get:
    """ESPN: the Champions League scoreboard, the DraftKings odds list and the live props."""
    def __init__(self, board, odds=ODDS, props=REST):
        self.board, self.odds, self.props, self.urls = board, odds, props, []

    def __call__(self, url, **kw):
        self.urls.append(url)
        if "propBets" in url:
            body = self.props
        elif "sports.core.api.espn.com" in url:
            body = copy.deepcopy(self.odds)
            for item in body["items"]:
                item["propBets"] = {"$ref": url.split("?")[0] + "/" + item["provider"]["name"].replace(" ", "") + "/propBets"}
        elif "/uefa.champions/" in url and "dates=20261125" in url:
            body = self.board
        else:
            body = {"events": []}

        class R:
            status_code = 200

            def json(self):
                return copy.deepcopy(body)
        return R()


def _setup(tmp_path, first_ml=None, first_total=None):
    conn = db.connect(tmp_path / "a.db")
    for schema in (soccer.GAMES_SCHEMA, soccer.LINES_SCHEMA, soccer.RESULTS_SCHEMA, soccer.HALF_SCHEMA):
        conn.execute(schema)
    pre = soccer.parse_events({"events": [event("STATUS_SCHEDULED", "pre", 0, 0)]}, "uefa.champions")[0]
    soccer._store(conn, pre, "2026-11-25T17:00:00.000Z")                   # the update run saw it before kickoff
    conn.execute("INSERT INTO soccer_half_lines VALUES (?, ?, ?, ?)", (
        "401915300", json.dumps(first_ml or {"home": 300, "away": -120, "draw": 250}),
        json.dumps(first_total or {"line": 1.5, "over": 120, "under": -150}), "2026-11-25T17:00:00.000Z"))
    conn.commit()
    return conn


def test_halftime_locks_the_first_lines_and_decides_the_2h_plays(tmp_path):
    conn = _setup(tmp_path)
    get = Get({"events": [event()]})
    c = soccer.live_poll(conn, HT, get)
    assert c["halftime"] == 1 and c["changed"] >= 1
    plays = soccer.second_half_table(conn)
    side = plays[plays.market == "ml"].iloc[0]
    # BAR the 1H favourite (-120) leads 1-0 at halftime: covered -> the other team in the 2H, at the rest-of-game price
    assert (side.pick, side.pick_side, side.price, side.favourite, side.covered) == ("SAB", "home", 1100, "BAR", True)
    total = plays[plays.market == "total"].iloc[0]
    # 1 goal under the 1H 1,5 -> 2H Over at the live total 2,5 less the goal = 1,5, at the live over price
    assert (total.pick, total.line, total.price, total.first_line, total.first_goals) == ("Over", 1.5, -172, 1.5, 1)
    assert set(plays.result) == {"pending"} and (side.home_1h, side.away_1h) == (0, 1)


def test_later_halftime_sightings_never_move_a_locked_line_but_fill_a_missing_price(tmp_path):
    conn = _setup(tmp_path)
    no_team = {"items": [x for x in REST["items"] if not x.get("team")]}          # team prices off the board
    soccer.live_poll(conn, HT, Get({"events": [event()]}, props=no_team))
    assert soccer.second_half_table(conn).query("market == 'ml'").empty          # no price yet: no side play
    moved = copy.deepcopy(ODDS)
    for item in moved["items"]:
        item.update(overUnder=3.5, overOdds=110.0, underOdds=-140.0)
    soccer.live_poll(conn, "2026-11-25T18:40:00.000Z", Get({"events": [event()]}, odds=moved))
    plays = soccer.second_half_table(conn).set_index("market")
    assert plays.loc["ml", "price"] == 1100                                       # filled at the next sighting
    assert (plays.loc["total", "line"], plays.loc["total", "price"]) == (1.5, -172)   # the first total stays


def test_plays_are_graded_on_the_90_minute_score_at_the_locked_price(tmp_path):
    conn = _setup(tmp_path)
    soccer.live_poll(conn, HT, Get({"events": [event()]}))
    final = event("STATUS_FULL_TIME", "post", home=1, away=4)                    # 2H: SAB 1, BAR 3 -> 4 goals
    c = soccer.live_poll(conn, "2026-11-25T19:40:00.000Z", Get({"events": [final]}))
    assert c["final"] == 1 and c["changed"] >= 1
    plays = soccer.second_half_table(conn).set_index("market")
    assert (plays.loc["ml", "result"], plays.loc["ml", "units"]) == ("loss", -1.0)
    assert plays.loc["total", "result"] == "win" and plays.loc["total", "units"] == pytest.approx(100 / 172, abs=1e-3)
    assert (plays.loc["total", "home_2h"], plays.loc["total", "away_2h"]) == (1, 3)
    summary = soccer.second_half_summary(soccer.second_half_table(conn))
    everything = summary[(summary.scope == "all") & (summary.market == "ALL")].iloc[0]
    assert (everything.wins, everything.losses, everything.pending) == (1, 1, 0)
    assert everything.units == pytest.approx(100 / 172 - 1, abs=1e-3)
    day = summary[(summary.scope == "day") & (summary.market == "ml")].iloc[0]
    assert (day.et_date, day.wins, day.losses) == ("2026-11-25", 0, 1)
    assert soccer.live_poll(conn, "2026-11-25T19:45:00.000Z", Get({"events": [final]}))["polled"] == 0   # final: no more polls


def test_a_level_score_on_a_whole_1h_line_or_a_draw_rest_of_game_follow_the_rules(tmp_path):
    conn = _setup(tmp_path, first_total={"line": 1.0, "over": -110, "under": -110})
    soccer.live_poll(conn, HT, Get({"events": [event()]}))                       # 1 goal on a 1H line of 1: push
    plays = soccer.second_half_table(conn)
    assert list(plays.market) == ["ml"]
    soccer.live_poll(conn, "2026-11-25T19:40:00.000Z", Get({"events": [event("STATUS_FULL_TIME", "post", 1, 2)]}))
    assert soccer.second_half_table(conn).iloc[0].result == "loss"              # 2H 1-1: the 3-way rest of game loses


def test_no_request_when_no_soccer_game_can_be_in_play(tmp_path):
    conn = _setup(tmp_path)
    get = Get({"events": [event()]})
    assert soccer.live_poll(conn, "2026-11-25T12:00:00.000Z", get)["polled"] == 0   # kickoff still 5 h away
    assert soccer.live_poll(conn, "2026-11-25T22:00:00.000Z", get)["polled"] == 0   # over 3 h after kickoff
    assert get.urls == []


def test_the_update_run_also_locks_a_game_it_finds_at_halftime(tmp_path):
    conn = _setup(tmp_path)
    c = soccer.collect(conn, HT, get=Get({"events": [event()]}))
    assert c["second_half"] == 1
    assert len(soccer.second_half_table(conn)) == 2


def test_the_live_command_locks_halftime_and_publishes_the_2h_record(tmp_path):
    from actions_tracker.cli import live_scores
    _setup(tmp_path).close()
    assert live_scores(tmp_path / "a.db", tmp_path / "site", [], HT, soccer_get=Get({"events": [event()]})) == 0
    html = (tmp_path / "site" / "index.html").read_text("utf-8")
    assert '"Soccer_2H_Plays"' in html and '"Soccer_2H_Summary"' in html and '"SAB"' in html
