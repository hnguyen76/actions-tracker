import json

from actions_tracker import db
from actions_tracker.playoffs import (NFL_SIMS, _save, load_playoff_tables, ncaaf_projection, pregame_playoff_table,
                                      nfl_projection, parse_nba_standings, parse_ncaaf_standings,
                                      parse_nfl_standings)
import pandas as pd

NOW = "2026-11-24T12:00:00.000Z"


def _entry(team_id, abbr, wins, losses, seed, diff=0, conf="0-0"):
    return {"team": {"id": str(team_id), "displayName": f"{abbr} Team", "abbreviation": abbr,
                     "logos": [{"href": f"https://img/{abbr}.png"}]},
            "stats": [{"name": "wins", "value": wins, "displayValue": str(wins)},
                      {"name": "losses", "value": losses, "displayValue": str(losses)},
                      {"name": "ties", "value": 0, "displayValue": "0"},
                      {"name": "playoffSeed", "value": seed, "displayValue": str(seed)},
                      {"name": "pointDifferential", "value": diff, "displayValue": str(diff)},
                      {"name": "overall", "type": "overall", "displayValue": f"{wins}-{losses}"},
                      {"name": "vs. Conf.", "type": "vsconf", "displayValue": conf}]}


def test_parse_espn_standings_keeps_nfl_divisions_and_nested_ncaaf_divisions():
    nfl = {"children": []}
    team_id = 1
    for conference in ("AFC", "NFC"):
        divisions = []
        for number in range(4):
            entries = [_entry(team_id + x, f"T{team_id+x}", 9 - x, 1 + x, number * 4 + x + 1)
                       for x in range(4)]
            team_id += 4
            divisions.append({"abbreviation": f"{conference} D{number+1}", "standings": {"entries": entries}})
        nfl["children"].append({"abbreviation": conference, "children": divisions})
    nfl_rows = parse_nfl_standings(nfl, NOW)
    assert len(nfl_rows) == 32 and nfl_rows[0]["conference"] == "AFC"
    assert nfl_rows[0]["division"] == "AFC D1" and nfl_rows[0]["record"] == "9-1"

    conferences = []
    team_id = 100
    for i in range(10):
        entries = [_entry(team_id + x, f"C{i}T{x}", 8, 2, x + 1, 40, "6-1") for x in range(11)]
        team_id += 11
        if i == 9:
            conferences.append({"shortName": "Sun Belt", "children": [
                {"shortName": "East", "standings": {"entries": entries[:6]}},
                {"shortName": "West", "standings": {"entries": entries[6:]}}]})
        else:
            conferences.append({"shortName": f"C{i}", "standings": {"entries": entries}})
    ncaaf_rows = parse_ncaaf_standings({"children": conferences}, NOW)
    assert len(ncaaf_rows) == 110
    assert {r["division"] for r in ncaaf_rows if r["conference"] == "Sun Belt"} == {"East", "West"}


def test_nba_standings_tracks_seed_movement_and_postseason_phase():
    data = {"season": {"year": 2027}, "seasons": [{"year": 2027, "types": [
        {"id": "2", "startDate": "2026-10-01T00:00Z", "endDate": "2027-04-19T00:00Z"},
        {"id": "3", "startDate": "2027-04-19T00:00Z", "endDate": "2027-06-30T00:00Z"},
    ]}], "children": []}
    team_id = 1
    for conference in ("East", "West"):
        entries = [_entry(team_id + seed - 1, f"{conference[0]}{seed}", 20 - seed, seed, seed)
                   for seed in range(1, 16)]
        data["children"].append({"abbreviation": conference, "standings": {"entries": entries}})
        team_id += 15
    rows = parse_nba_standings(data, NOW, {"1": 3, "8": 7, "11": 10})
    assert len(rows) == 30
    assert (rows[0]["bid"], rows[0]["seed_change"], rows[0]["season_type"]) == ("PLAYOFF", 2, "regular")
    assert next(r for r in rows if r["team_id"] == "8")["picture"] == "bubble"
    assert next(r for r in rows if r["team_id"] == "11")["picture"] == "outside"
    postseason = parse_nba_standings(data, "2027-05-01T12:00:00Z")
    assert all(r["season_type"] == "postseason" for r in postseason)


def test_nfl_model_uses_division_winners_then_three_wildcards():
    rows = []
    for conference in ("AFC", "NFC"):
        for division in range(4):
            for member in range(2):
                seed = division + 1 if member == 0 else 8 + division
                wins = 9 - division if member == 0 else 4
                rows.append({"league": "nfl", "team_id": f"{conference}{division}{member}",
                             "team": "Team", "abbr": f"{conference}{division}{member}", "logo": None,
                             "conference": conference, "division": f"D{division}", "record": f"{wins}-2",
                             "conf_record": "–", "wins": wins, "losses": 2, "ties": 0,
                             "point_diff": wins * 10, "seed": seed, "captured_at": NOW})
    projected = nfl_projection(rows, {"events": []}, NOW, 2026)
    assert sum(r["playoff_prob"] == 1 for r in projected if r["conference"] == "AFC") == 7
    assert {r["projected_seed"] for r in projected if r["conference"] == "AFC" and r["projected_seed"]} == set(range(1, 8))
    assert all(r["model"].startswith(f"{NFL_SIMS:,}") for r in projected)


