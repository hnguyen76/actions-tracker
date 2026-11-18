from actions_tracker import db
from actions_tracker.sports_news import load_sports_news, refresh_sports_news


NOW = "2026-11-18T03:00:00.000Z"


def espn_payload(items=None):
    return {"breakingNews": items if items is not None else [{
        "id": "espn-1",
        "headline": "Star quarterback ruled out tonight",
        "section": "NFL",
        "published": "2026-11-18T02:40:00Z",
        "links": {"web": {"href": "https://www.espn.com/nfl/story/_/id/1/news"}},
    }]}


def yahoo_rss(title="NBA star returns after injury"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>{title}</title><guid>yahoo-1</guid>
    <link>https://sports.yahoo.com/nba-star-returns-024500.html</link>
    <category>NBA</category><pubDate>Wed, 18 Nov 2026 02:45:00 GMT</pubDate></item>
  <item><title>Old story</title><guid>yahoo-old</guid>
    <link>https://sports.yahoo.com/old-story.html</link>
    <pubDate>Mon, 16 Nov 2026 02:45:00 GMT</pubDate></item>
</channel></rss>"""


def test_refreshes_espn_breaking_and_yahoo_then_reuses_translation_cache(tmp_path):
    conn = db.connect(tmp_path / "news.db")
    translated = []

    def translate(headline):
        translated.append(headline)
        return "VI: " + headline

    changed = refresh_sports_news(conn, NOW, get_json=lambda _url: espn_payload(),
                                  get_text=lambda _url: yahoo_rss(), translator=translate)
    rows = load_sports_news(conn)
    assert changed == 2
    assert list(rows.source) == ["ESPN", "Yahoo Sports"]
    assert list(rows.is_breaking) == [1, 0]
    assert list(rows.headline_vi) == ["VI: Star quarterback ruled out tonight", "VI: NBA star returns after injury"]
    assert translated == ["Star quarterback ruled out tonight", "NBA star returns after injury"]

    def should_not_translate(_headline):
        raise AssertionError("unchanged headlines must use the SQLite translation cache")

    assert refresh_sports_news(conn, NOW, get_json=lambda _url: espn_payload(),
                               get_text=lambda _url: yahoo_rss(), translator=should_not_translate) == 0


def test_empty_espn_breaking_list_deactivates_only_espn(tmp_path):
    conn = db.connect(tmp_path / "news.db")
    translate = lambda headline: "VI: " + headline
    refresh_sports_news(conn, NOW, get_json=lambda _url: espn_payload(),
                        get_text=lambda _url: yahoo_rss(), translator=translate)
    changed = refresh_sports_news(conn, NOW, get_json=lambda _url: espn_payload([]),
                                  get_text=lambda _url: yahoo_rss(), translator=translate)
    rows = load_sports_news(conn)
    assert changed == 1
    assert list(rows.source) == ["Yahoo Sports"]


def test_source_failure_keeps_last_good_cache(tmp_path):
    conn = db.connect(tmp_path / "news.db")
    refresh_sports_news(conn, NOW, get_json=lambda _url: espn_payload(),
                        get_text=lambda _url: yahoo_rss(), translator=lambda headline: "VI: " + headline)

    def failed(_url):
        raise RuntimeError("temporary network failure")

    assert refresh_sports_news(conn, NOW, get_json=failed, get_text=failed,
                               translator=lambda _headline: "unused") == 0
    assert set(load_sports_news(conn).source) == {"ESPN", "Yahoo Sports"}


def test_untrusted_story_links_are_not_published(tmp_path):
    conn = db.connect(tmp_path / "news.db")
    payload = espn_payload()
    payload["breakingNews"][0]["links"]["web"]["href"] = "https://example.com/fake"
    xml = yahoo_rss().replace("https://sports.yahoo.com/nba-star-returns-024500.html", "http://sports.yahoo.com/not-https")
    assert refresh_sports_news(conn, NOW, get_json=lambda _url: payload, get_text=lambda _url: xml,
                               translator=lambda headline: headline) == 0
    assert load_sports_news(conn).empty
