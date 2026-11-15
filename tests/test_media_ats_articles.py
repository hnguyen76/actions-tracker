"""Named article ATS selections retain the source line and refuse inferred/model picks."""

import json

import pytest

from actions_tracker import media_ats_articles as articles

COVERS = "https://www.covers.com/nfl/picks-against-the-spread-week-10-2026"
LOGAN = "https://www.covers.com/nfl/picks-and-predictions-week-10-2026"
SPORTING = "https://www.sportingnews.com/us/nfl/news/nfl-picks-predictions-against-spread-week-10/hash"
SBD = "https://www.sportsbettingdime.com/news/nfl/nfl-picks-against-the-spread-for-week-10-2026/"
NBC = "https://www.nbcsports.com/betting/nfl/news/2026-nfl-week-10-best-bets-picks-predictions-player-props-odds"


def page(body, author="Chris Vasile", headline="NFL Picks Against the Spread for Every Week 10 Game", **change):
    data = dict(**{"@type": "NewsArticle"}, headline=headline,
                author=author if isinstance(author, (dict, list)) else {"@type": "Person", "name": author}, datePublished="2026-11-13T17:00:00Z",
                dateModified="2026-11-14T16:00:00Z", isAccessibleForFree=True)
    data.update(change)
    return '<script type="application/ld+json">' + json.dumps(data) + '</script><h1>' + headline + '</h1>' + body


def test_covers_explicit_headings_read_human_side_line_and_pair():
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3><p>Prediction: Detroit wins.</p>'
                '<h3>49ers vs Cowboys: 49ers (-4.5)</h3>')
    rows = articles.parse_article(text, "nfl", COVERS)
    assert [(r["team_codes"], r["pick_code"], r["line"]) for r in rows] == [
        (["NE", "DET"], "DET", -2.5), (["SF", "DAL"], "SF", -4.5)]
    assert rows[0]["expert"] == "Chris Vasile" and rows[0]["source"] == "Covers"
    assert rows[0]["week"] == 10 and rows[0]["season"] == 2026
    assert rows[0]["published_at"] == "2026-11-13T17:00:00.000Z"
    assert rows[0]["modified_at"] == "2026-11-14T16:00:00.000Z"
    assert "away_code" not in rows[0]  # neutral-site "vs" does not invent home/away orientation


def test_covers_nested_profile_author_and_selected_underdog_headings():
    text = page('<h2>Browns +4.5 vs Texans</h2><h2>Panthers +2.5 at Saints</h2>',
                headline="NFL Week 10 Predictions: Underdog Picks Against the Spread",
                author=[{"@type": "ProfilePage", "mainEntity": {"@type": "Person", "name": "Jason Logan"}}])
    rows = articles.parse_article(text, "nfl", LOGAN)
    assert [(r["expert"], r["pick_code"], r["line"]) for r in rows] == [
        ("Jason Logan", "CLE", 4.5), ("Jason Logan", "CAR", 2.5)]
    assert rows[1]["away_code"] == "CAR" and rows[1]["home_code"] == "NO"


def test_sporting_explicit_cover_and_fail_cover_use_corresponding_spread():
    text = page('<h3>Lions (-2.5, 51.5 o/u) vs. Patriots (in Munich)</h3>'
                '<p>Pick: Lions win 27-24 and cover the spread.</p>'
                '<h3>Texans (-5.5, 39.5 o/u) at Browns</h3>'
                '<p>Pick: Texans win 20-17 but fail to cover the spread.</p>', author="Vinnie Iyer")
    rows = articles.parse_article(text, "nfl", SPORTING)
    assert [(r["pick_code"], r["line"]) for r in rows] == [("DET", -2.5), ("CLE", 5.5)]
    assert rows[1]["away_code"] == "HOU" and rows[1]["home_code"] == "CLE"


