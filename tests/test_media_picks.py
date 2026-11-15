"""Media winners remain source-linked, pregame, and separate from spread picks."""

import html
import json
import sqlite3

import pandas as pd
import pytest

from actions_tracker import db, media_picks as media

NOW = "2026-11-15T01:00:00.000Z"
CBS_NFL = "https://www.cbssports.com/nfl/picks/experts/straight-up/10/"
CBS_CFB = "https://www.cbssports.com/college-football/picks/experts/straight-up/11/"
NFL = "https://www.nfl.com/news/nfl-picks-week-10-2026-nfl-season"


def _db(tmp_path):
    c = db.connect(tmp_path / "a.db")
    games = [
        dict(id=1, league="nfl", season=2026, week=10, start_time="2026-11-15T18:00:00Z", home_abbr="NYJ", home_name="New York Jets", away_abbr="BUF", away_name="Buffalo Bills"),
        dict(id=2, league="ncaaf", season=2026, week=11, start_time="2026-11-15T03:30:00Z", home_abbr="ARI", home_name="Arizona Wildcats", away_abbr="UTAH", away_name="Utah Utes"),
        dict(id=3, league="ncaaf", season=2026, week=11, start_time="2026-11-15T18:00:00Z", home_abbr="OU", home_name="Oklahoma Sooners", away_abbr="MISS", away_name="Ole Miss Rebels"),
        dict(id=4, league="nfl", season=2026, week=10, start_time="2026-11-15T21:00:00Z", home_abbr="KC", home_name="Kansas City Chiefs", away_abbr="ATL", away_name="Atlanta Falcons"),
        dict(id=5, league="nba", season=2026, week=10, start_time="2026-11-15T21:00:00Z", home_abbr="BOS", away_abbr="NYK"),
        dict(id=6, league="nfl", season=2026, week=10, start_time="2026-11-14T21:00:00Z", home_abbr="KC", away_abbr="ATL"),
    ]
    db.upsert_games(c, games, NOW)
    return c


def _board():
    return pd.DataFrame([dict(game_id=i, total_votes=n) for i, n in [(1, 8), (2, 9), (3, 8), (4, 7), (5, 10), (6, 9)]])


def _row(league="nfl", date="20261115", away="BUF", home="NYJ", picks=("BUF", "NYJ"), experts=("Pete Prisco", "Jared Dubin"), status="SUN 1:00 pm", completed=False, market="Straight Up", label=None):
    prefix = "NFL" if league == "nfl" else "NCAAF"
    section = "nfl" if league == "nfl" else "college-football"
    slugs = {"BUF": "buffalo-bills", "NYJ": "new-york-jets", "UTAH": "utah-utes", "ARIZ": "arizona-wildcats", "MISS": "ole-miss-rebels", "OKLA": "oklahoma-sooners"}
    cells = [f'<td><a class="GameMatchup" href="/{section}/gametracker/preview/{prefix}_{date}_{away}@{home}/"><span class="GameMatchup-gameStatus--status">{status}</span></a></td>']
    for expert, pick in zip(experts, picks):
        code = pick.split()[0]
        link = f'<a href="/{section}/teams/{code}/{slugs.get(code, code)}/">logo</a>'
        if completed:
            value = f'<p class="TableExpertPicks-pick">{pick}</p>'
        else:
            config = json.dumps({"marketName": market, "meta": {"bets": [{"expertLabel": label or expert}]}})
            value = "<button class='BetButton' data-config='" + html.escape(config, quote=True) + "'><div class='BetButton-text'>" + code + "</div></button>"
        cells.append('<td>' + link + value + '</td>')
    return '<tr class="TableBase-bodyTr">' + ''.join(cells) + '</tr>'


def _cbs(league="nfl", heading="Straight Up", **kwargs):
    experts = kwargs.get("experts", ("Pete Prisco", "Jared Dubin"))
    names = ''.join('<th><div class="AuthorHeadshotAndName-name">' + e + '</div></th>' for e in experts)
    return '<h1>Expert Picks - ' + heading + '</h1><table class="TableExpertPicks"><thead><tr>' + names + '</tr></thead><tbody>' + _row(league=league, **kwargs) + '</tbody></table>'


def _cfb():
    experts = ("Tom Fornelli", "Chip Patterson")
    page = _cbs("ncaaf", date="20261114", away="UTAH", home="ARIZ", picks=("UTAH", "UTAH"), experts=experts)
    extra = _row("ncaaf", date="20261114", away="MISS", home="OKLA", picks=("MISS", "OKLA"), experts=experts, status="POSTPONED")
    return page.replace('</tbody>', extra + '</tbody>')


