"""Match Action Network games to The Odds API events by team names and kickoff time (spec §12.2)."""

import difflib
import re

import pandas as pd

EXACT_WINDOW_H = 12
FUZZY_WINDOW_H = 3
FUZZY_MIN = 0.6

# normalized Action Network name -> normalized The Odds API name (NCAAF spellings seen 2026-11-09)
ALIASES = {
    "delaware fightin blue hens": "delaware blue hens",
    "hawaii warriors": "hawaii rainbow warriors",
    "miami fl hurricanes": "miami hurricanes",
    "north carolina state wolfpack": "nc state wolfpack",
    "southern miss golden eagles": "southern mississippi golden eagles",
}


def normalize(name: str | None) -> str:
    s = (name or "").lower().replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return ALIASES.get(s, s)


def _hours(a: str | None, b: str | None) -> float:
    if not a or not b:
        return float("inf")
    return abs((pd.Timestamp(a) - pd.Timestamp(b)).total_seconds()) / 3600


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def match_events(games: list[dict], events: list[dict]) -> dict[int, dict]:
    """Return {game_id: event} — exact names within 12h first, else one exact + one similar within 3h."""
    prepared = [(e, normalize(e.get("home_name")), normalize(e.get("away_name"))) for e in events]
    used: set = set()
    out: dict[int, dict] = {}
    for g in games:
        gh, ga = normalize(g.get("home_name")), normalize(g.get("away_name"))
        if not gh or not ga:
            continue
        best, best_h = None, float("inf")
        for e, eh, ea in prepared:
            if e["event_id"] in used:
                continue
            h = _hours(g.get("start_time"), e.get("commence_time"))
            if gh == eh and ga == ea and h <= EXACT_WINDOW_H and h < best_h:
                best, best_h = e, h
        if best is None:
            for e, eh, ea in prepared:
                if e["event_id"] in used:
                    continue
                h = _hours(g.get("start_time"), e.get("commence_time"))
                if h > FUZZY_WINDOW_H or h >= best_h:
                    continue
                if (gh == eh and _similar(ga, ea) >= FUZZY_MIN) or (ga == ea and _similar(gh, eh) >= FUZZY_MIN):
                    best, best_h = e, h
        if best is not None:
            used.add(best["event_id"])
            out[g["id"]] = best
    return out
