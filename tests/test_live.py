"""Live scores from ESPN's public scoreboard: parsed, matched to our games, shown until the final arrives."""

import pandas as pd

from actions_tracker import db, live

NOW = "2026-11-14T23:50:00.000Z"
BOARD = {"events": [
    {"id": "1", "date": "2026-11-14T23:15Z", "status": {"type": {"state": "in", "shortDetail": "6:09 - 2nd"}},
     "competitions": [{"competitors": [
         {"homeAway": "home", "team": {"displayName": "Kentucky Wildcats"}, "score": "14"},
         {"homeAway": "away", "team": {"displayName": "Florida Gators"}, "score": "10"}]}]},
    {"id": "2", "date": "2026-11-15T00:30Z", "status": {"type": {"state": "pre", "shortDetail": "7:30 PM"}},
     "competitions": [{"competitors": [
         {"homeAway": "home", "team": {"displayName": "LSU Tigers"}, "score": "0"},
         {"homeAway": "away", "team": {"displayName": "Texas Longhorns"}, "score": "0"}]}]},
]}


class _R:
    status_code = 200

    def json(self):
        return BOARD


def _db(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [dict(id=1, league="ncaaf", start_time="2026-11-14T23:15:00.000Z", home_abbr="UK",
                             away_abbr="FLA", home_name="Kentucky Wildcats", away_name="Florida Gators"),
                        dict(id=2, league="ncaaf", start_time="2026-11-15T00:30:00.000Z", home_abbr="LSU",
                             away_abbr="TEX", home_name="LSU Tigers", away_name="Texas Longhorns"),
                        dict(id=3, league="ncaaf", start_time="2026-11-14T17:00:00.000Z", home_abbr="SMU",
                             away_abbr="WF", status="complete", home_score=7, away_score=49)], "t")
    db.upsert_picks(c, [dict(id=10 + g, expert_id=1, game_id=g, league="ncaaf", market="spread", pick_side="home",
                             created_at="2026-11-14T10:00:00.000Z") for g in (1, 2, 3)], "t")
    return c


def test_parse_scoreboard():
    ev = live.parse_scoreboard(BOARD)
    assert ev[0].pop("lines") == []
    assert ev[0].pop("venue")["venue"] is None      # this test board carries no venue
    assert ev[0].pop("open") == []
    assert ev[0] == {"event_id": "1", "commence_time": "2026-11-14T23:15Z", "home_name": "Kentucky Wildcats",
                     "away_name": "Florida Gators", "home_score": 14, "away_score": 10, "state": "in",
                     "detail": "6:09 - 2nd", "is_halftime": False, "situation": None}


def test_collect_live_only_games_in_progress_and_scores_table(tmp_path):
    c = _db(tmp_path)
    urls = []
    n = live.collect_live(c, "ncaaf", NOW, get=lambda url, **k: urls.append(url) or _R())
    assert n == 1 and len([u for u in urls if "scoreboard" in u]) == 1 and "dates=20261114" in urls[0]       # only the game that has kicked off
    s = live.scores_table(c, NOW).set_index("game_id")
    assert (s.loc[1, "away_score"], s.loc[1, "home_score"], s.loc[1, "state"], s.loc[1, "detail"]) == (10, 14, "live", "6:09 - 2nd")
    assert (s.loc[3, "away_score"], s.loc[3, "state"]) == (49, "final")    # the Odds API final wins
    assert 2 not in s.index
    assert s.loc[1, "updated_at"] == NOW and pd.isna(s.loc[3, "updated_at"])


def test_no_request_when_nothing_is_being_played(tmp_path):
    c = _db(tmp_path)
    called = []
    assert live.collect_live(c, "nfl", NOW, get=lambda url, **k: called.append(url)) == 0 and called == []



def test_espn_final_grades_the_game(tmp_path):
    c = _db(tmp_path)
    final = {"events": [dict(BOARD["events"][0], status={"type": {"state": "post", "shortDetail": "Final"}})]}

    class R:
        status_code = 200

        def json(self):
            return final
    live.collect_live(c, "ncaaf", NOW, get=lambda url, **k: R())
    g = dict(c.execute("SELECT status, away_score, home_score FROM games WHERE id = 1").fetchone())
    assert g == {"status": "complete", "away_score": 10, "home_score": 14}


