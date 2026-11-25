"""A recent copy of Action Network pages not parsed yet (soccer), saved in the database the phone commits."""

import gzip
from pathlib import Path

from actions_tracker import db, page_samples
from actions_tracker.fetch import FetchError

NOW = "2026-11-25T18:00:00.000Z"
PICKS = (Path(__file__).parent / "fixtures" / "mini_picks.html").read_text("utf-8")


class Fetcher:
    def __init__(self, fail=None):
        self.urls, self.fail = [], fail

    def get_text(self, url):
        self.urls.append(url)
        if self.fail and self.fail in url:
            raise FetchError("HTTP 404")
        return "<html>by game</html>" if "/picks/game" in url else PICKS


def _rows(conn):
    return {r["name"]: dict(r) for r in conn.execute("SELECT * FROM page_samples")}


def test_soccer_picks_and_by_game_pages_are_saved_compressed(tmp_path):
    conn, f = db.connect(tmp_path / "a.db"), Fetcher()
    assert page_samples.capture(conn, f, NOW) == 2
    assert f.urls[0].endswith("/soccer/picks") and "/soccer/picks/game?id=" in f.urls[1]
    rows = _rows(conn)
    assert gzip.decompress(rows["soccer_picks"]["html_gz"]).decode("utf-8") == PICKS
    assert gzip.decompress(rows["soccer_bygame"]["html_gz"]).decode("utf-8") == "<html>by game</html>"
    assert rows["soccer_picks"]["fetched_at"] == NOW and rows["soccer_picks"]["error"] is None


def test_pages_are_fetched_again_only_after_twelve_hours(tmp_path):
    conn, f = db.connect(tmp_path / "a.db"), Fetcher()
    page_samples.capture(conn, f, NOW)
    assert page_samples.capture(conn, f, "2026-11-26T05:00:00.000Z") == 0 and len(f.urls) == 2
    assert page_samples.capture(conn, f, "2026-11-26T06:30:00.000Z") == 2 and len(f.urls) == 4


def test_a_failed_page_is_noted_and_never_stops_the_run(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    assert page_samples.capture(conn, Fetcher(fail="/picks/game"), NOW) == 1
    rows = _rows(conn)
    assert rows["soccer_bygame"]["html_gz"] is None and "404" in rows["soccer_bygame"]["error"]
    conn2 = db.connect(tmp_path / "b.db")
    assert page_samples.capture(conn2, Fetcher(fail="/soccer/picks"), NOW) == 0
    assert "404" in _rows(conn2)["soccer_picks"]["error"]
