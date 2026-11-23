"""Telegram alerts for an ESPN spread crossing from plus to minus."""

import pandas as pd
import pytest

from actions_tracker import alerts, db

NOW = "2026-11-23T15:00:00.000Z"


class _Resp:
    def __init__(self, code=200, text=""):
        self.status_code, self.text = code, text


def _flips(start="2026-11-23T18:00:00.000Z"):
    return pd.DataFrame([dict(
        game_id=71, league="nba", start_time=start, et_date="2026-11-23",
        away_abbr="NYK", home_abbr="BOS", side="away", team="NYK",
        open_line=2.5, current_line=-1.5, move=-4.0,
        first_seen_at="2026-11-23T13:00:00.000Z",
        crossed_at="2026-11-23T14:45:00.000Z", current_at="2026-11-23T14:45:00.000Z",
    )])


def test_spread_flip_sends_once_and_marks_after_success(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    sent = []
    post = lambda url, **kw: sent.append(kw["data"]["text"]) or _Resp()  # noqa: E731

    assert alerts.notify_spread_flips(conn, _flips(), NOW, ("TOKEN", "42"), post=post) == 1
    assert len(sent) == 1
    assert "Spread + → −" in sent[0]
    assert "NBA · NYK @ BOS" in sent[0]
    assert "NYK +2,5 → −1,5" in sent[0]
    assert "dịch −4" in sent[0] and "S21 thấy đầu" in sent[0]
    assert sent[0].endswith(alerts.DASHBOARD)
    assert alerts.notify_spread_flips(conn, _flips(), NOW, ("TOKEN", "42"), post=post) == 0
    assert len(sent) == 1


def test_failed_spread_flip_is_retried_next_scan(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    with pytest.raises(alerts.TelegramError):
        alerts.notify_spread_flips(conn, _flips(), NOW, ("TOKEN", "42"),
                                  post=lambda *a, **k: _Resp(400, "bad request"))
    assert conn.execute("SELECT count(*) FROM spread_flip_alerts").fetchone()[0] == 0
    assert alerts.notify_spread_flips(conn, _flips(), NOW, ("TOKEN", "42"),
                                     post=lambda *a, **k: _Resp()) == 1


def test_started_game_and_missing_credentials_do_not_alert(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    sent = []
    post = lambda *a, **k: sent.append(1) or _Resp()  # noqa: E731
    assert alerts.notify_spread_flips(conn, _flips("2026-11-23T14:59:00.000Z"), NOW,
                                     ("TOKEN", "42"), post=post) == 0
    assert alerts.notify_spread_flips(conn, _flips(), NOW, (None, None), post=post) == 0
    assert sent == []