def test_old_picked_game_left_ungraded_is_graded_late(tmp_path):
    # JAC@BAL 05/11 was never graded: the 72-hour score window had passed before ESPN grading existed
    c = _db(tmp_path)
    db.upsert_games(c, [dict(id=4, league="ncaaf", start_time="2026-10-28T23:15:00.000Z", home_abbr="BAL",
                             away_abbr="JAC", home_name="Baltimore Ravens", away_name="Jacksonville Jaguars"),
                        dict(id=5, league="ncaaf", start_time="2026-10-01T23:15:00.000Z", home_abbr="OLD",
                             away_abbr="GONE", home_name="Old Team", away_name="Gone Team")], "t")
    db.upsert_picks(c, [dict(id=10 + g, expert_id=1, game_id=g, league="ncaaf", market="spread", pick_side="away",
                             created_at="2026-10-01T10:00:00.000Z") for g in (4, 5)], "t")
    old = {"events": [{"id": "9", "date": "2026-10-28T23:15Z", "status": {"type": {"state": "post", "shortDetail": "Final"}},
                       "competitions": [{"competitors": [
                           {"homeAway": "home", "team": {"displayName": "Baltimore Ravens"}, "score": "10"},
                           {"homeAway": "away", "team": {"displayName": "Jacksonville Jaguars"}, "score": "33"}]}]}]}
    urls = []

    class R:
        status_code = 200

        def __init__(self, url):
            self.url = url

        def json(self):
            return old if "dates=20261028" in self.url else BOARD
    live.collect_live(c, "ncaaf", NOW, get=lambda url, **k: urls.append(url) or R(url))
    g = dict(c.execute("SELECT status, away_score, home_score FROM games WHERE id = 4").fetchone())
    assert g == {"status": "complete", "away_score": 33, "home_score": 10}
    assert not any("dates=20261001" in u for u in urls)      # beyond the 30-day look-back: not requested
    urls.clear()
    live.collect_live(c, "ncaaf", NOW, get=lambda url, **k: urls.append(url) or R(url))
    assert not any("dates=20261028" in u for u in urls)      # graded now: its date is not fetched again



ODDS = [{"provider": {"name": "DraftKings"}, "spread": -3.0, "overUnder": 49.5,
         "pointSpread": {"home": {"close": {"line": "-3", "odds": "-102"}}, "away": {"close": {"line": "+3", "odds": "-118"}}},
         "total": {"over": {"close": {"line": "o49.5", "odds": "-112"}}, "under": {"close": {"line": "u49.5", "odds": "-108"}}},
         "moneyline": {"home": {"close": {"odds": "-155"}}, "away": {"close": {"odds": "+130"}}}}]


def test_parse_odds_draftkings():
    got = {(x["market"], x["side"]): (x["line"], x["odds"]) for x in live.parse_odds(ODDS)}
    assert got == {("spread", "home"): (-3.0, -102), ("spread", "away"): (3.0, -118), ("total", "over"): (49.5, -112),
                   ("total", "under"): (49.5, -108), ("ml", "home"): (None, -155), ("ml", "away"): (None, 130)}
    # only the summary fields -> spread from the home number, total from overUnder
    got = {(x["market"], x["side"]): x["line"] for x in live.parse_odds([{"spread": 2.5, "overUnder": 75.5}])}
    assert got == {("spread", "home"): 2.5, ("spread", "away"): -2.5, ("total", "over"): 75.5, ("total", "under"): 75.5}


def test_lines_stored_before_kickoff_only(tmp_path):
    c = _db(tmp_path)
    board = {"events": [dict(BOARD["events"][1], competitions=[dict(BOARD["events"][1]["competitions"][0], odds=ODDS)])]}

    class R:
        status_code = 200

        def json(self):
            return board
    counts = live.collect_espn(c, "ncaaf", NOW, get=lambda url, **k: R())
    assert counts["lines"] == 1
    rows = {(r["market"], r["side"]): r["line"] for r in c.execute("SELECT * FROM closing_lines WHERE game_id = 2")}
    assert rows[("spread", "home")] == -3.0 and rows[("total", "over")] == 49.5
    # after kickoff the closing line no longer moves
    live.collect_espn(c, "ncaaf", "2026-11-15T01:00:00.000Z", get=lambda url, **k: R())
    assert c.execute("SELECT captured_at FROM closing_lines WHERE game_id = 2 AND market = 'spread' AND side = 'home'"
                     ).fetchone()[0] == NOW