def test_sporting_never_derives_cover_from_predicted_score_alone():
    text = page('<h3>Lions (-2.5, 51.5 o/u) vs Patriots</h3><p>Pick: Lions win 27-24.</p>', author="Vinnie Iyer")
    assert articles.parse_article(text, "nfl", SPORTING) == []
    # The explicit "over" ATS selection in the heading does not require score arithmetic.
    text = page('<h3>Upset of the Week: Dolphins (+2.5, 40.5 o/u) over Colts</h3><p>Pick: Dolphins win 23-20.</p>', author="Vinnie Iyer")
    [row] = articles.parse_article(text, "nfl", SPORTING)
    assert (row["pick_code"], row["line"]) == ("MIA", 2.5)


def test_sbd_reads_ats_column_not_the_market_favorite():
    body = '<table><tr><th>Matchup</th><th>Spread</th><th>ATS Pick</th></tr>'
    body += '<tr><td>Patriots at Lions</td><td>Lions -3</td><td>Patriots +3</td></tr>'
    body += '<tr><td>Vikings at Packers</td><td>Packers -3</td><td>Vikings +3</td></tr></table>'
    rows = articles.parse_article(page(body, author="Zach Reger"), "nfl", SBD)
    assert [(r["pick_code"], r["line"]) for r in rows] == [("NE", 3.0), ("MIN", 3.0)]
    assert articles.parse_article(page(body.replace("ATS Pick", "Winner"), author="Zach Reger"), "nfl", SBD) == []


def test_nbc_only_explicit_full_game_spread_excludes_props_total_and_first_half():
    body = '<div class="RichTextArticleBody"><h3>Lions (-2.5) vs Patriots: O/U 51.5</h3>'
    body += '<p>Picks: Jared Goff Over 34.5 Pass Attempts (1 unit), Drake Maye Over 1.5 Pass TDs (1 unit)</p>'
    body += '<h3>Steelers at Bengals (-3.5): O/U 49.5</h3><p>Pick: Steelers vs Bengals 1H Under 24.5</p>'
    body += '<h3>Chargers at Ravens (-4.5): O/U 38.5</h3><p>Pick: Chargers +4.5 (1 unit)</p>'
    body += '<p>Pick: Ravens +4.5 first half</p></div>'
    rows = articles.parse_article(page(body, author="Vaughn Dalzell", headline="2026 NFL Week 10 Best Bets, Picks, Predictions, Player Props, Odds"), "nfl", NBC)
    assert len(rows) == 1 and (rows[0]["pick_code"], rows[0]["line"]) == ("LAC", 4.5)
    assert rows[0]["team_codes"] == ["LAC", "BAL"]


@pytest.mark.parametrize("change", [
    {"datePublished": None}, {"author": None}, {"isAccessibleForFree": False},
    {"author": {"name": "Covers Staff"}}, {"dateModified": "bad"},
    {"dateModified": "2026-11-12T12:00:00Z"},
    {"author": [{"name": "Chris Vasile"}, {"name": "Jason Logan"}]},
])
def test_missing_or_ambiguous_article_provenance_fails_closed(change):
    assert articles.parse_article(page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', **change), "nfl", COVERS) == []


def test_explicit_ai_model_not_attributed_to_human_author():
    body = '<p>These selections come from the SBD AI model.</p><table><tr><th>Matchup</th><th>ATS Pick</th></tr><tr><td>Patriots at Lions</td><td>Lions -3</td></tr></table>'
    assert articles.parse_article(page(body, author="Sascha Paruk"), "nfl", SBD) == []


@pytest.mark.parametrize("url", [COVERS.replace("https:", "http:"), COVERS.replace("covers.com", "covers.com.evil.test"),
                                  COVERS.replace("www.covers.com", "name@www.covers.com"), COVERS.replace("week-10", "week-9")])
def test_host_and_exact_week_are_verified(url):
    assert articles.parse_article(page('<h3>Patriots vs Lions: Lions (-2.5)</h3>'), "nfl", url) == []


def test_old_calendar_year_and_unverified_league_are_not_assumed_current():
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', datePublished="2025-11-13T17:00:00Z", dateModified="2025-11-14T17:00:00Z")
    assert articles.parse_article(text, "nfl", COVERS) == []
    assert articles.parse_article(page('<h3>Patriots vs Lions: Lions (-2.5)</h3>'), "ncaaf", COVERS) == []


def test_duplicate_pick_is_one_record_and_conflicting_pick_is_omitted():
    good = '<h3>Patriots vs Lions: Lions (-2.5)</h3>'
    assert len(articles.parse_article(page(good + good), "nfl", COVERS)) == 1
    bad = '<h3>Patriots vs Lions: Patriots (+3)</h3>'
    assert articles.parse_article(page(good + bad + good), "nfl", COVERS) == []


def test_january_final_week_keeps_previous_season():
    url = COVERS.replace("week-10-2026", "week-18-2027")
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', headline="NFL Week 18 Picks Against the Spread",
                datePublished="2027-01-01T12:00:00Z", dateModified="2027-01-02T12:00:00Z")
    [row] = articles.parse_article(text, "nfl", url)
    assert row["season"] == 2026


