"""Turn Action Network picks pages and scoreboard JSON into DB row dicts (spec §3, §5)."""

import json
import re
from dataclasses import dataclass, field

from actions_tracker.config import BOOK_ID, KEEP_TYPES

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_RESULTS = {"win", "loss", "push"}
_MARKETS = {"spread": "spread", "moneyline": "ml", "total": "total"}
_SIDES = {"home", "away", "over", "under"}


class ParseError(Exception):
    """The page no longer has the structure this parser expects."""


@dataclass
class PicksPage:
    experts: list[dict] = field(default_factory=list)
    picks: list[dict] = field(default_factory=list)
    games: list[dict] = field(default_factory=list)


@dataclass
class Scoreboard:
    games: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)


def extract_next_data(html: str) -> dict:
    m = _NEXT_DATA.search(html)
    if not m:
        raise ParseError("__NEXT_DATA__ script not found")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ParseError(f"__NEXT_DATA__ is not valid JSON: {e}") from e


def _game_row(g: dict, league: str) -> dict:
    abbr = {t.get("id"): t.get("abbr") for t in g.get("teams") or []}
    box = g.get("boxscore") or {}
    return {
        "id": g["id"],
        "league": league,
        "season": g.get("season"),
        "week": g.get("week"),
        "start_time": g.get("start_time"),
        "status": g.get("status"),
        "home_team_id": g.get("home_team_id"),
        "away_team_id": g.get("away_team_id"),
        "home_abbr": abbr.get(g.get("home_team_id")),
        "away_abbr": abbr.get(g.get("away_team_id")),
        "home_score": box.get("total_home_points"),
        "away_score": box.get("total_away_points"),
    }


def _pick_row(k: dict, expert_id: int, league: str) -> dict | None:
    if k.get("type") not in KEEP_TYPES or k.get("period") != "game" or k.get("player_id"):
        return None
    market, side = KEEP_TYPES[k["type"]]
    return {
        "id": k["id"],
        "expert_id": k.get("user_id", expert_id),
        "game_id": k.get("game_id"),
        "league": league,
        "market": market,
        "pick_side": side,
        "line": None if market == "ml" else k.get("value"),
        "odds": k.get("odds"),
        "units": k.get("units"),
        "an_result": k.get("result") if k.get("result") in _RESULTS else None,
        "created_at": k.get("created_at"),
        "starts_at": k.get("starts_at"),
        "settled_at": k.get("settled_at"),
        "play_text": k.get("play"),
    }


def parse_picks_page(html: str, league: str) -> PicksPage:
    data = extract_next_data(html)
    try:
        profiles = data["props"]["pageProps"]["initialExpertsResponse"]["response"]["profiles"]
    except (KeyError, TypeError) as e:
        raise ParseError(f"expert profiles missing: {e!r}") from e
    page = PicksPage()
    games: dict[int, dict] = {}
    for pr in profiles or []:
        page.experts.append({
            "id": pr["id"],
            "name": pr.get("name"),
            "username": pr.get("username"),
            "followers": pr.get("followers"),
        })
        for k in pr.get("picks") or []:
            row = _pick_row(k, pr["id"], league)
            if row is None or row["game_id"] is None:
                continue
            page.picks.append(row)
            if isinstance(k.get("game"), dict) and k["game"].get("id") is not None:
                games[k["game"]["id"]] = _game_row(k["game"], league)
    page.games = list(games.values())
    return page


def parse_scoreboard(data: dict, league: str) -> Scoreboard:
    if not isinstance(data, dict) or "games" not in data:
        raise ParseError("scoreboard JSON has no 'games' key")
    sb = Scoreboard()
    for g in data["games"] or []:
        sb.games.append(_game_row(g, league))
        event = ((g.get("markets") or {}).get(BOOK_ID) or {}).get("event") or {}
        for key, market in _MARKETS.items():
            for o in event.get(key) or []:
                if o.get("side") not in _SIDES:
                    continue
                info = o.get("bet_info") or {}
                sb.lines.append({
                    "game_id": g["id"],
                    "market": market,
                    "side": o["side"],
                    "line": None if market == "ml" else o.get("value"),
                    "odds": o.get("odds"),
                    "tickets_pct": (info.get("tickets") or {}).get("percent"),
                    "money_pct": (info.get("money") or {}).get("percent"),
                })
    return sb
