"""BetMGM's public sportsbook feed for exact NCAAF first/second-half markets.

This is the same unauthenticated read feed used by BetMGM's public Illinois site.  ESPN remains the
score/clock source; BetMGM is only a fallback for half markets that ESPN does not publish for NCAAF.
Failures deliberately return no data so a sportsbook outage can never stop score collection.
"""

from __future__ import annotations

import base64
import difflib
import re
from typing import Callable

import pandas as pd

from actions_tracker.matching import normalize


_HOST = "https://www.il.betmgm.com/cds-api/bettingoffer"
# Public site identifier used by BetMGM's browser client; it is not a user/account credential.
_PUBLIC_SITE_ID = "e88aa018-e9ac-41dd-b3af-f33829d14279"
_LEAGUE = {"ncaaf": (11, 211)}
HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) actions-tracker/1.0", "Accept": "application/json"}


def _access_id() -> str:
    return base64.b64encode(_PUBLIC_SITE_ID.encode()).decode()


def _params(**extra) -> dict:
    return {
        "x-bwin-accessid": _access_id(), "lang": "en-us", "country": "US", "userCountry": "US",
        "subdivision": "US-Illinois", "offerMapping": "Filtered", "scoreboardMode": "Full",
        "state": "Latest", "supportVirtual": "false", "useRegionalisedConfiguration": "true",
    } | extra


def _json(get: Callable, url: str, params: dict) -> dict | None:
    try:
        response = get(url, params=params, timeout=30, headers=HEADERS)
        if getattr(response, "status_code", None) != 200:
            return None
        body = response.json()
        return body if isinstance(body, dict) else None
    except Exception:  # noqa: BLE001 - sportsbook fallback must never stop ESPN score collection
        return None


def fixture_index(get: Callable, league: str) -> list[dict]:
    """Small normalized fixture list used to match local games before requesting one detailed board."""
    if league not in _LEAGUE:
        return []
    sport, competition = _LEAGUE[league]
    body = _json(get, f"{_HOST}/fixtures", _params(
        sportIds=str(sport), competitionIds=str(competition), fixtureTypes="Standard", skip=0, take=200,
        sortBy="Tags", offerCategories="Gridable",
    ))
    out = []
    for fixture in (body or {}).get("fixtures", []):
        if not isinstance(fixture, dict):
            continue
        name = str(((fixture.get("name") or {}).get("value")) or "")
        teams = re.split(r"\s+@\s+", name, maxsplit=1)
        if len(teams) != 2 or not fixture.get("id"):
            continue
        out.append({"event_id": str(fixture["id"]), "commence_time": fixture.get("startDate"),
                    "away_name": teams[0].strip(), "home_name": teams[1].strip()})
    return out


def _similar(left: str | None, right: str | None) -> float:
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    if ta <= tb or tb <= ta:
        return 0.95
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_fixtures(games: list[dict], fixtures: list[dict]) -> dict[int, dict]:
    """Match school-only BetMGM names to full ESPN/Action names within three hours."""
    candidates = []
    for game in games:
        for fixture in fixtures:
            try:
                hours = abs((pd.Timestamp(game["start_time"]) - pd.Timestamp(fixture["commence_time"])).total_seconds()) / 3600
            except (TypeError, ValueError):
                continue
            away = _similar(game.get("away_name"), fixture.get("away_name"))
            home = _similar(game.get("home_name"), fixture.get("home_name"))
            if hours <= 3 and min(away, home) >= 0.55 and away + home >= 1.25:
                candidates.append((away + home - hours / 20, int(game["id"]), fixture))
    out, used_games, used_events = {}, set(), set()
    for _, game_id, fixture in sorted(candidates, key=lambda item: item[0], reverse=True):
        if game_id in used_games or fixture["event_id"] in used_events:
            continue
        out[game_id] = fixture
        used_games.add(game_id)
        used_events.add(fixture["event_id"])
    return out


def fixture_board(get: Callable, fixture_id: str) -> dict | None:
    body = _json(get, f"{_HOST}/fixture-view", _params(
        fixtureIds=fixture_id, offerMapping="All", includePrecreatedBetBuilder="false",
        includeRelatedFixtures="false", statisticsModes="All",
    ))
    fixture = (body or {}).get("fixture")
    return fixture if isinstance(fixture, dict) else None


def _value(option: dict) -> float | None:
    text = str(((option.get("name") or {}).get("value")) or "")
    match = re.search(r"(?:^|\s)([+-]?\d+(?:\.\d+)?)\s*$", text)
    return float(match.group(1)) if match else None


def _balanced(market: dict) -> float:
    prices = [((option.get("price") or {}).get("americanOdds")) for option in market.get("options", [])]
    if len(prices) < 2 or any(not isinstance(price, (int, float)) for price in prices[:2]):
        return float("inf")
    return sum(abs(abs(float(price)) - 110) for price in prices[:2])


def _main(markets: list[dict], name_pattern: str) -> dict | None:
    found = [market for market in markets if isinstance(market, dict) and market.get("status") == "Visible"
             and re.fullmatch(name_pattern, str(((market.get("name") or {}).get("value")) or ""), re.I)]
    return min(found, key=_balanced) if found else None


def _spread_sides(fixture: dict, options: list[dict]) -> tuple[float | None, float | None]:
    name = str(((fixture.get("name") or {}).get("value")) or "")
    teams = re.split(r"\s+@\s+", name, maxsplit=1)
    away_name, home_name = (teams[0], teams[1]) if len(teams) == 2 else (None, None)
    found = {"away": None, "home": None}
    for option in options:
        text = str(((option.get("name") or {}).get("value")) or "")
        team = re.sub(r"\s+[+-]?\d+(?:\.\d+)?\s*$", "", text)
        scores = {"away": _similar(team, away_name), "home": _similar(team, home_name)}
        side = max(scores, key=scores.get)
        if scores[side] >= 0.55:
            found[side] = _value(option)
    # BetMGM currently orders away/home. Keep that safe fallback for a fixture missing its display name.
    if len(options) >= 2 and found["away"] is None and found["home"] is None:
        found["away"], found["home"] = _value(options[0]), _value(options[1])
    return found["away"], found["home"]


def parse_half_markets(fixture: dict | None, half: str) -> dict:
    """Return the main spread/total for ``1st`` or ``2nd`` half, never an alternate line."""
    out = {"away": None, "home": None, "total": None}
    markets = (fixture or {}).get("optionMarkets", [])
    spread = _main(markets, fr"{half}\s+half\s*(?:[-:]\s*)?spread")
    total = _main(markets, fr"{half}\s+half\s*(?:[-:]\s*)?totals?")
    if spread:
        options = [option for option in spread.get("options", []) if option.get("status") == "Visible"]
        if len(options) >= 2:
            out["away"], out["home"] = _spread_sides(fixture or {}, options)
    if total:
        options = [option for option in total.get("options", []) if option.get("status") == "Visible"]
        if options:
            out["total"] = _value(options[0])
    if out["away"] is None and out["home"] is not None:
        out["away"] = -out["home"]
    if out["home"] is None and out["away"] is not None:
        out["home"] = -out["away"]
    return out


def half_lines(get: Callable, league: str, games: list[dict], half: str) -> dict[int, dict]:
    """Exact half markets per local game; one index request plus one small request per matched game."""
    matched = match_fixtures(games, fixture_index(get, league))
    return {game_id: parse_half_markets(fixture_board(get, fixture["event_id"]), half)
            for game_id, fixture in matched.items()}
