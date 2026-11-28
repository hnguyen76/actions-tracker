import json

from actions_tracker import db
from actions_tracker.wagerhub_feed import apply_scores, load_events


def _write(root, updated, records):
    path = root / "data/private"
    path.mkdir(parents=True)
    (path / "wagerhub_live.json").write_text(json.dumps({"updated_at": updated, "records": records}), "utf-8")


def test_only_fresh_at_matchups_are_loaded(tmp_path):
    _write(tmp_path, "2026-11-28T00:00:00Z", [
        {"Match": "LA Lakers @ Boston Celtics", "Score": "53-62", "Status": "3rd 8:21"},
        {"Match": "Denver vs Miami", "Score": "7-3"},
    ])
    rows = load_events(tmp_path, "2026-11-28T00:05:00Z")
    assert len(rows) == 1 and rows[0]["away_score"] == 53 and rows[0]["home_score"] == 62
    assert load_events(tmp_path, "2026-11-28T00:09:00Z") == []


def test_exact_wagerhub_score_overrides_espn_and_records_source(tmp_path):
    conn = db.connect(tmp_path / "data/actions.db")
    db.upsert_games(conn, [{"id": 1, "league": "nba", "start_time": "2026-11-28T00:00:00Z",
                            "away_name": "LA Lakers", "home_name": "Boston Celtics",
                            "away_abbr": "LAL", "home_abbr": "BOS"}], "2026-11-28T00:00:00Z")
    conn.execute("CREATE TABLE live_scores(game_id INTEGER PRIMARY KEY, away_score INTEGER, home_score INTEGER, "
                 "state TEXT, detail TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO live_scores VALUES (1, 50, 60, 'in', 'ESPN', '2026-11-28T00:04:00Z')")
    conn.commit()
    _write(tmp_path, "2026-11-28T00:05:00Z", [
        {"Match": "LA Lakers @ Boston Celtics", "Score": "53-62", "Status": "3rd 8:21"}])
    result = apply_scores(conn, tmp_path, "2026-11-28T00:06:00Z")
    row = conn.execute("SELECT away_score,home_score,source FROM live_scores WHERE game_id=1").fetchone()
    assert result["matched"] == 1
    assert tuple(row) == (53, 62, "WagerHub")


def test_ambiguous_or_reversed_match_never_overwrites(tmp_path):
    conn = db.connect(tmp_path / "data/actions.db")
    db.upsert_games(conn, [{"id": 1, "league": "nba", "away_name": "LA Lakers", "home_name": "Boston Celtics"}],
                    "2026-11-28T00:00:00Z")
    _write(tmp_path, "2026-11-28T00:05:00Z", [
        {"Match": "Boston Celtics @ LA Lakers", "Score": "62-53", "Status": "3rd"}])
    assert apply_scores(conn, tmp_path, "2026-11-28T00:06:00Z")["matched"] == 0
