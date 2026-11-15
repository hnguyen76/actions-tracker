import sqlite3

import pandas as pd
import pytest

from actions_tracker import db, match_news as news

NOW = "2026-11-14T23:00:00.000Z"
FUTURE = "2026-11-15T01:00:00.000Z"


def _db(tmp_path):
    conn = db.connect(tmp_path / "news.db")
    games = [dict(id=1, league="nfl", start_time=FUTURE, home_abbr="BUF", away_abbr="NYJ",
                  home_name="Buffalo Bills", away_name="New York Jets"),
             dict(id=2, league="nfl", start_time=FUTURE, home_abbr="KC", away_abbr="ATL"),
             dict(id=3, league="nba", start_time=FUTURE, home_abbr="BOS", away_abbr="NYK"),
             dict(id=4, league="nfl", start_time="2026-11-14T12:00:00Z", home_abbr="GB", away_abbr="MIN"),
             dict(id=5, league="ncaaf", start_time=FUTURE, home_abbr="MICH", away_abbr="MSU",
                  home_name="Michigan Wolverines", away_name="Michigan State Spartans")]
    db.upsert_games(conn, games, NOW)
    return conn


def _board():
    return pd.DataFrame([dict(game_id=g, total_votes=v) for g, v in ((1, 8), (1, 10), (2, 7), (3, 12), (4, 8), (5, 8))])


def _html(player="Player One", headline="Ruled out for Sunday", body="One has been ruled out.",
          team="Buffalo Bills", code="BUF", date="November 14, 2026", rank=100):
    return f'''<div class="news-update is-injured"><div class="news-update__top">
      <img class="news-update__logo" alt="{code}"><div><a class="news-update__player-link">{player}</a>
      <a class="news-update__headline" href="/football/headlines/player-news-{rank}">{headline}</a></div></div>
      <div class="news-update__meta"><div><b class="news-update__pos">WR</b>{team}</div>
      <div class="news-update__inj">Knee</div></div><div class="news-update__main">
      <div class="news-update__timestamp">{date}</div><div class="news-update__news">{body}</div>
      <div class="news-update__analysis">SUBSCRIBER CONTENT MUST NOT BE READ</div></div></div>'''


def _item(**changes):
    item = dict(game_id=1, league="nfl", team_abbr="BUF", sentiment="positive", summary="Cầu thủ trở lại.",
                source="PFF", url="https://www.pff.com/news/update", published_at=NOW, subject="player")
    return item | changes


def test_exact_threshold_and_deduplication_exclude_other_leagues_and_started_games(tmp_path):
    conn = _db(tmp_path)
    assert [g["id"] for g in news.eligible_games(conn, _board(), NOW)] == [1, 5]
    assert news.eligible_games(conn, pd.DataFrame(), NOW) == []


def test_load_without_news_table_is_read_only(tmp_path):
    conn = _db(tmp_path)
    assert news.load_news(conn, _board(), NOW).columns.tolist() == news.NEWS_COLS
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='match_news'").fetchone() is None


def test_public_html_parser_keeps_team_and_omits_subscriber_analysis():
    [row] = news.parse_rotowire(_html())
    assert row["team"] == "Buffalo Bills" and row["team_code"] == "BUF"
    assert row["player"] == "Player One" and row["headline"] == "Ruled out for Sunday"
    assert row["url"] == "https://www.rotowire.com/football/headlines/player-news-100"
    assert "SUBSCRIBER" not in str(row) and row["body"] == "One has been ruled out."


@pytest.mark.parametrize("headline,sentiment,part", [
    ("Ruled out for Sunday", "negative", "không thi đấu"),
    ("Questionable for Sunday", "negative", "chưa chắc"),
    ("Limited practice Thursday", "negative", "tập hạn chế"),
    ("Full practice participant", "positive", "tập luyện đầy đủ"),
    ("Expected to play Sunday", "positive", "dự kiến"),
])
def test_conservative_vietnamese_status_templates(headline, sentiment, part):
    result = news.classify(dict(player="Player", headline=headline, body=""))
    assert result[0] == sentiment and part in result[1] and len(result[1]) <= 150


def test_fantasy_performance_is_not_automatically_favorable_and_headline_wins():
    assert news.classify(dict(player="Player", headline="Scores in loss", body="He caught two touchdowns.")) is None
    assert news.classify(dict(player="Player", headline="No injury designation", body="He was ruled out last week."))[0] == "positive"
    assert "sẵn sàng thi đấu" not in news.classify(dict(player="Player", headline="Full practice", body=""))[1]


def test_team_matching_does_not_confuse_michigan_and_michigan_state():
    game = dict(league="ncaaf", home_abbr="MICH", away_abbr="MSU", home_name="Michigan Wolverines", away_name="Michigan State Spartans")
    assert news._same_team({"team": "Michigan"}, game, "home")
    assert not news._same_team({"team": "Michigan"}, game, "away")
    assert news._same_team({"team": "Michigan State"}, game, "away")
    ole_miss = dict(league="ncaaf", home_abbr="MISS", home_name="Mississippi Rebels")
    assert news._same_team({"team": "Ole Miss"}, ole_miss, "home")


