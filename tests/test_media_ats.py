"""CBS expert picks against the spread: parsed from the week table, matched to board games, kept per expert."""

import json
import sqlite3

import pandas as pd

from actions_tracker import db
from actions_tracker import media_ats as ats

URL = "https://www.cbssports.com/nfl/picks/experts/against-the-spread/10/"
NOW = "2026-11-15T16:00:00.000Z"


def _done(team, line):
    return f'<td><div class="TableExpertPicks-cellWrapper"><p class="TableExpertPicks-pick"> {team} {line} </p></div></td>'


def _button(expert, team, line, market="Spread"):
    cfg = json.dumps({"marketName": market, "meta": {"bets": [{"expertLabel": expert}]}, "line": line})
    return (f"<td><button class=\"BetButton cbs-widget\" data-config='{cfg}'>"
            f'<div class="BetButton-text"> {team} {line} </div></button></td>')


def _page(rows, experts=("Pete Prisco", "Jared Dubin"), title="NFL Week 10 Expert Picks - Against the Spread"):
    head = "".join(f'<th><span class="AuthorHeadshotAndName-name">{e}</span></th>' for e in experts)
    body = "".join(f'<tr class="TableBase-bodyTr"><td><a class="GameMatchup" href="/nfl/gametracker/preview/'
                   f'NFL_{date}_{away}@{home}/">x</a></td>{cells}</tr>' for date, away, home, cells in rows)
    return f'<h1>{title}</h1><table class="TableExpertPicks"><tr>{head}</tr>{body}</table>'


PAGE = _page([
    ("20261115", "SF", "DAL", _button("Pete Prisco", "DAL", "+3.5") + _button("Jared Dubin", "SF", "-3.5")),
    ("20261115", "NE", "DET", _done("DET", "-3") + _done("DET", "-3")),
    ("20261115", "MIA", "IND", _button("Pete Prisco", "IND", "-4.5", market="Moneyline") + _done("PK", "x")),
])


def test_parse_reads_upcoming_buttons_and_finished_cells_only_for_the_spread_market():
    rows = ats.parse_cbs_ats(PAGE, "nfl", URL)
    got = {(r["away_code"], r["expert"]): (r["pick_code"], r["line"]) for r in rows}
    assert got == {("SF", "Pete Prisco"): ("DAL", 3.5), ("SF", "Jared Dubin"): ("SF", -3.5),
                   ("NE", "Pete Prisco"): ("DET", -3.0), ("NE", "Jared Dubin"): ("DET", -3.0)}
    assert ats.parse_cbs_ats(PAGE.replace("Against the Spread", "Straight Up"), "nfl", URL) == []
    assert ats.parse_cbs_ats(PAGE, "nfl", URL.replace("against-the-spread", "straight-up")) == []


def test_refresh_matches_board_games_and_load(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [dict(id=1, league="nfl", week=10, season=2026, start_time="2026-11-15T21:25:00.000Z",
                             home_abbr="DAL", away_abbr="SF"),
                        dict(id=2, league="nfl", week=10, season=2026, start_time="2026-11-15T14:30:00.000Z",
                             home_abbr="DET", away_abbr="NE")], "t")
    db.upsert_picks(c, [dict(id=9, expert_id=1, game_id=2, league="nfl", market="spread", pick_side="home",
                             created_at="2026-11-15T10:00:00.000Z")], "t")
    calls = []
    board = pd.DataFrame([dict(game_id=1, total_votes=7)])
    assert ats.refresh_ats(c, board, NOW, lambda url: calls.append(url) or PAGE) == 4
    assert calls.count(URL) == 1
    assert any("covers.com" in url for url in calls)
    initial_calls = len(calls)
    df = ats.load_ats(c, board, NOW).set_index(["game_id", "expert"])
    assert df.loc[(1, "Pete Prisco"), "pick_team"] == "DAL" and df.loc[(1, "Jared Dubin"), "line"] == -3.5
    assert df.loc[(2, "Pete Prisco"), "pick_team"] == "DET"      # started game kept (CBS locks picks at kickoff)
    assert ats.refresh_ats(c, board, NOW, lambda url: calls.append(url) or PAGE) == 0 and len(calls) == initial_calls  # hourly


def _article(**changes):
    row = dict(game_id=1, league="nfl", expert="Zach Reger", source="SportsBettingDime", pick_code="DAL", line=3.5,
               team_codes=["SF", "DAL"], week=10, season=2026, source_url="https://www.sportsbettingdime.com/news/nfl/nfl-picks-against-the-spread-for-week-10-2026/",
               published_at="2026-11-13T17:14:00Z", modified_at="2026-11-14T12:00:00Z")
    row.update(changes)
    return row


