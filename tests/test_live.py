"""Live scores from ESPN's public scoreboard: parsed, matched to our games, shown until the final arrives."""

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
    assert ev[0] == {"event_id": "1", "commence_time": "2026-11-14T23:15Z", "home_name": "Kentucky Wildcats",
                     "away_name": "Florida Gators", "home_score": 14, "away_score": 10, "state": "in",
                     "detail": "6:09 - 2nd"}


def test_collect_live_only_games_in_progress_and_scores_table(tmp_path):
    c = _db(tmp_path)
    urls = []
    n = live.collect_live(c, "ncaaf", NOW, get=lambda url, **k: urls.append(url) or _R())
    assert n == 1 and len(urls) == 1 and "dates=20261114" in urls[0]       # only the game that has kicked off
    s = live.scores_table(c, NOW).set_index("game_id")
    assert (s.loc[1, "away_score"], s.loc[1, "home_score"], s.loc[1, "state"], s.loc[1, "detail"]) == (10, 14, "live", "6:09 - 2nd")
    assert (s.loc[3, "away_score"], s.loc[3, "state"]) == (49, "final")    # the Odds API final wins
    assert 2 not in s.index


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
