"""Telegram alert for a 2H play: sent once, in the run that sees the game at halftime."""

import pytest

from actions_tracker import alerts, db, live

NOW = "2026-11-22T22:40:00.000Z"


def _database(tmp_path, captured_at=NOW, second_total=21.5, score_1h=(3, 10)):
    conn = db.connect(tmp_path / "h2.db")
    db.upsert_games(conn, [dict(id=7, league="nfl", start_time="2026-11-22T21:05:00.000Z", away_abbr="NYJ",
                                home_abbr="LAC", away_name="New York Jets", home_name="Los Angeles Chargers")], "t")
    conn.execute(live.SECOND_HALF_SCHEMA)
    # 1H 3-10: NYJ +0.5 lost ATS -> NYJ in 2H; 13 points under 22.5 -> Over in 2H
    conn.execute("INSERT INTO second_half_snapshots(game_id, league, espn_event_id, captured_at, away_score_1h, "
                 "home_score_1h, first_spread_away, first_spread_home, first_total, second_spread_away, "
                 "second_spread_home, second_total) VALUES (7, 'nfl', '401873074', ?, ?, ?, 0.5, -0.5, 22.5, 3.5, "
                 "-3.5, ?)", (captured_at, *score_1h, second_total))
    conn.commit()
    return conn


def _post(sent, status=200):
    class R:
        status_code = status
        text = "err"

        def json(self):
            return {}

    def post(url, **kw):
        sent.append(kw["data"]["text"])
        return R()
    return post


def test_halftime_play_is_sent_once_with_both_markets(tmp_path):
    conn, sent = _database(tmp_path), []
    assert alerts.notify_second_half(conn, NOW, ("tok", "chat"), post=_post(sent)) == 2
    assert len(sent) == 1
    text = sent[0]
    assert "2H" in text and "NFL · NYJ @ LAC" in text and "1H 3–10" in text
    assert "NYJ +3,5" in text and "NYJ +0,5" in text and "thua ATS" in text
    assert "Over 21,5" in text and "13 &lt; 22,5" in text            # HTML-safe for Telegram
    assert "theo dõi" in text
    assert alerts.notify_second_half(conn, NOW, ("tok", "chat"), post=_post(sent)) == 0
    assert len(sent) == 1                                             # never twice


def test_old_snapshot_or_no_telegram_sends_nothing(tmp_path):
    sent = []
    old = _database(tmp_path, captured_at="2026-11-22T22:30:00.000Z")   # seen at an earlier halftime run
    assert alerts.notify_second_half(old, NOW, ("tok", "chat"), post=_post(sent)) == 0
    assert alerts.notify_second_half(old, "2026-11-22T22:30:00.000Z", (None, None), post=_post(sent)) == 0
    assert sent == []


def test_a_failed_send_is_retried_while_still_at_halftime(tmp_path):
    conn, sent = _database(tmp_path), []
    with pytest.raises(alerts.TelegramError):
        alerts.notify_second_half(conn, NOW, ("tok", "chat"), post=_post(sent, status=400))
    later = "2026-11-22T22:45:00.000Z"
    conn.execute("UPDATE second_half_snapshots SET captured_at = ?", (later,))  # next run, still halftime
    assert alerts.notify_second_half(conn, later, ("tok", "chat"), post=_post(sent)) == 2


def test_a_market_whose_2h_line_arrives_later_is_sent_then(tmp_path):
    conn, sent = _database(tmp_path, second_total=None), []
    assert alerts.notify_second_half(conn, NOW, ("tok", "chat"), post=_post(sent)) == 1   # spread only
    later = "2026-11-22T22:45:00.000Z"
    conn.execute("UPDATE second_half_snapshots SET captured_at = ?, second_total = 21.5", (later,))
    assert alerts.notify_second_half(conn, later, ("tok", "chat"), post=_post(sent)) == 1  # the total now
    assert "Over 21,5" in sent[-1] and "NYJ +3,5" not in sent[-1]


def test_live_run_sends_the_2h_alert_in_the_run_that_saves_halftime(tmp_path, monkeypatch):
    from actions_tracker import cli
    conn = _database(tmp_path, captured_at="2026-11-22T22:00:00.000Z")   # an earlier, already-old halftime
    conn.close()

    def at_halftime(conn, league, now, get=None, lines=True):          # this run sees the game at halftime
        if league == "nfl":
            conn.execute("UPDATE second_half_snapshots SET captured_at = ?", (now,))
            conn.commit()
        return {"lines": 0, "priced_of": 0, "live": 0, "final": 0, "scored_of": 0, "halftime_saved": 1}
    monkeypatch.setattr(live, "collect_espn", at_halftime)
    sent = []
    cli.live_scores(tmp_path / "h2.db", tmp_path / "site", ["nfl", "nba"], NOW, telegram=("tok", "chat"),
                    post=_post(sent))
    assert len(sent) == 1 and "NYJ +3,5" in sent[0]



# --- a move of a 2H line already announced: sent at once, with every line seen at halftime --------------------
T0, T1 = "2026-11-22T22:30:00.000Z", "2026-11-22T22:35:00.000Z"   # 17:30 / 17:35 ET


