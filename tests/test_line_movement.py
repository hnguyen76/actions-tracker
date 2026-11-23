from actions_tracker import db
from actions_tracker.analysis.line_movement import line_movement_tables


NOW = "2026-11-23T12:00:00.000Z"


def _db(tmp_path):
    conn = db.connect(tmp_path / "lines.db")
    db.upsert_games(conn, [dict(id=1, league="nfl", start_time="2026-11-23T18:00:00.000Z",
                                away_abbr="AWY", home_abbr="HOM")], "t")
    db.upsert_picks(conn, [dict(id=1, expert_id=1, game_id=1, league="nfl", market="spread",
                                pick_side="away", created_at="2026-11-23T10:00:00.000Z")], "t")
    for captured, away, home in [
        ("2026-11-23T10:00:00.000Z", 2.5, -2.5),
        ("2026-11-23T10:15:00.000Z", 2.5, -2.5),
        ("2026-11-23T10:30:00.000Z", 1.0, -1.0),
        ("2026-11-23T10:45:00.000Z", -1.5, 1.5),
    ]:
        db.upsert_lines(conn, [dict(game_id=1, market="spread", side="away", line=away, odds=-110),
                               dict(game_id=1, market="spread", side="home", line=home, odds=-110)], captured)
    return conn


def test_line_history_keeps_only_real_changes_and_detects_plus_to_minus(tmp_path):
    movement, flips = line_movement_tables(_db(tmp_path), NOW)
    away = movement.query("side == 'away'")
    assert list(away.line) == [2.5, 1.0, -1.5]
    assert list(away.delta_from_open) == [0, -1.5, -4.0]
    assert len(flips) == 1
    flip = flips.iloc[0]
    assert flip.team == "AWY" and flip.open_line == 2.5 and flip.current_line == -1.5
    assert flip.move == -4 and flip.crossed_at == "2026-11-23T10:45:00.000Z"
    assert flip.et_date == "2026-11-23"


def test_started_games_are_not_in_upcoming_line_movement(tmp_path):
    conn = _db(tmp_path)
    movement, flips = line_movement_tables(conn, "2026-11-23T19:00:00.000Z")
    assert movement.empty and flips.empty