def _nfl(published="2026-11-12T19:00:00Z", winner="Buffalo Bills"):
    data = '<script type="application/ld+json">' + json.dumps({"datePublished": published}) + '</script>' if published else ''
    cards = ''.join('<div><span class="lg:max-xl:hidden">' + name + '</span><span class="hidden">short name</span><img alt="' + winner + '"/><span>Predicted score: 30-20</span></div>' for name in ("Jeremy Bergman", "Dan Parr"))
    return data + '<h2>SUNDAY, NOV. 15</h2><a aria-label="View details for Buffalo Bills"></a><a aria-label="View details for New York Jets"></a><a href="/games/bills-at-jets-2026-reg-10">When</a><section><h2>AUTHOR PICKS</h2><div class="grid">' + cards + '</div></section>'


def _item(**kw):
    return dict(game_id=1, league="nfl", expert="Pete Prisco", source="CBS Sports", pick_team="BUF", source_url=CBS_NFL, published_at=None, **kw)


def test_cbs_upcoming_buttons_read_explicit_straight_up_and_names():
    rows = media.parse_cbs(_cbs(), "nfl", CBS_NFL)
    assert [(r["expert"], r["pick_code"]) for r in rows] == [("Pete Prisco", "BUF"), ("Jared Dubin", "NYJ")]
    assert all(r["published_at"] is None and r["event_date"] == "2026-11-15" for r in rows)


@pytest.mark.parametrize("change", [dict(heading="Against the Spread"), dict(market="Spread"), dict(label="Wrong Person")])
def test_ats_or_misaligned_expert_is_not_read_as_winner(change):
    assert media.parse_cbs(_cbs(**change), "nfl", CBS_NFL) == []


def test_wrong_route_and_integer_or_decimal_spreads_rejected():
    assert media.parse_cbs(_cbs(), "nfl", CBS_NFL.replace('straight-up/', 'spread/')) == []
    assert media.parse_cbs(_cbs(completed=True, picks=("BUF +3.5", "NYJ -7")), "nfl", CBS_NFL) == []
    assert len(media.parse_cbs(_cbs(completed=True, picks=("BUF +120", "NYJ -140")), "nfl", CBS_NFL)) == 2


def test_nfl_author_cards_supply_winner_not_cover_pick():
    rows = media.parse_nfl(_nfl(), NFL)
    assert len(rows) == 2 and all(r["pick_name"] == "Buffalo Bills" for r in rows)
    assert rows[0]["published_at"] == "2026-11-12T19:00:00.000Z"
    assert media.parse_nfl(_nfl(published=None), NFL) == []
    assert media.parse_nfl(_nfl(winner="Dallas Cowboys"), NFL) == []
    assert media.parse_nfl(_nfl(), NFL.replace('nfl-picks-week-', 'other-week-')) == []


def test_nfl_january_games_use_calendar_year_after_season_year():
    page = _nfl(published="2026-12-30T19:00:00Z").replace("NOV. 15", "JAN. 3").replace("2026-reg-10", "2026-reg-18")
    rows = media.parse_nfl(page, NFL.replace("week-10", "week-18"))
    assert len(rows) == 2 and all(r["event_date"] == "2027-01-03" and r["season"] == 2026 for r in rows)


def test_refresh_scopes_hot_games_and_caches_each_source(tmp_path):
    c = _db(tmp_path)
    calls = []
    routes = {CBS_NFL: _cbs(), CBS_CFB: _cfb(), NFL: _nfl()}
    def fetch(url):
        calls.append(url)
        return routes[url]
    assert media.refresh_picks(c, _board(), NOW, fetch) == 8
    rows = media.load_picks(c, _board(), NOW)
    assert set(rows.game_id) == {1, 2, 3} and len(rows) == 8
    assert all(rows[rows.source == "CBS Sports"].published_at.isna())
    assert rows[rows.game_id == 3].source_note.str.contains("dời ngày").all()
    assert media.refresh_picks(c, _board(), "2026-11-15T01:10:00Z", fetch) == 0 and len(calls) == 3
    media.refresh_picks(c, _board(), "2026-11-15T01:20:00Z", fetch, force=True)
    assert len(calls) == 6 and set(media.load_picks(c, _board(), "2026-11-15T01:20:00Z").fetched_at) == {NOW}


def test_accepts_existing_fetcher_object_and_new_game_scope(tmp_path):
    c = _db(tmp_path)
    class Fetcher:
        def __init__(self): self.calls = []
        def get_text(self, url):
            self.calls.append(url)
            return _cfb() if 'college-football' in url else _nfl() if 'nfl.com' in url else _cbs()
    f = Fetcher()
    board = _board()
    media.refresh_picks(c, board[board.game_id != 4], NOW, f)
    media.refresh_picks(c, board, NOW, f)  # a game joins the board (any pick count) -> sources are read again
    assert len(f.calls) == 6


def test_load_absent_table_is_read_only(tmp_path):
    c = _db(tmp_path); c.close()
    c = sqlite3.connect(f'file:{(tmp_path / "a.db").as_posix()}?mode=ro', uri=True)
    assert media.load_picks(c, _board(), NOW).empty
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='media_picks'").fetchone()