def _games_db(tmp_path):
    c = db.connect(tmp_path / "ats.db")
    db.upsert_games(c, [
        dict(id=1, league="nfl", week=10, season=2026, start_time="2026-11-15T21:25:00.000Z", home_abbr="DAL", away_abbr="SF"),
        dict(id=2, league="nfl", week=10, season=2026, start_time="2026-11-15T14:30:00.000Z", home_abbr="DET", away_abbr="NE"),
        dict(id=3, league="nfl", week=10, season=2026, start_time="2026-11-15T21:05:00.000Z", home_abbr="ARI", away_abbr="LA"),
        dict(id=4, league="ncaaf", week=11, season=2026, start_time="2026-11-15T18:00:00.000Z", home_abbr="OU", away_abbr="MISS"),
    ], "t")
    db.upsert_picks(c, [dict(id=22, expert_id=1, game_id=2, league="nfl", market="spread", pick_side="away", created_at="2026-11-14T10:00:00Z")], "t")
    return c


def test_old_schema_migrates_without_touching_final_scores_or_lines(tmp_path):
    c = _games_db(tmp_path)
    c.execute("UPDATE games SET status='complete',away_score=20,home_score=17 WHERE id=1")
    c.execute("CREATE TABLE media_ats(game_id INTEGER,league TEXT,expert TEXT,source TEXT,pick_team TEXT,line REAL,source_url TEXT,fetched_at TEXT,PRIMARY KEY(game_id,expert))")
    c.executemany("INSERT INTO media_ats VALUES (?,?,?,?,?,?,?,?)", [
        (1,"nfl","Pete Prisco","CBS Sports","SF",-3.0,URL,"2026-11-14T12:00:00Z"),
        (1,"nfl","PetePrisco","CBS Sports","SF",-3.5,URL,"2026-11-14T13:00:00Z"),
    ])
    ats._schema(c)
    assert tuple(c.execute("SELECT status,away_score,home_score FROM games WHERE id=1").fetchone()) == ("complete",20,17)
    rows=list(c.execute("SELECT expert_key,line FROM media_ats"))
    assert len(rows)==1 and tuple(rows[0])==("peteprisco",-3.5)
    assert set(ats.ATS_COLS).issubset({r[1] for r in c.execute("PRAGMA table_info(media_ats)")})


def test_schema_handles_existing_unique_index_with_stale_swapped_keys(tmp_path):
    c=_games_db(tmp_path);ats._schema(c)
    c.execute("INSERT INTO media_ats(game_id,expert,expert_key,source,fetched_at) VALUES (1,'Pete Prisco','jareddubin','CBS Sports','2026-11-14T12:00:00Z')")
    c.execute("INSERT INTO media_ats(game_id,expert,expert_key,source,fetched_at) VALUES (1,'Jared Dubin','peteprisco','CBS Sports','2026-11-14T13:00:00Z')")
    ats._schema(c)
    assert dict(c.execute("SELECT expert,expert_key FROM media_ats"))=={"Pete Prisco":"peteprisco","Jared Dubin":"jareddubin"}


def test_read_only_old_table_loads_without_migration(tmp_path):
    c=_games_db(tmp_path)
    c.execute("CREATE TABLE media_ats(game_id INTEGER,league TEXT,expert TEXT,source TEXT,pick_team TEXT,line REAL,source_url TEXT,fetched_at TEXT,PRIMARY KEY(game_id,expert))")
    c.execute("INSERT INTO media_ats VALUES (1,'nfl','Pete Prisco','CBS Sports','SF',-3.5,?,'2026-11-14T13:00:00Z')",(URL,));c.commit();c.close()
    c=sqlite3.connect(f"file:{(tmp_path/'ats.db').as_posix()}?mode=ro",uri=True);c.row_factory=sqlite3.Row
    out=ats.load_ats(c,pd.DataFrame([dict(game_id=1)]),NOW)
    assert len(out)==1 and out.iloc[0].expert_key=='peteprisco'
    assert 'published_at' not in {r[1] for r in c.execute('PRAGMA table_info(media_ats)')}


def test_canonical_expert_dedup_keeps_native_source_and_latest_line(tmp_path):
    c=_games_db(tmp_path)
    original=_article(expert='Chris Vasile',source_url='https://www.covers.com/nfl/picks-against-the-spread-week-10-2026')
    assert ats.add_verified_ats(c,[original],NOW)==1
    duplicate=dict(original,expert='ChrisVasile',line=4.0,source_url='https://www.nbcsports.com/betting/nfl/news/reprint',modified_at='2026-11-15T15:00:00Z')
    assert ats.add_verified_ats(c,[duplicate],NOW)==0
    newer=dict(original,line=4.5,modified_at='2026-11-15T15:30:00Z')
    assert ats.add_verified_ats(c,[newer],NOW)==1
    rows=list(c.execute('SELECT expert_key,source,line FROM media_ats'))
    assert len(rows)==1 and tuple(rows[0])==('chrisvasile','Covers',4.5)