def test_ncaaf_picture_uses_cfp_refs_and_excludes_independent_auto_bid():
    rows = []
    for i in range(1, 26):
        conference = "FBS Indep." if i == 3 else f"C{(i - 1) % 6}"
        rows.append({"league": "ncaaf", "team_id": str(i), "team": f"Team {i}", "abbr": f"T{i}",
                     "logo": None, "conference": conference, "division": "", "record": "10-1",
                     "conf_record": "7-1", "wins": 10, "losses": 1, "ties": 0,
                     "point_diff": 100 - i, "seed": 1, "captured_at": NOW})
    ranking = {"ranks": [{"current": i, "team": {
        "$ref": f"http://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/2026/teams/{i}?lang=en"}}
        for i in range(1, 26)]}
    projected = ncaaf_projection(rows, ranking)
    assert len(projected) == 25 and sum(r["picture"] == "field" for r in projected) == 12
    assert next(r for r in projected if r["team_id"] == "3")["bid"] == "AT-LARGE"
    assert sum(r["bid"] == "AUTO" for r in projected) == 5
    assert {r["projected_seed"] for r in projected if r["picture"] == "field"} == set(range(1, 13))


def test_cached_rows_survive_an_offline_site_rebuild(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    standing = {"league": "nfl", "team_id": "1", "team": "Bills", "abbr": "BUF", "logo": None,
                "conference": "AFC", "division": "East", "record": "9-1", "conf_record": "6-1",
                "wins": 9, "losses": 1, "ties": 0, "point_diff": 100, "seed": 1, "captured_at": NOW}
    playoff = {**standing, "rank": None, "playoff_prob": .98, "picture": "field", "bid": "DIV", "model": "test"}
    _save(conn, "nfl", [standing], [playoff], NOW)
    tables = load_playoff_tables(conn)
    assert tables["NFL_Playoff"].iloc[0]["playoff_prob"] == .98
    payload = conn.execute("SELECT payload FROM playoff_cache WHERE league='nfl'").fetchone()[0]
    assert json.loads(payload)["standings"][0]["abbr"] == "BUF"


def test_pregame_playoff_matches_aliases_and_keeps_unranked_ncaaf_standings():
    nfl_was = {"league": "nfl", "team_id": "28", "team": "Washington Commanders", "abbr": "WSH",
               "logo": None, "conference": "NFC", "division": "East", "record": "4-5-1",
               "conf_record": "3-4-1", "wins": 4, "losses": 5, "ties": 1, "point_diff": -25,
               "seed": 11, "captured_at": NOW}
    nfl_cin = {**nfl_was, "team_id": "4", "team": "Cincinnati Bengals", "abbr": "CIN",
               "record": "7-3", "seed": 4}
    playoff = [
        {**nfl_was, "rank": None, "playoff_prob": .18, "picture": "outside", "bid": "", "model": "test"},
        {**nfl_cin, "rank": None, "playoff_prob": .82, "picture": "field", "bid": "DIV", "model": "test"},
    ]
    ncaaf = {"league": "ncaaf", "team_id": "1", "team": "Miami Hurricanes", "abbr": "MIA",
             "logo": None, "conference": "ACC", "division": "", "record": "6-5", "conf_record": "4-4",
             "wins": 6, "losses": 5, "ties": 0, "point_diff": 10, "seed": 99, "captured_at": NOW}
    games = pd.DataFrame([
        {"id": 7, "league": "nfl", "away_abbr": "CIN", "home_abbr": "WAS",
         "away_name": "Cincinnati Bengals", "home_name": "Washington Commanders"},
        {"id": 8, "league": "ncaaf", "away_abbr": "MIA", "home_abbr": "FSU",
         "away_name": "Miami FL Hurricanes", "home_name": "Florida State Seminoles"},
    ])
    tables = {"NFL_Standings": pd.DataFrame([nfl_was, nfl_cin]), "NFL_Playoff": pd.DataFrame(playoff),
              "NCAAF_Standings": pd.DataFrame([ncaaf]), "NCAAF_Playoff": pd.DataFrame()}
    got = pregame_playoff_table(games, tables)
    was = got[(got.game_id == 7) & (got.side == "home")].iloc[0]
    mia = got[(got.game_id == 8) & (got.side == "away")].iloc[0]
    assert (was.abbr, was.seed, was.playoff_prob, was.picture) == ("WSH", 11, .18, "outside")
    assert (mia.abbr, mia.record, mia.picture) == ("MIA", "6-5", "outside")
    assert pd.isna(mia.seed)
