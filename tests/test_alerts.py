"""Telegram alert before kickoff: which games are due, what the message says, sent once."""

import pandas as pd

from actions_tracker import alerts, db
from actions_tracker.cli import alert, telegram_setup

NOW = "2026-11-14T23:00:00.000Z"          # Sat 18:00 ET
SOON = "2026-11-14T23:15:00.000Z"         # 18:15 ET -> due
LATER = "2026-11-15T00:30:00.000Z"        # 19:30 ET -> not yet


def _db(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [dict(id=1, league="ncaaf", start_time=SOON, home_abbr="UK", away_abbr="FLA"),
                        dict(id=2, league="ncaaf", start_time=SOON, home_abbr="UCF", away_abbr="ASU"),
                        dict(id=3, league="ncaaf", start_time=LATER, home_abbr="LSU", away_abbr="TEX"),
                        dict(id=4, league="nfl", start_time=SOON, home_abbr="NOP", away_abbr="NOK")], "t")
    db.upsert_picks(c, [dict(id=10 + g, expert_id=1, game_id=g, league="ncaaf", market="spread", pick_side="home",
                             created_at="2026-11-14T10:00:00.000Z") for g in (1, 2, 3)], "t")
    return c


def _tables():
    decisions = pd.DataFrame([
        dict(game_id=1, market="spread", action="paper", pick="UK -3", stake_u=0.0,
             reason="NCAAF spread: Mon–Fri theo đa số, Sat–Sun đánh ngược: đa số FLA 3/5"),
        dict(game_id=2, market="total", action="paper", pick="Under 46,5", stake_u=0.0, reason="NCAAF total"),
        dict(game_id=2, market="spread", action="skip", pick="Đa số chọn UCF (4/5)", stake_u=0.0, reason="x"),
    ])
    board = pd.DataFrame([dict(game_id=1, market="spread", total_votes=5), dict(game_id=2, market="total", total_votes=3),
                          dict(game_id=2, market="spread", total_votes=5)])
    return {"Decisions": decisions, "Upcoming_Board": board}


def test_due_games_only_soon_with_picks_and_not_sent(tmp_path):
    c = _db(tmp_path)
    assert [g["id"] for g in alerts.due_games(c, NOW)] == [1, 2]   # game 3 is later, game 4 has no picks
    alerts.mark_sent(c, [1], NOW)
    assert [g["id"] for g in alerts.due_games(c, NOW)] == [2]


def test_message_lists_games_and_hides_small_totals(tmp_path):
    c = _db(tmp_path)
    [msg] = alerts.build_messages(alerts.due_games(c, NOW), _tables(), NOW)
    assert "18:15 ET Sat 14/11" in msg and "còn 15 phút" in msg and "2 trận" in msg
    assert "NCAAF · FLA @ UK" in msg and "📝 Spread: UK -3 · 5 expert\n" in msg
    assert "Under 46,5" not in msg                       # total with 3 experts is hidden, like on the dashboard
    assert "▫️ Spread: Đa số chọn UCF (4/5) · 5 expert · bỏ qua" in msg
    assert msg.endswith("\n\n" + alerts.DASHBOARD) and "Không đặt tiền thật" not in msg


def test_weekday_user_decision_keeps_a_small_total_in_telegram():
    games = [dict(id=2, league="nba", start_time=SOON, home_abbr="BOS", away_abbr="NYK")]
    decisions = pd.DataFrame([dict(game_id=2, market="total", action="mine", pick="Under 221,5",
                                   stake_u=0.0, reason="Cách của bạn")])
    board = pd.DataFrame([dict(game_id=2, market="total", total_votes=3)])
    [msg] = alerts.build_messages(games, {"Decisions": decisions, "Upcoming_Board": board}, NOW)
    assert "⭐ Total: <b>Under 221,5</b> · 3 expert" in msg