def test_refresh_only_fetches_eligible_teams_and_hourly_cache(tmp_path):
    conn = _db(tmp_path)
    board = _board().query("game_id != 5")
    calls = []
    fetcher = lambda url: calls.append(url) or _html()
    assert news.refresh_news(conn, board, NOW, fetcher) == 1
    assert set(calls) == {"https://www.rotowire.com/football/news.php?team=BUF", "https://www.rotowire.com/football/news.php?team=NYJ"}
    [row] = news.load_news(conn, board, NOW).to_dict("records")
    assert row["game_id"] == 1 and row["team_abbr"] == "BUF" and row["sentiment"] == "negative"
    assert news.refresh_news(conn, board, NOW, fetcher) == 0 and len(calls) == 2


def test_refresh_accepts_existing_fetcher_object(tmp_path):
    conn = _db(tmp_path)
    class Fetcher:
        def get_text(self, url):
            return _html()
    assert news.refresh_news(conn, _board(), NOW, Fetcher()) == 1


def test_newer_cleared_update_supersedes_older_same_player_injury(tmp_path):
    conn = _db(tmp_path)
    html = _html(rank=100) + _html(headline="No injury designation", rank=101)
    news.refresh_news(conn, _board(), NOW, lambda url: html)
    rows = news.load_news(conn, _board(), NOW)
    assert len(rows) == 1 and rows.iloc[0].sentiment == "positive"
    # A later generic update removes an old injury rather than guessing its impact.
    news.refresh_news(conn, _board(), NOW, lambda url: _html(headline="Scores in loss", body="Caught a touchdown.", rank=102), force=True)
    assert news.load_news(conn, _board(), NOW).empty


def test_reviewed_same_day_latest_story_is_not_overwritten_by_older_auto_story(tmp_path):
    conn = _db(tmp_path)
    news.add_verified_news(conn, [_item(subject="Player One", published_at="2026-11-14T05:00:00.000Z",
                                      url="https://www.rotowire.com/football/headlines/player-news-101")], NOW)
    news.refresh_news(conn, _board(), NOW, lambda url: _html(rank=100))
    [row] = news.load_news(conn, _board(), NOW).to_dict("records")
    assert row["sentiment"] == "positive" and row["url"].endswith("-101")


def test_old_future_and_wrong_team_reports_are_not_shown(tmp_path):
    conn = _db(tmp_path)
    html = _html(date="November 10, 2026") + _html(player="Future", date="November 15, 2026", rank=101)
    html += _html(player="Other", team="Atlanta Falcons", code="ATL", rank=102)
    news.refresh_news(conn, _board(), NOW, lambda url: html)
    assert news.load_news(conn, _board(), NOW).empty


def test_fetch_failures_preserve_fresh_news_and_are_cached(tmp_path):
    conn = _db(tmp_path)
    news.add_verified_news(conn, [_item()], NOW)
    calls = []
    def broken(url):
        calls.append(url)
        raise RuntimeError("provider unavailable")
    assert news.refresh_news(conn, _board(), NOW, broken) == 0
    assert not news.load_news(conn, _board(), NOW).empty
    news.refresh_news(conn, _board(), NOW, broken)
    assert len(calls) == 4
    assert news.load_news(conn, _board(), "2026-11-18T00:00:00Z").empty


def test_bad_html_never_breaks_refresh(tmp_path):
    conn = _db(tmp_path)
    assert news.refresh_news(conn, _board(), NOW, lambda url: "<html>unavailable</html>") == 0
    assert news.load_news(conn, _board(), NOW).empty


def test_verified_sources_limit_per_sentiment_and_current_eligibility(tmp_path):
    conn = _db(tmp_path)
    items = [_item(subject=f"p{i}", url=f"https://www.pff.com/news/{i}") for i in range(4)]
    items += [_item(subject="evil", url="https://pff.com.evil.invalid/news"),
              _item(subject="http", url="http://www.pff.com/news/x"),
              _item(subject="future", published_at="2026-11-15T12:00:00Z"),
              _item(subject="wrongteam", team_abbr="KC")]
    assert news.add_verified_news(conn, items, NOW) == 4
    assert len(news.load_news(conn, _board(), NOW)) == 2
    assert news.load_news(conn, pd.DataFrame([dict(game_id=1, total_votes=7)]), NOW).empty


def test_expired_verified_item_is_not_loaded(tmp_path):
    conn = _db(tmp_path)
    assert news.add_verified_news(conn, [_item(expires_at="2026-11-14T22:59:00Z")], NOW) == 0


def test_available_headline_preserves_explicit_same_player_uncertainty():
    sentiment, summary = news.classify({
        "player": "Player One", "headline": "Will be available Saturday",
        "body": "Listed available. Warmups will determine whether or not One will actually play.",
    })
    assert sentiment == "negative" and "chưa chắc ra sân" in summary


def test_newly_highlighted_game_is_checked_before_hourly_cache_expires(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO games(id,league,start_time,home_abbr,home_name,away_abbr,away_name) "
                 "VALUES (6,'ncaaf','2026-11-15T23:00:00Z','TEX','Texas Longhorns','LSU','LSU Tigers')")
    calls = []
    def fetch(url):
        calls.append(url)
        return _html(team="Texas", code="TEX", player="New Player")
    board = pd.DataFrame([dict(game_id=5, total_votes=8)])
    news.refresh_news(conn, board, NOW, fetch)
    assert len(calls) == 2
    board = pd.concat([board, pd.DataFrame([dict(game_id=6, total_votes=8)])], ignore_index=True)
    news.refresh_news(conn, board, NOW, fetch)
    assert len(calls) == 4 and 6 in set(news.load_news(conn, board, NOW).game_id)
