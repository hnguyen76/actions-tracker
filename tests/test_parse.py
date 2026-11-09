import json
import pathlib

import pytest

from actions_tracker.config import KEEP_TYPES
from actions_tracker.parse import ParseError, extract_next_data, parse_picks_page, parse_scoreboard

F = pathlib.Path(__file__).parent / "fixtures"


def test_mini_page_maps_and_filters():
    p = parse_picks_page((F / "mini_picks.html").read_text("utf-8"), "nfl")
    assert {e["id"] for e in p.experts} == {1, 2}
    assert [(x["id"], x["market"], x["pick_side"], x["line"], x["an_result"]) for x in p.picks] == [
        (11, "spread", "home", -3.5, "win"),
        (12, "ml", "away", None, None),
    ]
    g = {x["id"]: x for x in p.games}[100]
    assert (g["home_abbr"], g["away_abbr"], g["home_score"], g["away_score"], g["status"]) == (
        "HOM", "AWY", 24, 17, "complete")


@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_real_page_counts_match_raw(league):
    html = (F / f"{league}_picks.html").read_text("utf-8")
    raw = extract_next_data(html)["props"]["pageProps"]["initialExpertsResponse"]["response"]["profiles"]
    expected = sum(
        1
        for pr in raw
        for k in (pr.get("picks") or [])
        if k["type"] in KEEP_TYPES and k["period"] == "game" and not k.get("player_id")
    )
    p = parse_picks_page(html, league)
    assert len(p.picks) == expected and len(p.experts) == len(raw)
    assert all(x["league"] == league for x in p.picks)


@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_real_scoreboard(league):
    s = parse_scoreboard(json.loads((F / f"{league}_scoreboard.json").read_text("utf-8")), league)
    assert s.games and s.lines
    assert {l["market"] for l in s.lines} <= {"spread", "ml", "total"}
    assert {l["side"] for l in s.lines} <= {"home", "away", "over", "under"}
    assert all(l["line"] is None for l in s.lines if l["market"] == "ml")


def test_empty_offseason_is_valid():
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"initialExpertsResponse":{"response":{"profiles":[]}}}}}</script>')
    p = parse_picks_page(html, "mlb")
    assert p.picks == [] and p.experts == []
    assert parse_scoreboard({"games": []}, "mlb").games == []


def test_structure_change_raises():
    with pytest.raises(ParseError):
        parse_picks_page("<html>no data</html>", "nfl")
    with pytest.raises(ParseError):
        parse_picks_page('<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{}}}</script>', "nfl")
    with pytest.raises(ParseError):
        parse_scoreboard({"error": "x"}, "nfl")
