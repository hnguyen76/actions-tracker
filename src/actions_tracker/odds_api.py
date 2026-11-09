"""The Odds API (official, keyed): final scores and pre-game lines (spec §12.1, §12.3)."""

import os
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import requests

BASE = "https://api.the-odds-api.com/v4/sports/{sport}/{kind}/"
SPORT_KEYS = {"nfl": "americanfootball_nfl", "ncaaf": "americanfootball_ncaaf", "nba": "basketball_nba"}
SCORES_PARAMS = {"daysFrom": 3, "dateFormat": "iso"}
ODDS_PARAMS = {"regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american", "dateFormat": "iso"}
BACKOFF = (2, 4, 8)
_MARKETS = {"spreads": "spread", "totals": "total", "h2h": "ml"}


class OddsApiError(Exception):
    """Request rejected (bad key, quota exhausted, bad params) or still failing after retries."""


def load_key(root: Path) -> str | None:
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if key:
        return key
    path = Path(root) / ".odds_api_key"
    if path.exists():
        return path.read_text("utf-8").strip() or None
    return None


def iso(ts: str | None) -> str | None:
    """'2026-11-08T14:35:00Z' -> '2026-11-08T14:35:00.000Z' (the format the DB compares as strings)."""
    if not ts:
        return None
    return ts[:-1] + ".000Z" if ts.endswith("Z") and "." not in ts else ts


class OddsApi:
    def __init__(self, key: str, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.key = key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.remaining: int | None = None

    def _get(self, league: str, kind: str, params: dict) -> list[dict]:
        url = BASE.format(sport=SPORT_KEYS[league], kind=kind)
        last = ""
        for attempt in range(len(BACKOFF) + 1):
            if attempt:
                self.sleep(BACKOFF[attempt - 1])
            try:
                resp = self.session.get(url, params={"apiKey": self.key, **params}, timeout=30)
            except requests.RequestException as e:
                last = type(e).__name__
                continue
            remaining = resp.headers.get("x-requests-remaining")
            if remaining is not None:
                try:
                    self.remaining = int(float(remaining))
                except ValueError:
                    pass
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                continue
            raise OddsApiError(f"The Odds API {kind}/{league}: HTTP {resp.status_code}")
        raise OddsApiError(f"The Odds API {kind}/{league}: gave up ({last})")

    def scores(self, league: str) -> list[dict]:
        return self._get(league, "scores", SCORES_PARAMS)

    def odds(self, league: str) -> list[dict]:
        return self._get(league, "odds", ODDS_PARAMS)


def parse_scores(events: list[dict]) -> list[dict]:
    rows = []
    for e in events:
        by_name = {s.get("name"): s.get("score") for s in e.get("scores") or []}
        done = bool(e.get("completed"))

        def score(name):
            v = by_name.get(name)
            try:
                return int(v) if done and v is not None else None
            except (TypeError, ValueError):
                return None

        rows.append({
            "event_id": e["id"], "commence_time": iso(e.get("commence_time")),
            "home_name": e.get("home_team"), "away_name": e.get("away_team"), "completed": done,
            "home_score": score(e.get("home_team")), "away_score": score(e.get("away_team")),
        })
    return rows


def parse_lines(events: list[dict]) -> list[dict]:
    """Median point and price per (event, market, side) across all bookmakers."""
    rows = []
    for e in events:
        home, away = e.get("home_team"), e.get("away_team")
        acc: dict[tuple[str, str], tuple[list, list]] = {}
        for book in e.get("bookmakers") or []:
            for m in book.get("markets") or []:
                market = _MARKETS.get(m.get("key"))
                if market is None:
                    continue
                for o in m.get("outcomes") or []:
                    name = o.get("name")
                    if market == "total":
                        side = {"Over": "over", "Under": "under"}.get(name)
                    else:
                        side = "home" if name == home else "away" if name == away else None
                    if side is None:
                        continue
                    points, prices = acc.setdefault((market, side), ([], []))
                    if o.get("point") is not None:
                        points.append(float(o["point"]))
                    if o.get("price") is not None:
                        prices.append(o["price"])
        for (market, side), (points, prices) in acc.items():
            rows.append({
                "event_id": e["id"], "commence_time": iso(e.get("commence_time")),
                "home_name": home, "away_name": away, "market": market, "side": side,
                "line": None if market == "ml" or not points else float(statistics.median(points)),
                "odds": int(round(statistics.median(prices))) if prices else None,
            })
    return rows
