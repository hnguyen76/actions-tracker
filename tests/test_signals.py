"""Signals for the side being bet: line move, key numbers, rest, QBs, experts, same situation, public money."""

import pandas as pd

from actions_tracker.analysis.signals import SIGNAL_COLS, expert_sides, include_live_decisions, signals
from actions_tracker.game_context import parse_open, parse_summary, starter_injury


def _df(rows, cols):
    return pd.DataFrame(rows, columns=cols)


def test_signals_for_the_side_bet():
    decisions = _df([dict(game_id=1, market="spread", bet_side="home"), dict(game_id=2, market="total", bet_side="under")],
                    ["game_id", "market", "bet_side"])
    games = _df([dict(id=1, league="nfl"), dict(id=2, league="ncaaf")], ["id", "league"])
    current = _df([dict(game_id=1, market="spread", side="home", line=3.5), dict(game_id=2, market="total", side="under", line=48.5)],
                  ["game_id", "market", "side", "line"])
    opening = _df([dict(game_id=1, market="spread", side="home", line=4.5), dict(game_id=2, market="total", side="under", line=50.0)],
                  ["game_id", "market", "side", "line"])
    context = _df([dict(game_id=1, home_rest_days=14.0, away_rest_days=7.0, home_qb=None, away_qb="J. Doe (Out)")],
                  ["game_id", "home_rest_days", "away_rest_days", "home_qb", "away_qb"])
    public = _df([dict(game_id=2, market="total", side="under", tickets_pct=30, money_pct=55)],
                 ["game_id", "market", "side", "tickets_pct", "money_pct"])
    experts = _df([dict(game_id=1, market="spread", side="home", units_30=5), dict(game_id=1, market="spread", side="home", units_30=-4),
                   dict(game_id=1, market="spread", side="away", units_30=1)], ["game_id", "market", "side", "units_30"])
    forecast = _df([dict(game_id=1, p_win=0.57, basis_n=36)], ["game_id", "p_win", "basis_n"])
    s = signals(decisions, games, current, opening, context, public, experts, forecast)
    assert list(s.columns) == SIGNAL_COLS
    one = list(zip(s[s.game_id == 1].tone, s[s.game_id == 1].text))
    assert ("🟢", "Line chạy về phía bạn: mở +4,5 → nay +3,5") in one
    assert ("🟢", "Nhận +3,5: qua được số then chốt 3") in one
    assert ("🟢", "Đội bạn sau tuần nghỉ (14 ngày, đối thủ 7)") in one
    assert ("🟢", "QB chính đối thủ: J. Doe (Out)") in one
    assert any("2 người · 1 đang lời, 1 đang lỗ" in t for _, t in one)
    assert any("57%" in t for _, t in one)
    two = list(zip(s[s.game_id == 2].tone, s[s.game_id == 2].text))
    assert ("🟢", "Line chạy về phía bạn: mở 50 → nay 48,5") in two
    assert ("🟢", "Tiền lớn nghiêng về bạn: vé 30% · tiền 55%") in two


def test_parse_open_and_summary():
    odds = [{"pointSpread": {"home": {"open": {"line": "-1.5", "odds": "-110"}}, "away": {"open": {"line": "+1.5", "odds": "-110"}}},
             "total": {"over": {"open": {"line": "o48.5", "odds": "-110"}}, "under": {"open": {"line": "u48.5"}}}}]
    got = {(x["market"], x["side"]): x["line"] for x in parse_open(odds)}
    assert got == {("spread", "home"): -1.5, ("spread", "away"): 1.5, ("total", "over"): 48.5, ("total", "under"): 48.5}
    summary = {"header": {"competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "6"}},
                                                            {"homeAway": "away", "team": {"id": "25"}}]}]},
               "lastFiveGames": [{"team": {"id": "6"}, "events": [{"gameDate": "2026-11-01T18:00Z"}, {"gameDate": "2026-11-08T18:00Z"}]},
                                 {"team": {"id": "25"}, "events": [{"gameDate": "2026-10-26T18:00Z"}]}],
               "injuries": [{"team": {"id": "25"}, "injuries": [
                   {"athlete": {"displayName": "Brock Purdy", "position": {"abbreviation": "QB"}}, "status": "Questionable"},
                   {"athlete": {"displayName": "Backup", "position": {"abbreviation": "QB"}}, "status": "Injured Reserve"},
                   {"athlete": {"displayName": "Some WR", "position": {"abbreviation": "WR"}}, "status": "Out"}]}]}
    summary["leaders"] = [{"team": {"id": "25"}, "leaders": [{"name": "passingYards",
                                                         "leaders": [{"athlete": {"displayName": "Brock Purdy"}}]}]}]
    c = parse_summary(summary, "2026-11-15T21:25:00Z")
    assert (c["home_rest_days"], c["away_rest_days"]) == (7.1, 20.1)
    assert c["away_qb_injuries"] == [("Brock Purdy", "Questionable")] and c["away_passer"] == "Brock Purdy"
    assert starter_injury(c["away_qb_injuries"], "Brock Purdy") == "Brock Purdy (Questionable)"
    assert starter_injury([("Mac Jones", "Out")], "Brock Purdy") is None          # a backup is ignored


