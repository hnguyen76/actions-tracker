import sqlite3
from pathlib import Path

from actions_tracker.cli import main

FX = str(Path(__file__).parent / "fixtures")


def _args(tmp_path, fx=FX, leagues="nfl,ncaaf,nba"):
    return ["run", "--offline", fx, "--leagues", leagues, "--db", str(tmp_path / "a.db"),
            "--report", str(tmp_path / "r.xlsx"), "--site", str(tmp_path / "site")]


def test_offline_end_to_end(tmp_path):
    args = _args(tmp_path)
    assert main(args) == 0
    assert (tmp_path / "r.xlsx").exists() and (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / "actions_report.xlsx").exists()
    c = sqlite3.connect(tmp_path / "a.db")
    n1 = c.execute("select count(*) from picks").fetchone()[0]
    assert n1 > 0
    assert main(args) == 0
    assert c.execute("select count(*) from picks").fetchone()[0] == n1
    assert c.execute("select count(*) from league_status where last_success_at is not null").fetchone()[0] == 3


def test_parse_error_exit_2_and_others_continue(tmp_path):
    d = tmp_path / "fx"
    d.mkdir()
    for f in Path(FX).glob("nba_*"):
        (d / f.name).write_bytes(f.read_bytes())
    (d / "nfl_picks.html").write_text("<html>changed</html>")
    (d / "nfl_scoreboard.json").write_text('{"games": []}')
    rc = main(_args(tmp_path, fx=str(d), leagues="nfl,nba"))
    assert rc == 2 and (tmp_path / "site" / "index.html").exists()
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks where league='nba'").fetchone()[0] > 0
    err = c.execute("select last_error from league_status where league='nfl'").fetchone()[0]
    assert "__NEXT_DATA__" in err


def test_all_leagues_fail_exit_1(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert main(_args(tmp_path, fx=str(d), leagues="nfl,nba")) == 1


import json as _json

from actions_tracker import db as _db
from actions_tracker.cli import run
from actions_tracker.fetch import FetchError

NBA_PICKS = (Path(FX) / "nba_picks.html").read_text("utf-8")
NBA_BOARD = _json.loads((Path(FX) / "nba_scoreboard.json").read_text("utf-8"))
NOW = "2026-11-09T22:00:00.000Z"


class FakeFetcher:
    """Answers by URL substring; a value that is an Exception is raised."""

    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def _get(self, url):
        self.urls.append(url)
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise FetchError(f"no route for {url}")

    def get_text(self, url):
        return self._get(url)

    def get_json(self, url):
        return self._get(url)


def _run(tmp_path, fetcher, leagues):
    return run(tmp_path / "a.db", tmp_path / "r.xlsx", tmp_path / "site", leagues, fetcher, NOW)


def test_backfill_fetches_past_scores(tmp_path):
    c = _db.connect(tmp_path / "a.db")
    c.execute("INSERT INTO games(id, league, start_time, status) VALUES (777, 'nba', '2026-11-09T00:30:00.000Z', 'scheduled')")
    c.commit()
    past = {"games": [{"id": 777, "status": "complete", "start_time": "2026-11-09T00:30:00.000Z",
                       "home_team_id": 1, "away_team_id": 2, "teams": [],
                       "boxscore": {"total_home_points": 110, "total_away_points": 99}}]}
    f = FakeFetcher({"date=20261108": past, "nba/picks": NBA_PICKS, "scoreboard/nba": NBA_BOARD})
    assert _run(tmp_path, f, ["nba"]) == 0
    row = c.execute("SELECT status, home_score FROM games WHERE id = 777").fetchone()
    assert tuple(row) == ("complete", 110)
    assert any("date=20261108" in u for u in f.urls)


def test_unexpected_error_in_one_league_does_not_stop_others(tmp_path):
    f = FakeFetcher({"nfl/picks": RuntimeError("boom"), "nba/picks": NBA_PICKS, "scoreboard/nba": NBA_BOARD})
    assert _run(tmp_path, f, ["nfl", "nba"]) == 3
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks where league='nba'").fetchone()[0] > 0
    assert "boom" in c.execute("select last_error from league_status where league='nfl'").fetchone()[0]
    assert (tmp_path / "site" / "index.html").exists()


def test_scoreboard_failure_keeps_picks(tmp_path):
    f = FakeFetcher({"nba/picks": NBA_PICKS, "scoreboard/nba": FetchError("api down")})
    assert _run(tmp_path, f, ["nba"]) == 1
    c = sqlite3.connect(tmp_path / "a.db")
    assert c.execute("select count(*) from picks where league='nba'").fetchone()[0] > 0
    assert "api down" in c.execute("select last_error from league_status where league='nba'").fetchone()[0]


def test_locked_excel_still_builds_site(tmp_path, monkeypatch):
    import actions_tracker.cli as cli_mod
    monkeypatch.setattr(cli_mod, "write_report", lambda tables, path: False)
    f = FakeFetcher({"nba/picks": NBA_PICKS, "scoreboard/nba": NBA_BOARD})
    assert _run(tmp_path, f, ["nba"]) == 4
    assert (tmp_path / "site" / "index.html").exists()


def test_status_reports_ungraded_past_games(tmp_path):
    c = _db.connect(tmp_path / "a.db")
    c.execute("INSERT INTO games(id, league, start_time, status) VALUES (778, 'nba', '2026-11-09T00:30:00.000Z', 'scheduled')")
    c.execute("INSERT INTO picks(id, expert_id, game_id, league, market, pick_side) VALUES (1, 1, 778, 'nba', 'ml', 'home')")
    c.commit()
    f = FakeFetcher({"nba/picks": NBA_PICKS, "scoreboard/nba": NBA_BOARD})  # backfill query gets no route -> stays stale
    _run(tmp_path, f, ["nba"])
    html = (tmp_path / "site" / "index.html").read_text("utf-8")
    assert '"ungraded_past_games":1' in html