def test_unchanged_pick_retains_first_observed_timestamp(tmp_path):
    c=_games_db(tmp_path)
    assert ats.add_verified_ats(c,[_article()],NOW)==1
    assert ats.add_verified_ats(c,[_article()],"2026-11-15T16:15:00Z")==1
    assert c.execute('SELECT fetched_at FROM media_ats').fetchone()[0]==NOW


def test_article_after_kickoff_requires_pregame_publication_and_revision_and_is_labelled(tmp_path):
    c=_games_db(tmp_path)
    valid=_article(game_id=2,pick_code='NE',line=3,team_codes=['NE','DET'])
    assert ats.add_verified_ats(c,[valid],NOW)==1
    row=dict(c.execute('SELECT * FROM media_ats').fetchone())
    assert row['fetched_at']==NOW and row['source_note']=='Đọc sau giờ bắt đầu'
    for field in ('published_at','modified_at'):
        invalid=dict(valid,expert='Other Expert',**{field:'2026-11-15T15:00:00Z'})
        assert ats.add_verified_ats(c,[invalid],NOW)==0


def test_wrong_market_source_team_or_invalid_line_is_not_stored(tmp_path):
    c=_games_db(tmp_path)
    for change in [dict(market='winner'),dict(market='total'),dict(source_url='https://covers.com.evil.test/nfl/picks'),
                   dict(source_url=URL.replace('against-the-spread','straight-up')),dict(source_url=URL.replace('/10/','/9/')),
                   dict(source_url='http://www.covers.com/nfl/picks'),dict(pick_code='BUF'),dict(line=float('nan')),
                   dict(line=float('inf')),dict(line=-110),dict(expert='SBD AI Model'),dict(published_at=None),
                   dict(league='ncaaf'),dict(week=9),dict(season=2025),dict(team_codes=['SF','BUF'])]:
        assert ats.add_verified_ats(c,[_article(**change)],NOW)==0
    assert c.execute('SELECT count(*) FROM media_ats').fetchone()[0]==0


def test_matching_requires_exact_league_season_week_pair_and_explicit_orientation(tmp_path):
    c=_games_db(tmp_path);games=[dict(r) for r in c.execute('SELECT * FROM games')]
    assert ats._game_for(_article(),games)['id']==1
    for change in [dict(league='ncaaf'),dict(week=9),dict(season=2025),dict(team_codes=['SF','BUF']),dict(event_date='bad'),
                   dict(away_code='DAL',home_code='SF')]:
        assert ats._game_for(_article(**change),games) is None
    assert ats._game_for(_article(game_id=3,team_codes=['LAR','ARI']),games)['id']==3
    assert ats.add_verified_ats(c,[_article(game_id=3,pick_code='LAR',team_codes=['LAR','ARI'])],NOW)==1
    assert c.execute('SELECT pick_team FROM media_ats WHERE game_id=3').fetchone()[0]=='LA'


def test_january_cbs_records_use_prior_season_year(tmp_path):
    c=_games_db(tmp_path)
    db.upsert_games(c,[dict(id=5,league='nfl',season=2026,week=18,start_time='2027-01-03T18:00:00Z',away_abbr='SF',home_abbr='DAL')],'t')
    page=_page([('20270103','SF','DAL',_done('DAL','+3')+_done('SF','-3'))])
    records=ats.parse_cbs_ats(page,'nfl',URL.replace('/10/','/18/'))
    assert records[0]['season']==2026
    assert ats._game_for(records[0],[dict(r) for r in c.execute('SELECT * FROM games')])['id']==5


def test_source_failures_cache_and_new_board_scope_are_independent(tmp_path,monkeypatch):
    from actions_tracker import media_ats_articles as articles
    c=_games_db(tmp_path);calls=[]
    art='https://www.covers.com/nfl/picks-against-the-spread-week-10-2026'
    hub='https://www.covers.com/nfl/picks'
    monkeypatch.setattr(articles,'candidate_urls',lambda *a:[art])
    monkeypatch.setattr(articles,'source_hubs',lambda *a:[hub])
    monkeypatch.setattr(articles,'discover_urls',lambda *a:[])
    monkeypatch.setattr(articles,'parse_article',lambda *a:[_article(expert='Chris Vasile',source_url=art)])
    def get(url):
        calls.append(url)
        if url==hub:raise OSError('publisher temporarily unavailable')
        return PAGE if url==URL else '<article>picks</article>'
    board=pd.DataFrame([dict(game_id=1)])
    assert ats.refresh_ats(c,board,NOW,get)==5
    first=len(calls)
    assert ats.refresh_ats(c,board,NOW,get)==0 and len(calls)==first
    ats.refresh_ats(c,pd.DataFrame([dict(game_id=1),dict(game_id=3)]),NOW,get)
    assert len(calls)>first
    assert c.execute("SELECT count(*) FROM media_ats WHERE source='Covers'").fetchone()[0]==1