def _last_game_tables(final_start=SOON, late_detail="2:00 - 4th"):
    prior = "2026-11-14T22:00:00.000Z"
    tables = _tables()
    tables["Picks"] = pd.DataFrame([
        dict(game_id=10, start_time=prior), dict(game_id=1, start_time=final_start),
    ])
    tables["Decision_Method"] = pd.DataFrame([
        dict(game_id=10, league="nba", market="spread", start_time=prior, et_date="2026-11-14", result="win"),
        dict(game_id=11, league="nba", market="spread", start_time=prior, et_date="2026-11-14", result="loss"),
        dict(game_id=12, league="nba", market="total", start_time=prior, et_date="2026-11-14", result="loss"),
        dict(game_id=13, league="ncaaf", market="spread", start_time=prior, et_date="2026-11-14", result="loss"),
        dict(game_id=14, league="nba", market="spread", start_time=prior, et_date="2026-11-14", result=None),
        dict(game_id=1, league="ncaaf", market="spread", start_time=final_start, et_date="2026-11-14", result=None),
    ])
    tables["In_Play"] = pd.DataFrame([
        dict(game_id=14, league="nba", market="spread", state="live", detail=late_detail,
             source="Cách của bạn", now="loss"),
    ])
    tables["Scores"] = pd.DataFrame([
        dict(game_id=14, situation={"period": 4, "clock": late_detail.split(" ", 1)[0]}),
    ])
    return tables


def test_last_game_message_reports_eighty_percent_losses_including_late_live_lean():
    games = [dict(id=1, league="ncaaf", start_time=SOON, home_abbr="UK", away_abbr="FLA")]
    [msg] = alerts.build_messages(games, _last_game_tables(), NOW)
    assert "🏁 <b>TRẬN CUỐI TRONG NGÀY</b>" in msg
    assert "1 thắng · 4 thua — thắng 20% / thua 80% · gồm 1 kèo gần hết giờ" in msg
    assert "🔴 <b>Hôm nay thua chiếm đa số: 80%</b>" in msg


def test_live_lean_before_last_five_minutes_is_not_counted():
    games = [dict(id=1, league="ncaaf", start_time=SOON, home_abbr="UK", away_abbr="FLA")]
    [msg] = alerts.build_messages(games, _last_game_tables(late_detail="7:43 - 4th"), NOW)
    assert "1 thắng · 3 thua — thắng 25% / thua 75%" in msg
    assert "gần hết giờ" not in msg and "chiếm đa số" not in msg


def test_game_is_not_labeled_last_when_a_later_picked_game_exists():
    tables = _last_game_tables()
    tables["Picks"] = pd.concat([tables["Picks"], pd.DataFrame([
        dict(game_id=99, start_time="2026-11-15T00:30:00.000Z"),
    ])], ignore_index=True)
    games = [dict(id=1, league="ncaaf", start_time=SOON, home_abbr="UK", away_abbr="FLA")]
    [msg] = alerts.build_messages(games, tables, NOW)
    assert "TRẬN CUỐI" not in msg and "Trước trận cuối" not in msg


def test_long_slot_is_split_under_the_telegram_limit(tmp_path):
    games = [dict(id=i, league="ncaaf", start_time=SOON, home_abbr=f"H{i}", away_abbr=f"A{i}") for i in range(80)]
    decisions = pd.DataFrame([dict(game_id=i, market="spread", action="paper", pick=f"H{i} -3", stake_u=0.0,
                                   reason="x" * 150) for i in range(80)])
    msgs = alerts.build_messages(games, {"Decisions": decisions, "Upcoming_Board": pd.DataFrame()}, NOW)
    assert len(msgs) > 1 and all(len(m) <= 4096 for m in msgs) and "(tiếp)" in msgs[1]


class _Resp:
    def __init__(self, code=200, data=None):
        self.status_code, self.text, self._data = code, "", data or {}

    def json(self):
        return self._data


def test_alert_sends_once_then_stays_quiet(tmp_path, monkeypatch):
    c = _db(tmp_path)
    c.close()
    sent, runs = [], []
    monkeypatch.setattr("actions_tracker.cli.run", lambda *a, **k: runs.append(k.get('budget') and {'budget': True}) or 0)
    monkeypatch.setattr("actions_tracker.cli.build_tables", lambda *a: _tables())
    post = lambda url, **k: sent.append((url, k["data"])) or _Resp()  # noqa: E731
    args = (tmp_path / "a.db", tmp_path / "r.xlsx", tmp_path / "site", ["ncaaf"], None, lambda: NOW, None)
    assert alert(*args, ("TOKEN", "42"), post=post) == 0
    assert runs == [{"budget": True}] and len(sent) == 1 and sent[0][1]["chat_id"] == "42"
    assert alert(*args, ("TOKEN", "42"), post=post) == 0      # already announced -> no new message, no collection
    assert len(sent) == 1 and len(runs) == 1
    check = db.connect(tmp_path / "a.db")
    assert check.execute("SELECT value FROM meta WHERE key=?", (alerts.DELIVERY_ERROR_KEY,)).fetchone() is None


