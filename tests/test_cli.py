import json
import sqlite3
from pathlib import Path

from actions_tracker import db
from actions_tracker.cli import main, run
from actions_tracker.fetch import FetchError
from actions_tracker.odds_api import OddsApiError

FX = Path(__file__).parent / "fixtures"
NBA_PICKS = (FX / "nba_picks.html").read_text("utf-8")
NBA_ODDS = json.loads((FX / "odds_nba_odds.json").read_text("utf-8"))
NOW = "2026-11-09T22:00:00.000Z"


def _args(tmp_path, fx=FX, leagues="nfl,ncaaf,nba"):
    return ["run", "--offline", str(fx), "--leagues", leagues, "--db", str(tmp_path / "a.db"),
            "--report", str(tmp_path / "r.xlsx"), "--site", str(tmp_path / "site")]


class FakeFetcher:
    def __init__(self, routes):
        self.routes = routes

    def get_text(self, url):
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise FetchError(f"no route for {url}")


class FakeOddsApi:
    def __init__(self, odds=None, scores=None, remaining=400):
        self._odds, self._scores, self.remaining, self.calls = odds or {}, scores or {}, remaining, []

    def _get(self, store, league, kind):
        self.calls.append((kind, league))
        value = store.get(league, [])
        if isinstance(value, Exception):
            raise value
        return value

    def odds(self, league):
        return self._get(self._odds, league, "odds")

    def scores(self, league):
        return self._get(self._scores, league, "scores")


def _run(tmp_path, fetcher, leagues, api):
    return run(tmp_path / "a.db", tmp_path / "r.xlsx", tmp_path / "site", leagues, fetcher, NOW, api)


def _seed_past_pick(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [{"id": 777, "league": "nba", "start_time": "2026-11-09T00:30:00.000Z",
                         "home_name": "Boston Celtics", "away_name": "New York Knicks", "home_abbr": "BOS",
                         "away_abbr": "NYK"}], "t")
    db.upsert_picks(c, [{"id": 1, "expert_id": 9, "game_id": 777, "league": "nba", "market": "ml",
                         "pick_side": "home", "odds": -150, "created_at": "2026-11-08T12:00:00.000Z"}], "t")
    return c


PAST_SCORE = [{"id": "ev777", "commence_time": "2026-11-09T00:40:00Z", "completed": True,
               "home_team": "Boston Celtics", "away_team": "New York Knicks",
               "scores": [{"name": "Boston Celtics", "score": "110"}, {"name": "New York Knicks", "score": "99"}]}]


def test_offline_end_to_end(tmp_path):
    args = _args(tmp_path)
    assert main(args) == 0
    assert (tmp_path / "r.xlsx").exists() and (tmp_path / "site" / "index.html").exists()
    c = sqlite3.connect(tmp_path / "a.db")
    n1 = c.execute("select count(*) from picks").fetchone()[0]
    assert n1 > 0
    assert c.execute("select count(*) from closing_lines").fetchone()[0] > 0
    assert main(args) == 0
    assert c.execute("select count(*) from picks").fetchone()[0] == n1
    assert c.execute("select count(*) from league_status where last_success_at is not null").fetchone()[0] == 3


def test_lines_for_upcoming_and_scores_for_past(tmp_path):
    c = _seed_past_pick(tmp_path)
    api = FakeOddsApi(odds={"nba": NBA_ODDS}, scores={"nba": PAST_SCORE})
    assert _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], api) == 0
    assert tuple(c.execute("select status, home_score, away_score, odds_event_id from games where id=777").fetchone()) \
        == ("complete", 110, 99, "ev777")
    upcoming_with_lines = c.execute("select count(distinct game_id) from closing_lines").fetchone()[0]
    assert upcoming_with_lines > 0
    assert ("odds", "nba") in api.calls and ("scores", "nba") in api.calls


def test_no_calls_when_nothing_needed(tmp_path):
    api = FakeOddsApi()
    empty = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"initialExpertsResponse":{"response":{"profiles":[]}}}}}</script>'
    assert _run(tmp_path, FakeFetcher({"mlb/picks": empty}), ["mlb"], api) == 0
    assert api.calls == []


def test_low_credits_skip_odds_but_keep_scores(tmp_path):
    _seed_past_pick(tmp_path)
    api = FakeOddsApi(odds={"nba": NBA_ODDS}, scores={"nba": PAST_SCORE}, remaining=10)
    _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], api)
    assert ("odds", "nba") not in api.calls and ("scores", "nba") in api.calls


def test_odds_api_error_keeps_picks(tmp_path):
    api = FakeOddsApi(odds={"nba": OddsApiError("HTTP 401")})
    assert _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], api) == 1
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks").fetchone()[0] > 0
    assert "401" in c.execute("select last_error from league_status where league='nba'").fetchone()[0]


def test_no_key_exit_5_keeps_picks(tmp_path):
    assert _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], None) == 5
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks").fetchone()[0] > 0


def test_parse_error_exit_2_and_others_continue(tmp_path):
    f = FakeFetcher({"nfl/picks": "<html>changed</html>", "nba/picks": NBA_PICKS})
    assert _run(tmp_path, f, ["nfl", "nba"], FakeOddsApi(odds={"nba": NBA_ODDS})) == 2
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks where league='nba'").fetchone()[0] > 0
    assert "__NEXT_DATA__" in c.execute("select last_error from league_status where league='nfl'").fetchone()[0]
    assert (tmp_path / "site" / "index.html").exists()


def test_unexpected_error_exit_3(tmp_path):
    f = FakeFetcher({"nfl/picks": RuntimeError("boom"), "nba/picks": NBA_PICKS})
    assert _run(tmp_path, f, ["nfl", "nba"], FakeOddsApi(odds={"nba": NBA_ODDS})) == 3
    c = sqlite3.connect(tmp_path / "a.db")
    assert "boom" in c.execute("select last_error from league_status where league='nfl'").fetchone()[0]


def test_all_leagues_fail_exit_1(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert main(_args(tmp_path, fx=d, leagues="nfl,nba")) == 1


def test_locked_excel_still_builds_site(tmp_path, monkeypatch):
    import actions_tracker.cli as cli_mod
    monkeypatch.setattr(cli_mod, "write_report", lambda tables, path: False)
    assert _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], FakeOddsApi(odds={"nba": NBA_ODDS})) == 4
    assert (tmp_path / "site" / "index.html").exists()


def test_dashboard_gets_ungraded_count_and_credits(tmp_path):
    _seed_past_pick(tmp_path)
    api = FakeOddsApi(odds={"nba": NBA_ODDS}, scores={"nba": []}, remaining=321)
    _run(tmp_path, FakeFetcher({"nba/picks": NBA_PICKS}), ["nba"], api)
    html = (tmp_path / "site" / "index.html").read_text("utf-8")
    assert '"ungraded_past_games":1' in html and '"odds_api_remaining":321' in html
