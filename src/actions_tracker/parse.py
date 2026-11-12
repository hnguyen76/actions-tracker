"""Turn Action Network picks pages into DB row dicts (spec §3, §5, §12)."""

import json
import re
from dataclasses import dataclass, field

from actions_tracker.config import KEEP_TYPES, PUBLIC_BOOK

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_RESULTS = {"win", "loss", "push"}


class ParseError(Exception):
    """The page no longer has the structure this parser expects."""


@dataclass
class PicksPage:
    experts: list[dict] = field(default_factory=list)
    picks: list[dict] = field(default_factory=list)
    games: list[dict] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)  # expert form (streak, last-30-day record) per pick


def extract_next_data(html: str) -> dict:
    m = _NEXT_DATA.search(html)
    if not m:
        raise ParseError("__NEXT_DATA__ script not found")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ParseError(f"__NEXT_DATA__ is not valid JSON: {e}") from e


def _game_row(g: dict, league: str) -> dict:
    """Identity and kickoff only — status and scores come from The Odds API (spec §12.1)."""
    abbr = {t.get("id"): t.get("abbr") for t in g.get("teams") or []}
    name = {t.get("id"): t.get("full_name") for t in g.get("teams") or []}
    return {
        "id": g["id"],
        "league": league,
        "season": g.get("season"),
        "week": g.get("week"),
        "start_time": g.get("start_time"),
        "status": None,
        "home_team_id": g.get("home_team_id"),
        "away_team_id": g.get("away_team_id"),
        "home_abbr": abbr.get(g.get("home_team_id")),
        "away_abbr": abbr.get(g.get("away_team_id")),
        "home_score": None,
        "away_score": None,
        "home_name": name.get(g.get("home_team_id")),
        "away_name": name.get(g.get("away_team_id")),
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


def _form(pr: dict, pick: dict, league: str) -> dict:
    """The expert's form as the page shows it now: win/loss streak and the league's last-month record."""
    streak = pr.get("win_streak") if isinstance(pr.get("win_streak"), dict) else {}
    rec = pr.get("record") if isinstance(pr.get("record"), dict) else {}
    if rec.get("window") not in (None, "last_month"):
        rec = {}
    return {
        "pick_id": pick["id"],
        "expert_id": pick["expert_id"],
        "league": league,
        "streak_type": streak.get("type"),
        "streak_value": streak.get("value"),
        "units_30": rec.get("units_net"),
        "wins_30": rec.get("win"),
        "losses_30": rec.get("loss"),
        "pushes_30": rec.get("push"),
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
            page.forms.append(_form(pr, row, league))
            if isinstance(k.get("game"), dict) and k["game"].get("id") is not None:
                games[k["game"]["id"]] = _game_row(k["game"], league)
    page.games = list(games.values())
    return page


def _expert_row(pr: dict) -> dict:
    return {"id": pr["id"], "name": pr.get("name"), "username": pr.get("username"), "followers": pr.get("followers")}


def parse_bygame_page(html: str, league: str) -> PicksPage:
    """The "By Game" picks page: every game on the league's current board with each expert's picks."""
    data = extract_next_data(html)
    try:
        games = data["props"]["pageProps"]["scoreboardResponse"]["response"]["games"]
    except (KeyError, TypeError) as e:
        raise ParseError(f"by-game board missing: {e!r}") from e
    page = PicksPage()
    experts: dict[int, dict] = {}
    picks: dict[int, dict] = {}
    forms: dict[int, dict] = {}
    for g in games or []:
        if g.get("id") is None:
            continue
        page.games.append(_game_row(g, league))
        for pr in g.get("experts") or []:
            experts.setdefault(pr["id"], _expert_row(pr))
            for k in pr.get("picks") or []:
                row = _pick_row(k, pr["id"], league)
                if row is not None and row["game_id"] is not None:
                    picks[row["id"]] = row
                    forms[row["id"]] = _form(pr, row, league)
    page.experts = list(experts.values())
    page.picks = list(picks.values())
    page.forms = list(forms.values())
    return page



_PUBLIC_MARKETS = {"spread": "spread", "total": "total", "moneyline": "ml"}


def _pct(info: dict, kind: str):
    return ((info or {}).get(kind) or {}).get("percent")


def parse_public_page(html: str, league: str) -> tuple[list[dict], list[dict]]:
    """The "Public Betting" page: every game on the board with line, % of bets and % of money per side.
    Returns (games, splits). A market whose sides all show 0% has no public data yet -> percentages are None."""
    data = extract_next_data(html)
    try:
        games = data["props"]["pageProps"]["scoreboardResponse"]["games"]
    except (KeyError, TypeError) as e:
        raise ParseError(f"public betting board missing: {e!r}") from e
    rows, splits = [], []
    for g in games or []:
        if g.get("id") is None:
            continue
        rows.append(_game_row(g, league))
        event = ((g.get("markets") or {}).get(PUBLIC_BOOK) or {}).get("event") or {}
        for key, market in _PUBLIC_MARKETS.items():
            sides = [o for o in event.get(key) or [] if o.get("side") in ("home", "away", "over", "under")]
            has = {kind: sum(_pct(o.get("bet_info"), kind) or 0 for o in sides) > 0 for kind in ("tickets", "money")}
            for o in sides:
                splits.append({
                    "game_id": g["id"], "market": market, "side": o["side"],
                    "line": None if market == "ml" else o.get("value"), "odds": o.get("odds"),
                    "tickets_pct": _pct(o.get("bet_info"), "tickets") if has["tickets"] else None,
                    "money_pct": _pct(o.get("bet_info"), "money") if has["money"] else None,
                })
    return rows, splits