def test_live_command_updates_scores_without_lines_and_rebuilds_site(tmp_path):
    from actions_tracker.cli import live_scores
    _db(tmp_path).close()
    urls = []
    assert live_scores(tmp_path / "a.db", tmp_path / "site", ["ncaaf", "nfl"], NOW,
                       get=lambda url, **k: urls.append(url) or _R()) == 0
    assert len(urls) == 1 and (tmp_path / "site" / "index.html").exists()    # only the league with a game on
    c = db.connect(tmp_path / "a.db")
    assert c.execute("SELECT count(*) FROM closing_lines").fetchone()[0] == 0  # no lines in the light run
    assert c.execute("SELECT state FROM live_scores WHERE game_id = 1").fetchone()[0] == "in"


def test_live_command_refreshes_playoff_cache_and_builds_even_without_a_live_game(tmp_path, monkeypatch):
    from actions_tracker.cli import live_scores
    from actions_tracker import playoffs
    conn = db.connect(tmp_path / "a.db")
    conn.close()
    monkeypatch.setattr(playoffs, "refresh_playoff_picture", lambda conn, now, get: 170)
    assert live_scores(tmp_path / "a.db", tmp_path / "site", ["nfl"], NOW,
                       playoff_get=lambda *a, **k: None) == 0
    assert (tmp_path / "site" / "index.html").exists()


def test_verified_event_ids_include_upcoming_games_and_survive_reopen(tmp_path):
    c = _db(tmp_path)
    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: _R())
    assert dict(c.execute("SELECT game_id, espn_event_id FROM live_game_ids")) == {1: "1", 2: "2"}
    c.close()
    c = db.connect(tmp_path / "a.db")
    targets = live.live_games_table(c, NOW).set_index("game_id")
    assert targets.loc[2, "espn_event_id"] == "2"  # ready before kickoff, without a live score yet
    assert targets.loc[2, "home_name"] == "LSU Tigers"
    assert 3 not in targets.index


def test_fuzzy_score_match_does_not_become_a_browser_event_id(tmp_path):
    c = _db(tmp_path)
    c.execute("UPDATE games SET away_name='Florida Gator' WHERE id=1")
    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: _R())
    assert c.execute("SELECT 1 FROM live_scores WHERE game_id=1").fetchone()  # existing score matching is unchanged
    assert not c.execute("SELECT 1 FROM live_game_ids WHERE game_id=1").fetchone()
    assert pd.isna(live.live_games_table(c, NOW).set_index("game_id").loc[1, "espn_event_id"])


def test_event_id_accepts_known_name_aliases(tmp_path):
    c = _db(tmp_path)
    c.execute("UPDATE games SET home_name='Miami (FL) Hurricanes' WHERE id=2")
    from copy import deepcopy
    board = deepcopy(BOARD)
    board["events"][1]["competitions"][0]["competitors"][0]["team"]["displayName"] = "Miami Hurricanes"

    class R:
        status_code = 200

        def json(self):
            return board

    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: R())
    assert c.execute("SELECT espn_event_id FROM live_game_ids WHERE game_id=2").fetchone()[0] == "2"


