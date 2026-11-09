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
