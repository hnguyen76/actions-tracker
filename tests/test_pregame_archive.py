import json

import pandas as pd

from actions_tracker import db
from actions_tracker.pregame_archive import capture_snapshots, load_snapshots


def _tables(votes=5):
    return {
        "Upcoming_Board": pd.DataFrame([{
            "game_id": 7, "league": "nfl", "market": "spread", "start_time": "2026-11-15T20:00:00Z",
            "away_abbr": "NE", "home_abbr": "DET", "a_side": "home", "a_votes": votes,
            "b_side": "away", "b_votes": 2, "total_votes": votes + 2,
        }]),
        "Decisions": pd.DataFrame([{"game_id": 7, "market": "spread", "bet_side": "home", "pick": "DET -3"}]),
        "Signals": pd.DataFrame([{"game_id": 7, "market": "spread", "side": "home", "tone": "🟢", "text": "Line tốt"}]),
        "Match_News": pd.DataFrame([{"game_id": 7, "team_abbr": "DET", "sentiment": "positive", "summary": "QB trở lại"}]),
        "Media_ATS": pd.DataFrame([{"game_id": 7, "expert": "A", "pick_team": "DET", "line": -3}]),
        "Media_Picks": pd.DataFrame([{"game_id": 7, "expert": "B", "pick_team": "DET"}]),
        "Weather": pd.DataFrame([{"game_id": 7, "indoor": 1}]),
        "Picks": pd.DataFrame([
            {"game_id": 7, "market": "spread", "expert_name": "A", "play_text": "DET -3",
             "expert_note": "Matchup tốt", "created_at": "2026-11-15T18:00:00Z",
             "start_time": "2026-11-15T20:00:00Z"},
            {"game_id": 7, "market": "spread", "expert_name": "Late", "play_text": "DET -3",
             "expert_note": "Đăng sau kickoff", "created_at": "2026-11-15T20:01:00Z",
             "start_time": "2026-11-15T20:00:00Z"},
        ]),
        "In_Play": pd.DataFrame(),
    }


def test_snapshot_updates_before_kickoff_and_freezes_after(tmp_path):
    conn = db.connect(tmp_path / "archive.db")
    assert capture_snapshots(conn, _tables(5), "2026-11-15T18:00:00Z") == 1
    assert capture_snapshots(conn, _tables(6), "2026-11-15T19:00:00Z") == 1
    saved = load_snapshots(conn).iloc[0]
    snapshot = json.loads(saved.snapshot_json)
    assert snapshot["board"][0]["a_votes"] == 6
    assert [(x["expert_name"], x["expert_note"]) for x in snapshot["comments"]] == [("A", "Matchup tốt")]

    late = _tables(9)
    late["Upcoming_Board"] = pd.DataFrame()
    late["In_Play"] = pd.DataFrame([{
        "game_id": 7, "league": "nfl", "market": "spread", "start_time": "2026-11-15T20:00:00Z",
        "match": "NE@DET", "source": "Cách của bạn",
    }])
    assert capture_snapshots(conn, late, "2026-11-15T20:05:00Z") == 0
    assert json.loads(load_snapshots(conn).iloc[0].snapshot_json)["board"][0]["a_votes"] == 6
    conn.close()


def test_late_live_snapshot_is_inserted_once(tmp_path):
    conn = db.connect(tmp_path / "archive.db")
    tables = _tables()
    tables["Upcoming_Board"] = pd.DataFrame()
    tables["In_Play"] = pd.DataFrame([{
        "game_id": 7, "league": "nfl", "market": "spread", "start_time": "2026-11-15T20:00:00Z",
        "match": "NE@DET", "source": "Cách của bạn",
    }])
    assert capture_snapshots(conn, tables, "2026-11-15T20:05:00Z") == 1
    assert load_snapshots(conn).iloc[0].capture_phase == "late_archive"
    assert capture_snapshots(conn, tables, "2026-11-15T20:06:00Z") == 0
    conn.close()
