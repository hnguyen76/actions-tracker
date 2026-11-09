import json
import pathlib

import pytest

from actions_tracker.matching import match_events, normalize
from actions_tracker.odds_api import parse_scores

F = pathlib.Path(__file__).parent / "fixtures"


def _an_games(league):
    sb = json.loads((F / f"{league}_scoreboard.json").read_text("utf-8"))
    out = []
    for g in sb["games"]:
        names = {t["id"]: t["full_name"] for t in g["teams"]}
        out.append({"id": g["id"], "start_time": g["start_time"],
                    "home_name": names.get(g["home_team_id"]), "away_name": names.get(g["away_team_id"])})
    return out


def _events(league):
    return parse_scores(json.loads((F / f"odds_{league}_scores.json").read_text("utf-8")))


def _ev(eid, home, away, t="2026-11-08T18:00:00.000Z"):
    return {"event_id": eid, "commence_time": t, "home_name": home, "away_name": away}


def _g(gid, home, away, t="2026-11-08T18:00:00.000Z"):
    return {"id": gid, "start_time": t, "home_name": home, "away_name": away}


def test_normalize():
    assert normalize("Louisiana Ragin' Cajuns") == normalize("Louisiana Ragin Cajuns")
    assert normalize("UL-Monroe Warhawks") == normalize("UL Monroe Warhawks")
    assert normalize("Texas A&M Aggies") == "texas a and m aggies"


@pytest.mark.parametrize("league", ["nfl", "nba", "ncaaf"])
def test_real_fixtures_match_every_overlapping_game(league):
    games, events = _an_games(league), _events(league)
    m = match_events(games, events)
    # every AN game whose exact (home, away) pair appears in the odds fixture must be matched to that event
    by_pair = {(e["home_name"], e["away_name"]): e for e in events}
    for g in games:
        e = by_pair.get((g["home_name"], g["away_name"]))
        if e is not None:
            assert m[g["id"]]["event_id"] == e["event_id"]
    assert len(set(e["event_id"] for e in m.values())) == len(m)  # no event used twice


@pytest.mark.parametrize("an_name,odds_name", [
    ("Delaware Fightin Blue Hens", "Delaware Blue Hens"),
    ("Hawai'i Warriors", "Hawaii Rainbow Warriors"),
    ("Miami (FL) Hurricanes", "Miami Hurricanes"),
    ("North Carolina State Wolfpack", "NC State Wolfpack"),
    ("Southern Miss Golden Eagles", "Southern Mississippi Golden Eagles"),
])
def test_ncaaf_spelling_differences(an_name, odds_name):
    m = match_events([_g(1, an_name, "Boston College Eagles")], [_ev("x", odds_name, "Boston College Eagles")])
    assert m[1]["event_id"] == "x"


def test_two_miamis_not_confused():
    games = [_g(1, "Miami (FL) Hurricanes", "Syracuse Orange")]
    events = [_ev("oh", "Miami (OH) RedHawks", "Ohio Bobcats"), _ev("fl", "Miami Hurricanes", "Syracuse Orange")]
    assert match_events(games, events)[1]["event_id"] == "fl"


def test_time_window():
    games = [_g(1, "Atlanta Falcons", "Cincinnati Bengals", "2026-11-08T18:00:00.000Z")]
    far = [_ev("a", "Atlanta Falcons", "Cincinnati Bengals", "2026-11-09T08:00:00.000Z")]
    near = [_ev("b", "Atlanta Falcons", "Cincinnati Bengals", "2026-11-08T19:00:00.000Z")]
    assert match_events(games, far) == {}
    assert match_events(games, near)[1]["event_id"] == "b"


def test_fuzzy_needs_close_time():
    games = [_g(1, "Hawai'i Warriors", "UNLV Rebels", "2026-11-08T18:00:00.000Z")]
    events = [_ev("x", "Hawaii Rainbow Warriors", "UNLV Rebels", "2026-11-08T23:30:00.000Z")]  # 5.5h apart
    assert match_events([dict(games[0], home_name="Hawai'i Bows")], events) == {}