def test_alert_without_telegram_config_does_not_mark_sent(tmp_path, capsys):
    _db(tmp_path).close()
    args = (tmp_path / "a.db", tmp_path / "r.xlsx", tmp_path / "site", ["ncaaf"], None, lambda: NOW, None)
    assert alert(*args, (None, None)) == 6
    assert "telegram-setup" in capsys.readouterr().out
    assert len(alerts.due_games(db.connect(tmp_path / "a.db"), NOW)) == 2


def test_telegram_failure_keeps_games_due(tmp_path, monkeypatch):
    _db(tmp_path).close()
    monkeypatch.setattr("actions_tracker.cli.run", lambda *a, **k: 0)
    monkeypatch.setattr("actions_tracker.cli.build_tables", lambda *a: _tables())
    args = (tmp_path / "a.db", tmp_path / "r.xlsx", tmp_path / "site", ["ncaaf"], None, lambda: NOW, None)
    assert alert(*args, ("TOKEN", "42"), post=lambda url, **k: _Resp(401)) == 6
    c = db.connect(tmp_path / "a.db")
    assert len(alerts.due_games(c, NOW)) == 2
    error = c.execute("SELECT value FROM meta WHERE key=?", (alerts.DELIVERY_ERROR_KEY,)).fetchone()[0]
    assert error == f"{NOW}|HTTP 401: "


def test_telegram_retries_rate_limit_then_succeeds():
    responses = [_Resp(429, {"parameters": {"retry_after": 3}}), _Resp()]
    waits = []
    alerts.send_telegram("TOKEN", "42", "test", post=lambda *a, **k: responses.pop(0), sleep=waits.append)
    assert waits == [3] and responses == []


def test_telegram_retries_temporary_network_error_then_succeeds():
    calls, waits = [], []

    def post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise alerts.requests.ConnectionError("offline")
        return _Resp()

    alerts.send_telegram("TOKEN", "42", "test", post=post, sleep=waits.append)
    assert len(calls) == 2 and waits == [1]


def test_telegram_setup_saves_chat_id_and_sends_test(tmp_path):
    (tmp_path / alerts.TOKEN_FILE).write_text("TOKEN\n", "utf-8")
    sent = []
    get = lambda url, **k: _Resp(data={"result": [{"message": {"chat": {"id": 777}}}]})  # noqa: E731
    assert telegram_setup(tmp_path, get=get, post=lambda url, **k: sent.append(k["data"]) or _Resp()) == 0
    assert (tmp_path / alerts.CHAT_FILE).read_text("utf-8") == "777" and sent[0]["chat_id"] == "777"



def _board(votes_by_game):
    return pd.DataFrame([dict(game_id=g, league="ncaaf", market="spread", start_time=SOON, away_abbr="AW", home_abbr="HM",
                              a_side="away", a_votes=v - 1, a_line=3.5, b_side="home", b_votes=1, b_line=-3.5,
                              total_votes=v, status="majority") for g, v in votes_by_game.items()])


def test_rising_markets_first_run_records_then_reports_new_ones(tmp_path):
    c = _db(tmp_path)
    sent = []
    post = lambda url, **k: sent.append(k["data"]["text"]) or _Resp()  # noqa: E731
    # first run: game 1 already has 6 picks -> recorded silently, no message
    assert alerts.notify_rising(c, _board({1: 6, 2: 3}), NOW, ("T", "42"), post=post) == 0 and sent == []
    # game 2 grows from 3 to 5 picks -> one message; game 1 is not repeated
    assert alerts.notify_rising(c, _board({1: 7, 2: 5}), NOW, ("T", "42"), post=post) == 1
    assert len(sent) == 1 and "Kèo vừa lên ≥ 5 picks" in sent[0] and "AW +3,5 4 · HM -3,5 1 (5 picks)" in sent[0]
    assert "Kèo đang ≥ 10 picks</b> · 0 kèo" in sent[0]  # the 10+ summary rides along (none here)
    # nothing new -> quiet; without Telegram config -> nothing at all
    assert alerts.notify_rising(c, _board({1: 7, 2: 6}), NOW, ("T", "42"), post=post) == 0 and len(sent) == 1
    assert alerts.notify_rising(c, _board({3: 9}), NOW, (None, None), post=post) == 0



def test_rising_message_lists_heavy_markets():
    rows = _board({1: 5, 2: 12}).to_dict("records")
    [msg] = alerts.rising_messages(rows[:1], heavy=rows[1:])
    assert msg.index("Kèo vừa lên") < msg.index("Kèo đang ≥ 10 picks</b> · 1 kèo") < msg.index("(12 picks)")
