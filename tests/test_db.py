from actions_tracker import db

G = dict(id=100, league="nfl", season=2026, week=9, start_time="2026-11-10T01:00:00.000Z", status="scheduled",
         home_team_id=10, away_team_id=20, home_abbr="HOM", away_abbr="AWY", home_score=None, away_score=None)
P = dict(id=11, expert_id=1, game_id=100, league="nfl", market="spread", pick_side="home", line=-3.5, odds=-110,
         units=1, an_result=None, created_at="2026-11-09T10:00:00.000Z", starts_at=G["start_time"], settled_at=None,
         play_text="HOM -3.5")
L = dict(game_id=100, market="spread", side="home", line=-3.5, odds=-110, tickets_pct=60, money_pct=70)


def test_upsert_idempotent_and_coalesce(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [G], "t1")
    db.upsert_picks(c, [P], "t1")
    db.upsert_games(c, [G | {"status": "complete", "home_score": 24, "away_score": 17}], "t2")
    db.upsert_games(c, [G | {"home_abbr": None}], "t3")
    db.upsert_picks(c, [P | {"an_result": "win"}], "t2")
    db.upsert_picks(c, [P], "t3")
    assert c.execute("select count(*) from picks").fetchone()[0] == 1
    g = c.execute("select status, home_score, home_abbr from games").fetchone()
    assert tuple(g) == ("scheduled", 24, "HOM")
    assert c.execute("select an_result from picks").fetchone()[0] == "win"
    db.upsert_games(c, [{"id": 100, "status": "complete"}], "t4")
    assert tuple(c.execute("select status, home_abbr from games").fetchone()) == ("complete", "HOM")


def test_lines_frozen_after_start(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [G], "t")
    db.upsert_lines(c, [L], "2026-11-09T20:00:00.000Z")
    db.upsert_lines(c, [L | {"line": -7.0}], "2026-11-10T02:00:00.000Z")
    db.upsert_lines(c, [L | {"game_id": 999}], "2026-11-09T20:00:00.000Z")
    rows = c.execute("select game_id, line from closing_lines").fetchall()
    assert [tuple(r) for r in rows] == [(100, -3.5)]


def test_experts_first_seen_kept(tmp_path):
    c = db.connect(tmp_path / "a.db")
    e = dict(id=1, name="A", username="a", followers=10)
    db.upsert_experts(c, [e], "t1")
    db.upsert_experts(c, [e | {"followers": 20}], "t2")
    assert tuple(c.execute("select first_seen, last_seen, followers from experts").fetchone()) == ("t1", "t2", 20)


def test_mark_league(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.mark_league(c, "nfl", True, "t1")
    db.mark_league(c, "nfl", False, "t2", "boom")
    row = c.execute("select last_success_at, last_error, last_error_at from league_status").fetchone()
    assert tuple(row) == ("t1", "boom", "t2")
