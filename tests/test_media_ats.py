"""CBS expert picks against the spread: parsed from the week table, matched to board games, kept per expert."""

import json

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
    assert calls == [URL]
    df = ats.load_ats(c, board, NOW).set_index(["game_id", "expert"])
    assert df.loc[(1, "Pete Prisco"), "pick_team"] == "DAL" and df.loc[(1, "Jared Dubin"), "line"] == -3.5
    assert df.loc[(2, "Pete Prisco"), "pick_team"] == "DET"      # started game kept (CBS locks picks at kickoff)
    assert ats.refresh_ats(c, board, NOW, lambda url: calls.append(url) or PAGE) == 0 and len(calls) == 1  # hourly