def test_expert_sides_latest_pregame_pick_with_form():
    picks = pd.DataFrame([dict(pick_id=1, expert_id=7, game_id=1, market="spread", pick_side="home",
                               created_at="2026-11-14T10:00Z", start_time="2026-11-15T18:00Z"),
                          dict(pick_id=2, expert_id=7, game_id=1, market="spread", pick_side="away",
                               created_at="2026-11-15T10:00Z", start_time="2026-11-15T18:00Z")])
    forms = pd.DataFrame([dict(pick_id=2, units_30=-5.0)])
    e = expert_sides(picks, forms)
    assert e.to_dict("records") == [dict(game_id=1, market="spread", side="away", units_30=-5.0)]


def test_live_plays_remain_signal_inputs_after_kickoff():
    upcoming = pd.DataFrame([dict(game_id=1, market="spread", bet_side="home")])
    live = pd.DataFrame([
        dict(game_id=2, market="spread", bet_side="away", source="Cách của bạn"),
        dict(game_id=3, market="spread", bet_side="home", source="Quy tắc"),
    ])
    got = include_live_decisions(upcoming, live)
    assert got[["game_id", "market", "bet_side"]].to_dict("records") == [
        dict(game_id=1, market="spread", bet_side="home"),
        dict(game_id=2, market="spread", bet_side="away"),
    ]



def test_store_context_uses_nfl_depth_chart_starter(tmp_path):
    from actions_tracker import db
    from actions_tracker.game_context import store_context

    class R:
        def __init__(self, d):
            self._d, self.status_code = d, 200

        def json(self):
            return self._d
    summary = {"header": {"competitions": [{"competitors": [{"homeAway": "home", "team": {"id": "5"}},
                                                            {"homeAway": "away", "team": {"id": "34"}}]}]},
               "injuries": [{"team": {"id": "5"}, "injuries": [
                   {"athlete": {"displayName": "Dillon Gabriel", "position": {"abbreviation": "QB"}}, "status": "Out"}]},
                            {"team": {"id": "34"}, "injuries": [
                   {"athlete": {"displayName": "C.J. Stroud", "position": {"abbreviation": "QB"}}, "status": "Doubtful"}]}]}
    depth = {"5": "Deshaun Watson", "34": "C.J. Stroud"}

    def get(url, params=None, **k):
        if "depthcharts" in url:
            team = url.split("/teams/")[1].split("/")[0]
            return R({"depthchart": [{"positions": {"qb": {"athletes": [{"displayName": depth[team]}]}}}]})
        return R(summary)
    c = db.connect(tmp_path / "a.db")
    assert store_context(c, "nfl", {1: {"event_id": "9", "start_time": "2026-11-15T18:00:00Z"}}, "2026-11-15T12:00:00Z", get) == 1
    row = dict(c.execute("SELECT home_qb, away_qb FROM game_context WHERE game_id=1").fetchone())
    assert row == {"home_qb": None, "away_qb": "C.J. Stroud (Doubtful)"}    # CLE's injured QB is the backup