def test_discovery_uses_primary_week_specific_links_and_removes_tracking():
    html = '<a href="/nfl/picks-against-the-spread-week-10-2026?utm_source=x#top">yes</a>'
    html += '<a href="/nfl/picks-against-the-spread-week-1-2026">wrong week</a>'
    html += '<a href="/nfl/picks-against-the-spread-week-10-2025">wrong year</a>'
    html += '<a href="https://www.covers.com.evil.test/nfl/picks-week-10-2026">bad host</a>'
    assert articles.discover_urls(html, "https://www.covers.com/nfl/picks", "nfl", 10, 2026) == [COVERS]
    assert articles.discover_urls(html, "https://evil.test/", "nfl", 10, 2026) == []


def test_candidates_are_scoped_and_future_weeks_do_not_reuse_old_hashed_articles():
    current = articles.candidate_urls("nfl", 10, 2026)
    assert COVERS in current and SBD in current and any("sportingnews.com" in x for x in current)
    future = articles.candidate_urls("nfl", 11, 2026)
    assert future and all("week-11" in x for x in future)
    assert articles.candidate_urls("ncaaf", 10, 2026) == []
    assert len(articles.source_hubs("nfl")) == 4 and articles.source_hubs("ncaaf") == []


@pytest.mark.parametrize("market", ["first half", "1st-half", "1H", "Q1", "2Q", "first quarter", "alternate spread"])
def test_covers_partial_or_alternate_markets_are_not_full_game_ats(market):
    text = page(f'<h2>Patriots vs Lions (-2.5) — {market}</h2>')
    assert articles.parse_article(text, "nfl", COVERS) == []


def test_partial_market_article_or_sporting_section_is_rejected():
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', headline="NFL Week 10 First Half Picks Against the Spread")
    assert articles.parse_article(text, "nfl", COVERS) == []
    text = page('<h3>Lions (-2.5) vs Patriots: 1H</h3><p>Pick: Lions win 27-24 and cover the spread.</p>', author="Vinnie Iyer")
    assert articles.parse_article(text, "nfl", SPORTING) == []


def test_related_article_schema_cannot_supply_its_author_to_current_picks():
    body = '<h3>Patriots vs Lions: Lions (-2.5)</h3>'
    text = page(body, url=COVERS.replace("week-10-2026", "picks-and-predictions-week-10-2026"))
    assert articles.parse_article(text, "nfl", COVERS) == []
    text = page(body, mainEntityOfPage={"@id": "https://evil.test/nfl/picks-week-10-2026"})
    assert articles.parse_article(text, "nfl", COVERS) == []
    text = page(body).replace('<h1>NFL Picks Against the Spread for Every Week 10 Game</h1>', '<h1>Another NFL Week 10 article</h1>')
    assert articles.parse_article(text, "nfl", COVERS) == []


def test_relative_canonical_covers_metadata_and_primary_www_alias_are_supported():
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', mainEntityOfPage={"@id": "nfl/picks-against-the-spread-week-10-2026"})
    assert len(articles.parse_article(text, "nfl", COVERS)) == 1
    text = page('<h3>Patriots vs Lions: Lions (-2.5)</h3>', url=COVERS.replace("www.", "") + "?source=test")
    assert len(articles.parse_article(text, "nfl", COVERS)) == 1