def test_canonical_expert_dedupes_yahoo_republication(tmp_path):
    c = _db(tmp_path)
    assert media.add_verified_picks(c, [_item()], NOW) == 1
    syndicated = _item(); syndicated.update(expert="PetePrisco", source="Yahoo", source_url="https://sports.yahoo.com/articles/picks.html")
    assert media.add_verified_picks(c, [syndicated], NOW) == 0
    [row] = media.load_picks(c, _board(), NOW).to_dict('records')
    assert row['expert'] == 'Pete Prisco' and row['source'] == 'CBS Sports'


@pytest.mark.parametrize('change', [dict(source_url='https://cbssports.com.evil.test/x'), dict(source_url='http://www.cbssports.com/nfl/picks/experts/straight-up/10/'), dict(market='spread'), dict(pick_team='DAL'), dict(league='nba'), dict(published_at='2026-11-16T00:00:00Z'), dict(fetched_at='2026-11-16T00:00:00Z'), dict(source_url=CBS_NFL.replace('/10/', '/9/'))])
def test_invalid_reviewed_picks_are_not_stored(tmp_path, change):
    c = _db(tmp_path); item = _item(); item.update(change)
    assert media.add_verified_picks(c, [item], NOW) == 0


def test_no_late_capture_or_started_game_is_accepted(tmp_path):
    c = _db(tmp_path)
    item = _item(); item['game_id'] = 6; item['pick_team'] = 'KC'
    assert media.add_verified_picks(c, [item], NOW) == 0
    media.add_verified_picks(c, [_item()], NOW)
    assert media.load_picks(c, _board(), '2026-11-15T19:00:00Z').empty


def test_changed_pick_older_capture_does_not_overwrite_newer_pick(tmp_path):
    c = _db(tmp_path)
    media.add_verified_picks(c, [_item()], NOW)
    old = _item(); old.update(pick_team='NYJ', fetched_at='2026-11-15T00:30:00Z')
    assert media.add_verified_picks(c, [old], NOW) == 0
    assert media.load_picks(c, _board(), NOW).iloc[0].pick_team == 'BUF'
    new = _item(); new.update(pick_team='NYJ', fetched_at='2026-11-15T01:30:00Z')
    assert media.add_verified_picks(c, [new], '2026-11-15T01:30:00Z') == 1
    assert media.load_picks(c, _board(), '2026-11-15T01:30:00Z').iloc[0].pick_team == 'NYJ'


def test_matchup_date_season_week_and_postponement_guards(tmp_path):
    c = _db(tmp_path)
    game = dict(c.execute('SELECT * FROM games WHERE id=3').fetchone())
    record = media.parse_cbs(_cfb(), 'ncaaf', CBS_CFB)[-1]
    assert media._matches(record, game)
    for change in [dict(status='SUN'), dict(event_date='2026-11-10'), dict(week=10), dict(season=2025), dict(home_name='Oklahoma State Cowboys')]:
        assert not media._matches(record | change, game)


@pytest.mark.parametrize('status', ['FINAL', 'FINAL/OT', 'LIVE', 'HALFTIME', 'IN PROGRESS', 'IN-PROGRESS', '1st 12:30', '2nd Quarter', '3rd', '4th 00:10', 'Q2', 'OVERTIME'])
def test_started_source_game_is_rejected_even_if_local_kickoff_is_future(tmp_path, status):
    c = _db(tmp_path)
    game = dict(c.execute('SELECT * FROM games WHERE id=3').fetchone())
    record = media.parse_cbs(_cfb(), 'ncaaf', CBS_CFB)[-1]
    assert not media._matches(record | {'status': status}, game)
    assert media._matches(record, game)  # the separately guarded postponed match remains valid


def test_provider_failure_keeps_previously_verified_picks_and_caches_error(tmp_path):
    c = _db(tmp_path)
    media.add_verified_picks(c, [_item()], NOW)
    calls = []
    def broken(url):
        calls.append(url)
        raise RuntimeError('provider down')
    assert media.refresh_picks(c, _board(), NOW, broken) == 0
    assert len(media.load_picks(c, _board(), NOW)) == 1
    media.refresh_picks(c, _board(), NOW, broken)
    assert len(calls) == 3


def test_empty_or_ats_html_never_creates_guessed_picks(tmp_path):
    c = _db(tmp_path)
    assert media.refresh_picks(c, _board(), NOW, lambda url: '<html>unavailable</html>') == 0
    assert media.load_picks(c, _board(), NOW).empty



def test_every_board_game_is_in_scope_not_only_eight_plus(tmp_path):
    c = _db(tmp_path)
    board = _board()
    board["total_votes"] = 2                        # far below the old 8-pick highlight
    ids = {g["id"] for g in media.media_games(c, board, NOW)}
    assert {1, 2, 3, 4} <= ids and 5 not in ids     # NBA stays out