def test_browser_targets_are_bounded_picked_unique_and_read_only(tmp_path):
    c = _db(tmp_path)
    db.upsert_games(c, [
        dict(id=4, league="nfl", start_time="2026-11-11T23:50:00.000Z"),  # exactly 72h ago -> out
        dict(id=5, league="nba", start_time="2026-11-11T23:50:01.000Z"),
        dict(id=6, league="nfl", start_time="2026-11-16T11:50:00.000Z"),  # exactly 36h ahead -> in
        dict(id=7, league="nfl", start_time="2026-11-16T11:50:01.000Z"),
        dict(id=8, league="nfl", start_time=NOW),  # no picks
        dict(id=9, league="mlb", start_time=NOW),
    ], "t")
    db.upsert_picks(c, [dict(id=100 + g, game_id=g) for g in (1, 4, 5, 6, 7, 9)], "t")
    c.close()
    # An existing database can render browser targets without installing a schema or changing data.
    import sqlite3
    c = sqlite3.connect(f"file:{(tmp_path / 'a.db').as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    targets = live.live_games_table(c, NOW)
    assert list(targets.columns) == live.LIVE_GAME_COLS
    assert set(targets.game_id) == {1, 2, 5, 6} and len(targets) == 4
    assert targets.espn_event_id.isna().all()
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='live_game_ids'").fetchone()


def test_mapping_schema_preserves_final_scores_and_existing_lines(tmp_path):
    c = _db(tmp_path)
    db.upsert_lines(c, [dict(game_id=2, market="spread", side="home", line=-7.5, odds=-110)], NOW)
    before = [tuple(r) for r in c.execute("SELECT * FROM closing_lines")]
    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: _R())
    assert [tuple(r) for r in c.execute("SELECT * FROM closing_lines")] == before
    assert tuple(c.execute("SELECT status, away_score, home_score FROM games WHERE id=3").fetchone()) == ("complete", 49, 7)


def _situation_board():
    from copy import deepcopy
    board = deepcopy(BOARD)
    event = board["events"][0]
    event["status"].update(period=2, displayClock="5:47")
    comp = event["competitions"][0]
    comp["situation"] = {"possession": "17", "possessionText": "NE 39", "shortDownDistanceText": "1st & 10",
                         "downDistanceText": "1st & 10 at NE 39", "isRedZone": False, "yardLine": 61}
    comp["competitors"][0]["team"]["id"] = "8"
    comp["competitors"][1]["team"]["id"] = "17"
    comp["competitors"][0]["linescores"] = [{"value": 7, "period": 1}, {"value": 7, "period": 2}]
    comp["competitors"][1]["linescores"] = [{"value": 3, "period": 1}, {"value": 0, "period": 3}]
    return board


def test_situation_uses_explicit_possession_field_position_and_period_scores():
    situation = live.parse_scoreboard(_situation_board())[0]["situation"]
    assert situation == {"possession": "away", "possession_text": "NE 39", "down_distance": "1st & 10",
                         "red_zone": False, "period": 2, "clock": "5:47",
                         "away_period_scores": [3, None, 0], "home_period_scores": [7, 7],
                         "away_espn_id": "17", "home_espn_id": "8"}


def test_situation_does_not_infer_possession_or_fill_unknown_quarters():
    board = _situation_board()
    comp = board["events"][0]["competitions"][0]
    comp["situation"]["possession"] = "unknown"
    comp["situation"]["shortDownDistanceText"] = ""
    comp["competitors"][0]["linescores"] = [{"value": 0}, {"value": "bad", "period": 2}, {"value": -1, "period": 1}]
    s = live.parse_scoreboard(board)[0]["situation"]
    assert s["possession"] is None and s["home_period_scores"] is None
    assert s["down_distance"] == "1st & 10 at NE 39"
    # team ids alone do not imply that a situation is present.
    comp.pop("situation")
    for c in comp["competitors"]:
        c.pop("linescores")
    board["events"][0]["status"] = {"type": {"state": "in"}}
    assert live.parse_scoreboard(board)[0]["situation"] is None


def test_invalid_situation_fields_are_missing_instead_of_guessed():
    event = {"competitions": [{"situation": {"possession": {}, "possessionText": 39,
                                              "shortDownDistanceText": [], "isRedZone": "false"},
                                "competitors": [{"homeAway": "away", "team": {"id": "17"},
                                                 "linescores": [{"value": True, "period": 1},
                                                                {"value": 4, "period": 0},
                                                                {"value": 2, "period": 500}]}]}],
             "status": {"period": 0, "displayClock": ""}}
    assert live.parse_situation(event) is None
    event["status"]["period"] = 500
    assert live.parse_situation(event) is None


