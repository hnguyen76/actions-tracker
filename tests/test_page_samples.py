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


def test_pages_are_fetched_again_only_after_two_hours(tmp_path):
    conn, f = db.connect(tmp_path / "a.db"), Fetcher()
    page_samples.capture(conn, f, NOW)
    assert page_samples.capture(conn, f, "2026-11-25T19:45:00.000Z") == 0 and len(f.urls) == 2
    assert page_samples.capture(conn, f, "2026-11-25T20:00:00.000Z") == 2 and len(f.urls) == 4


def test_a_failed_page_is_noted_and_never_stops_the_run(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    assert page_samples.capture(conn, Fetcher(fail="/picks/game"), NOW) == 1
    rows = _rows(conn)
    assert rows["soccer_bygame"]["html_gz"] is None and "404" in rows["soccer_bygame"]["error"]
    conn2 = db.connect(tmp_path / "b.db")
    assert page_samples.capture(conn2, Fetcher(fail="/soccer/picks"), NOW) == 0
    assert "404" in _rows(conn2)["soccer_picks"]["error"]


def _page(profiles, games):
    import json
    data = {"props": {"pageProps": {"initialExpertsResponse": {"response": {"profiles": profiles}},
                                    "scoreboardResponse": {"response": {"games": games}}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


class PageFetcher(Fetcher):
    def __init__(self, picks_html):
        super().__init__()
        self.picks_html = picks_html

    def get_text(self, url):
        self.urls.append(url)
        return "<html>by game</html>" if "/picks/game" in url else self.picks_html


def test_no_picks_yet_opens_by_game_from_the_board_and_notes_the_counts(tmp_path):
    # 25/11 11:00 ET: nine Champions League games on the board, no expert pick yet
    conn = db.connect(tmp_path / "a.db")
    empty = _page([], [{"id": 296548, "experts": []}, {"id": 296549, "experts": []}])
    f = PageFetcher(empty)
    assert page_samples.capture(conn, f, NOW) == 2
    assert f.urls[1].endswith("id=296548")
    stats = [dict(r) for r in conn.execute("SELECT * FROM page_sample_stats")]
    assert [(s["name"], s["games"], s["games_with_experts"], s["picks"]) for s in stats] == [("soccer_picks", 2, 0, 0)]
    assert "soccer_picks_with_picks" not in _rows(conn)


def test_the_first_copy_with_picks_is_kept_apart_and_pick_types_are_counted(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    pick = lambda i, t: {"id": i, "game_id": 296549, "type": t, "period": "game"}  # noqa: E731
    games = [{"id": 296548, "experts": []},
             {"id": 296549, "experts": [{"id": 7, "picks": [pick(1, "ml_home"), pick(2, "draw_type_x")]}]}]
    f = PageFetcher(_page([{"id": 7, "picks": [pick(1, "ml_home")]}], games))
    page_samples.capture(conn, f, NOW)
    assert f.urls[1].endswith("id=296549")                              # a game that has experts
    row = _rows(conn)["soccer_picks_with_picks"]
    assert gzip.decompress(row["html_gz"]).decode("utf-8") == f.picks_html
    stats = dict(conn.execute("SELECT * FROM page_sample_stats").fetchone())
    assert (stats["games_with_experts"], stats["picks"]) == (1, 3)
    assert '"draw_type_x": 1' in stats["types"] and '"ml_home": 2' in stats["types"]
    empty = PageFetcher(_page([], [{"id": 296548, "experts": []}]))
    page_samples.capture(conn, empty, "2026-11-25T20:30:00.000Z")       # two hours later, nothing new
    assert "draw_type_x" in gzip.decompress(_rows(conn)["soccer_picks_with_picks"]["html_gz"]).decode("utf-8")