def _history(conn, rows):
    conn.execute(live.LINE_HISTORY_SCHEMA)
    conn.executemany("INSERT INTO second_half_line_history(game_id, market, line, seen_at) VALUES (7, ?, ?, ?)", rows)
    conn.commit()


def _halftime_run(conn, now, history):
    conn.execute("UPDATE second_half_snapshots SET captured_at = ?", (now,))
    _history(conn, history)


def test_a_moved_2h_line_is_sent_with_its_history(tmp_path):
    conn, sent = _database(tmp_path, captured_at=T0), []
    _history(conn, [("spread", 3.5, T0), ("total", 21.5, T0)])
    assert alerts.notify_second_half(conn, T0, ("tok", "chat"), post=_post(sent)) == 2
    assert alerts.notify_line_changes(conn, T0, ("tok", "chat"), post=_post(sent)) == 0     # first sighting only
    _halftime_run(conn, T1, [("spread", 4.5, T1)])
    assert alerts.notify_line_changes(conn, T1, ("tok", "chat"), post=_post(sent)) == 1
    text = sent[-1]
    assert "NFL · NYJ @ LAC" in text and "NYJ +3,5 → <b>+4,5</b>" in text
    assert "17:30 +3,5 · 17:35 +4,5" in text and "Over" not in text
    assert alerts.notify_line_changes(conn, T1, ("tok", "chat"), post=_post(sent)) == 0     # once per move
    _halftime_run(conn, NOW, [("spread", 5.0, NOW), ("total", 22.5, NOW)])
    assert alerts.notify_line_changes(conn, NOW, ("tok", "chat"), post=_post(sent)) == 2
    assert "NYJ +3,5 → <b>+5</b>" in sent[-1] and "17:30 +3,5 · 17:35 +4,5 · 17:40 +5" in sent[-1]
    assert "Over 21,5 → <b>22,5</b>" in sent[-1] and "17:30 21,5 · 17:40 22,5" in sent[-1]


def test_a_home_pick_shows_its_own_line(tmp_path):
    conn, sent = _database(tmp_path, captured_at=T0, score_1h=(10, 3)), []   # NYJ covered 1H -> LAC in 2H
    _history(conn, [("spread", 3.5, T0)])
    alerts.notify_second_half(conn, T0, ("tok", "chat"), post=_post(sent))
    _halftime_run(conn, T1, [("spread", 4.5, T1)])
    assert alerts.notify_line_changes(conn, T1, ("tok", "chat"), post=_post(sent)) == 1
    assert "LAC -3,5 → <b>-4,5</b>" in sent[-1] and "17:30 -3,5 · 17:35 -4,5" in sent[-1]


def test_no_move_alert_without_an_announced_play_or_after_halftime(tmp_path):
    conn, sent = _database(tmp_path, captured_at=T0), []
    _history(conn, [("spread", 3.5, T0)])
    _halftime_run(conn, T1, [("spread", 4.5, T1)])
    assert alerts.notify_line_changes(conn, T1, ("tok", "chat"), post=_post(sent)) == 0     # no play sent yet
    alerts.notify_second_half(conn, T1, ("tok", "chat"), post=_post(sent))
    _history(conn, [("spread", 5.5, NOW)])                                                    # seen, but ...
    assert alerts.notify_line_changes(conn, "2026-11-22T22:50:00.000Z", ("tok", "chat"), post=_post(sent)) == 0
    assert all("→" not in t for t in sent)                                                    # ... 2H under way


def test_a_failed_move_alert_is_retried_while_still_at_halftime(tmp_path):
    conn, sent = _database(tmp_path, captured_at=T0), []
    _history(conn, [("spread", 3.5, T0)])
    alerts.notify_second_half(conn, T0, ("tok", "chat"), post=_post(sent))
    _halftime_run(conn, T1, [("spread", 4.5, T1)])
    with pytest.raises(alerts.TelegramError):
        alerts.notify_line_changes(conn, T1, ("tok", "chat"), post=_post(sent, status=400))
    _halftime_run(conn, NOW, [])
    assert alerts.notify_line_changes(conn, NOW, ("tok", "chat"), post=_post(sent)) == 1



def test_live_run_sends_the_play_then_its_line_move(tmp_path, monkeypatch):
    from actions_tracker import cli
    conn = _database(tmp_path, captured_at="2026-11-22T22:00:00.000Z")
    conn.close()
    lines = iter([3.5, 4.5])

    def at_halftime(conn, league, now, get=None, lines_=True, **kw):
        if league == "nfl":
            conn.execute("UPDATE second_half_snapshots SET captured_at = ?", (now,))
            _history(conn, [("spread", next(lines), now)])
        return {"lines": 0, "priced_of": 0, "live": 0, "final": 0, "scored_of": 0, "halftime_saved": 1}
    monkeypatch.setattr(live, "collect_espn", at_halftime)
    sent = []
    for now in (T0, T1):
        cli.live_scores(tmp_path / "h2.db", tmp_path / "site", ["nfl"], now, telegram=("tok", "chat"), post=_post(sent))
    assert len(sent) == 2 and "NYJ +3,5" in sent[0] and "NYJ +3,5 → <b>+4,5</b>" in sent[1]