def test_situation_persists_exports_and_clears_when_next_snapshot_omits_it(tmp_path):
    import json
    from actions_tracker.build_site import build_site
    c = _db(tmp_path)

    class R:
        status_code = 200

        def json(self):
            return _situation_board()

    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: R())
    scores = live.scores_table(c, NOW)
    situation = scores.set_index("game_id").loc[1, "situation"]
    assert situation["possession"] == "away" and situation["away_period_scores"] == [3, None, 0]
    page = build_site({"Scores": scores}, [], tmp_path / "site", None, NOW).read_text("utf-8")
    data = json.loads(page.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    assert data["tables"]["Scores"][0]["situation"] == situation
    live.collect_espn(c, "ncaaf", NOW, get=lambda *a, **k: _R())
    assert pd.isna(live.scores_table(c, NOW).set_index("game_id").loc[1, "situation"])
    assert c.execute("SELECT details_json FROM live_details WHERE game_id=1").fetchone()[0] == "null"
    c.execute("UPDATE live_details SET details_json='broken json' WHERE game_id=1")
    assert pd.isna(live.scores_table(c, NOW).set_index("game_id").loc[1, "situation"])


def _halftime_board():
    from copy import deepcopy
    board = deepcopy(BOARD)
    event = board["events"][0]
    event["status"] = {"period": 2, "displayClock": "0:00",
                       "type": {"state": "in", "name": "STATUS_HALFTIME", "shortDetail": "Halftime"}}
    comp = event["competitions"][0]
    comp["competitors"][0]["team"]["id"] = "8"
    comp["competitors"][1]["team"]["id"] = "17"
    return board


def test_halftime_score_and_exact_espn_half_lines_are_persisted(tmp_path):
    c = _db(tmp_path)
    props = {
        "pregame-props": {"items": [
            {"type": {"name": "1st Half Spread"}, "team": {"$ref": "https://sports.core.api.espn.com/v2/teams/17"},
             "current": {"target": {"value": 2.5}}},
            {"type": {"name": "1st Half Spread"}, "team": {"$ref": "https://sports.core.api.espn.com/v2/teams/8"},
             "current": {"target": {"value": -2.5}}},
            {"type": {"name": "1st Half Total"}, "current": {"target": {"value": 27.5}}},
        ]},
        "live-props": {"items": [
            {"type": {"name": "2nd Half Spread"}, "team": {"$ref": "https://sports.core.api.espn.com/v2/teams/17"},
             "current": {"target": {"value": 4.5}}},
            {"type": {"name": "2nd Half Spread"}, "team": {"$ref": "https://sports.core.api.espn.com/v2/teams/8"},
             "current": {"target": {"value": -4.5}}},
            {"type": {"name": "2nd Half Total"}, "current": {"target": {"value": 24.5}}},
        ]},
    }
    odds = {"items": [
        {"provider": {"name": "DraftKings"},
         "propBets": {"$ref": "http://sports.core.api.espn.com/pregame-props"}},
        {"provider": {"name": "DraftKings - Live Odds"},
         "propBets": {"$ref": "https://sports.core.api.espn.com/live-props"}},
    ]}

    class R:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    urls = []

    def get(url, **kwargs):
        urls.append(url)
        if "scoreboard" in url:
            return R(_halftime_board())
        if "/odds?" in url:
            return R(odds)
        return R(props["pregame-props" if "pregame-props" in url else "live-props"])

    counts = live.collect_espn(c, "ncaaf", NOW, get=get, lines=False)
    assert counts["halftime_saved"] == 1
    saved = dict(c.execute("SELECT * FROM second_half_snapshots WHERE game_id=1").fetchone())
    assert (saved["away_score_1h"], saved["home_score_1h"]) == (10, 14)
    assert (saved["first_spread_away"], saved["first_spread_home"], saved["first_total"]) == (2.5, -2.5, 27.5)
    assert (saved["second_spread_away"], saved["second_spread_home"], saved["second_total"]) == (4.5, -4.5, 24.5)
    assert any("football/leagues/college-football/events/1/competitions/1/odds" in url for url in urls)
    exported = live.second_half_table(c).set_index("game_id")
    assert exported.loc[1, "league"] == "ncaaf" and exported.loc[1, "away_score_1h"] == 10


def test_halftime_lines_are_locked_at_the_first_sighting_the_telegram_alert_uses(tmp_path):
    # the 2H alert goes out in the run that first sees the line; grading must use that same line
    c = _db(tmp_path)
    spread = lambda team, v: {"type": {"name": "2nd Half Spread"}, "current": {"target": {"value": v}},  # noqa: E731
                              "team": {"$ref": f"https://sports.core.api.espn.com/v2/teams/{team}"}}
    total = lambda v: {"type": {"name": "2nd Half Total"}, "current": {"target": {"value": v}}}  # noqa: E731
    live_items = [spread(17, 4.5), spread(8, -4.5)]                     # first poll: no 2H total yet
    odds = {"items": [{"provider": {"name": "DraftKings - Live Odds"},
                       "propBets": {"$ref": "https://sports.core.api.espn.com/live-props"}}]}

    class R:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    def get(url, **kwargs):
        if "scoreboard" in url:
            return R(_halftime_board())
        return R(odds) if "/odds?" in url else R({"items": live_items})

    live.collect_espn(c, "ncaaf", NOW, get=get, lines=False)
    later = "2026-11-14T23:55:00.000Z"
    live_items[:] = [spread(17, 5.5), spread(8, -5.5), total(24.5)]      # the line moved; the total showed up
    live.collect_espn(c, "ncaaf", later, get=get, lines=False)
    saved = dict(c.execute("SELECT * FROM second_half_snapshots WHERE game_id=1").fetchone())
    assert (saved["second_spread_away"], saved["second_spread_home"]) == (4.5, -4.5)   # kept: the alerted line
    assert saved["second_total"] == 24.5                                                # filled at its first sighting
    assert saved["captured_at"] == later                                                # still at halftime now


def test_halftime_2h_line_history_keeps_each_change_once(tmp_path):
    c = _db(tmp_path)
    spread = lambda team, v: {"type": {"name": "2nd Half Spread"}, "current": {"target": {"value": v}},  # noqa: E731
                              "team": {"$ref": f"https://sports.core.api.espn.com/v2/teams/{team}"}}
    total = lambda v: {"type": {"name": "2nd Half Total"}, "current": {"target": {"value": v}}}  # noqa: E731
    items = []
    odds = {"items": [{"provider": {"name": "DraftKings - Live Odds"},
                       "propBets": {"$ref": "https://sports.core.api.espn.com/live-props"}}]}

    class R:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    def get(url, **kwargs):
        if "scoreboard" in url:
            return R(_halftime_board())
        return R(odds) if "/odds?" in url else R({"items": items})

    for now, lines in (("2026-11-14T23:50:00.000Z", [spread(17, 4.5), spread(8, -4.5), total(24.5)]),
                       ("2026-11-14T23:55:00.000Z", [spread(17, 4.5), spread(8, -4.5), total(24.5)]),   # no move
                       ("2026-11-15T00:00:00.000Z", [spread(17, 5.5), spread(8, -5.5), total(24.5)])):
        items[:] = lines
        live.collect_espn(c, "ncaaf", now, get=get, lines=False)
    history = [tuple(r) for r in c.execute(
        "SELECT market, line, seen_at FROM second_half_line_history WHERE game_id = 1 ORDER BY market, seen_at")]
    assert history == [("spread", 4.5, "2026-11-14T23:50:00.000Z"), ("spread", 5.5, "2026-11-15T00:00:00.000Z"),
                       ("total", 24.5, "2026-11-14T23:50:00.000Z")]      # away 2H spread; a repeat is not stored


def test_half_odds_support_all_three_leagues():
    expected = {"nfl": "football/leagues/nfl", "ncaaf": "football/leagues/college-football",
                "nba": "basketball/leagues/nba"}
    event = {"event_id": "123", "situation": {"away_espn_id": "1", "home_espn_id": "2"}}

    class R:
        status_code = 200

        def json(self):
            return {"items": []}

    for league, path in expected.items():
        urls = []
        live._halftime_odds(lambda url, **kwargs: urls.append(url) or R(), league, event)
        assert len(urls) == 1 and f"/sports/{path}/events/123/" in urls[0]
