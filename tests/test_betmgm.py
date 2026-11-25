from actions_tracker import betmgm


def option(name, odds=-110):
    return {"status": "Visible", "name": {"value": name}, "price": {"americanOdds": odds}}


def market(name, *options):
    return {"status": "Visible", "name": {"value": name}, "options": list(options)}


def test_parse_half_markets_selects_balanced_main_line_not_alternates():
    fixture = {"name": {"value": "Kent State @ Eastern Michigan"}, "optionMarkets": [
        market("1st half spread", option("Kent State +1.5", 155), option("Eastern Michigan -1.5", -210)),
        market("1st half spread", option("Kent State +3.5", -108), option("Eastern Michigan -3.5", -112)),
        market("1st half totals", option("Over 24.5", -105), option("Under 24.5", -125)),
        market("1st half totals", option("Over 23.5", -145), option("Under 23.5", 110)),
    ]}
    assert betmgm.parse_half_markets(fixture, "1st") == {"away": 3.5, "home": -3.5, "total": 24.5}


def test_parse_exact_second_half_and_ignore_full_game_live_markets():
    fixture = {"name": {"value": "Miami (OH) @ Western Michigan"}, "optionMarkets": [
        market("Spread", option("Miami (OH) -2.5"), option("Western Michigan +2.5")),
        market("Totals", option("Over 49.5"), option("Under 49.5")),
        market("2nd Half - Spread", option("Western Michigan +3.5", -108), option("Miami (OH) -3.5", -112)),
        market("2nd Half Totals", option("Over 25.5", -110), option("Under 25.5", -110)),
    ]}
    assert betmgm.parse_half_markets(fixture, "2nd") == {"away": -3.5, "home": 3.5, "total": 25.5}


def test_match_school_only_names_to_full_team_names_without_swapping_games():
    games = [
        {"id": 1, "start_time": "2026-11-25T00:00:00Z", "away_name": "Kent State Golden Flashes",
         "home_name": "Eastern Michigan Eagles"},
        {"id": 2, "start_time": "2026-11-25T00:05:00Z", "away_name": "Miami (OH) RedHawks",
         "home_name": "Western Michigan Broncos"},
    ]
    fixtures = [
        {"event_id": "6:49894", "commence_time": "2026-11-25T00:05:00Z", "away_name": "Miami (OH)",
         "home_name": "Western Michigan"},
        {"event_id": "6:49895", "commence_time": "2026-11-25T00:02:00Z", "away_name": "Kent State",
         "home_name": "Eastern Michigan"},
    ]
    matched = betmgm.match_fixtures(games, fixtures)
    assert matched[1]["event_id"] == "6:49895"
    assert matched[2]["event_id"] == "6:49894"


def test_feed_failure_is_empty_and_never_raises():
    def broken(*args, **kwargs):
        raise TimeoutError

    assert betmgm.fixture_index(broken, "ncaaf") == []
    assert betmgm.half_lines(broken, "ncaaf", [], "2nd") == {}
