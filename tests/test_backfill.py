from actions_tracker import db
from actions_tracker.backfill import backfill_queries

NOW = "2026-11-09T22:00:00.000Z"


def _game(gid, league, start, status="scheduled", week=None):
    return dict(id=gid, league=league, season=2026, week=week, start_time=start, status=status,
                home_team_id=1, away_team_id=2, home_abbr="H", away_abbr="A", home_score=None, away_score=None)


def test_daily_league_queries_by_eastern_date(tmp_path):
    c = db.connect(tmp_path / "b.db")
    db.upsert_games(c, [
        _game(1, "nba", "2026-11-09T00:30:00.000Z"),             # Sun 19:30 ET -> 20261108
        _game(2, "nba", "2026-11-09T03:00:00.000Z"),             # Sun 22:00 ET -> same date
        _game(3, "nba", "2026-11-08T01:00:00.000Z"),             # Fri 20:00 ET -> 20261107
        _game(4, "nba", "2026-11-09T21:00:00.000Z"),             # started <4h ago -> skip
        _game(5, "nba", "2026-11-07T00:00:00.000Z", "complete"),  # already graded
        _game(6, "nba", "2026-11-07T00:00:00.000Z", "postponed"),
        _game(7, "nba", "2026-10-20T00:00:00.000Z"),             # older than 10 days -> skip
    ], "t")
    assert backfill_queries(c, "nba", NOW) == ["date=20261107", "date=20261108"]


def test_weekly_league_queries_by_week(tmp_path):
    c = db.connect(tmp_path / "b.db")
    db.upsert_games(c, [_game(1, "ncaaf", "2026-11-07T17:00:00.000Z", week=10),
                        _game(2, "ncaaf", "2026-11-08T01:00:00.000Z", week=10),
                        _game(3, "ncaaf", "2026-11-01T01:00:00.000Z", week=9),
                        _game(4, "ncaaf", "2026-11-08T01:00:00.000Z", week=None)], "t")
    assert backfill_queries(c, "ncaaf", NOW) == ["week=9", "week=10"]


def test_query_cap(tmp_path):
    c = db.connect(tmp_path / "b.db")
    db.upsert_games(c, [_game(i, "nba", f"2026-11-0{i}T12:00:00.000Z") for i in range(1, 9)], "t")
    assert len(backfill_queries(c, "nba", NOW)) == 5
