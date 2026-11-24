import json

from actions_tracker import db
from actions_tracker.playoffs import (NFL_SIMS, _save, load_playoff_tables, ncaaf_projection,
                                      nfl_projection, parse_ncaaf_standings, parse_nfl_standings)

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
