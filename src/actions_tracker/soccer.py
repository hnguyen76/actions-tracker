"""Soccer from ESPN's public scoreboards: fixtures, DraftKings lines and the 90-minute score.

Soccer bets are graded on the score after 90 minutes plus stoppage time: extra-time goals and penalty shootouts do
not count. ESPN's final score includes extra time, so for a game decided after 90 minutes the score is rebuilt from
its goal list (each goal carries its minute; own goals are credited to the team that benefits, shootout kicks are
flagged). Lines are DraftKings' (through ESPN): moneyline with the draw (1X2), spread (Asian handicap, quarter lines
split in two halves) and total goals, each with its opening and closing number.

The owner's method (like NFL): Monday-Friday US/Eastern follow the experts' majority side in every market, the draw
included, once that side has at least two experts; Saturday-Sunday fade the spread majority when at least five
experts picked the spread (moneyline and totals are not faded).
"""

import re

import pandas as pd

from actions_tracker.config import TZ

COMPS = {
    "eng.1": "Premier League", "uefa.champions": "Champions League", "uefa.europa": "Europa League",
    "esp.1": "La Liga", "ita.1": "Serie A", "ger.1": "Bundesliga", "fra.1": "Ligue 1", "usa.1": "MLS",
}
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/{comp}/scoreboard?dates={d}"
AFTER_90 = {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}     # decided in extra time or on penalties
WEEKDAY_VOTES = 2                                       # Mon-Fri: experts on the majority side
WEEKEND_PICKS = 5                                       # Sat-Sun: experts on the spread in all
_OTHER = {"home": "away", "away": "home"}


def _int(value):
    try:
        return int(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _num(value):
    try:
        return float(str(value).lstrip("ou").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _minute(display) -> int | None:
    """ "90'+3'" -> 90 (stoppage time of the second half), "114'" -> 114."""
    m = re.match(r"\s*(\d+)", str(display or ""))
    return int(m.group(1)) if m else None


def score_90(competition: dict, status: str) -> tuple[int, int] | None:
    """(home, away) after 90 minutes, or None while the game is not final or its goal list is missing."""
    teams = {c.get("homeAway"): c for c in competition.get("competitors") or []}
    if "home" not in teams or "away" not in teams:
        return None
    home, away = _int(teams["home"].get("score")), _int(teams["away"].get("score"))
    if status not in AFTER_90:
        return (home, away) if home is not None and away is not None else None
    details = competition.get("details")
    if not isinstance(details, list):
        return None
    ids = {str(teams["home"].get("team", {}).get("id")): 0, str(teams["away"].get("team", {}).get("id")): 1}
    goals = [0, 0]
    for play in details:
        if not play.get("scoringPlay") or play.get("shootout"):
            continue
        minute, side = _minute((play.get("clock") or {}).get("displayValue")), ids.get(str((play.get("team") or {}).get("id")))
        if minute is not None and minute <= 90 and side is not None:
            goals[side] += 1
    return goals[0], goals[1]


def parse_odds(odds: list) -> dict:
    """DraftKings 1X2 / spread / total with opening and closing numbers (empty when ESPN has no line)."""
    items = [o for o in odds or [] if isinstance(o, dict)]
    dk = next((o for o in items if re.search(r"draftkings", str((o.get("provider") or {}).get("name") or ""), re.I)),
              items[0] if items else None)
    if not isinstance(dk, dict):
        return {}
    out = {}
    ml = dk.get("moneyline") or {}
    out["ml"] = {side: {when: _int((ml.get(side) or {}).get(when, {}).get("odds")) for when in ("open", "close")}
                 for side in ("home", "draw", "away") if ml.get(side)}
    for market, key, sides in (("spread", "pointSpread", ("home", "away")), ("total", "total", ("over", "under"))):
        block = dk.get(key) or {}
        out[market] = {side: {when: {"line": _num((block.get(side) or {}).get(when, {}).get("line")),
                                     "odds": _int((block.get(side) or {}).get(when, {}).get("odds"))}
                              for when in ("open", "close")} for side in sides if block.get(side)}
    return {k: v for k, v in out.items() if v}


def parse_events(data: dict, comp: str) -> list[dict]:
    out = []
    for e in (data or {}).get("events", []):
        competition = (e.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in competition.get("competitors") or []}
        if "home" not in teams or "away" not in teams:
            continue
        status = (e.get("status") or {}).get("type") or {}
        state = {"pre": "scheduled", "in": "live", "post": "final"}.get(status.get("state"), "scheduled")
        name = status.get("name") or ""
        out.append({
            "event_id": str(e.get("id")), "comp": comp, "short": e.get("shortName"), "start_time": e.get("date"),
            "state": state, "status": name, "detail": status.get("shortDetail"),
            "home_name": teams["home"]["team"].get("displayName"), "away_name": teams["away"]["team"].get("displayName"),
            "home_abbr": teams["home"]["team"].get("abbreviation"), "away_abbr": teams["away"]["team"].get("abbreviation"),
            "home_score": _int(teams["home"].get("score")), "away_score": _int(teams["away"].get("score")),
            "score_90": score_90(competition, name) if state == "final" else None,
            "odds": parse_odds(competition.get("odds")),
        })
    return out


def _single(market: str, side: str, line: float | None, home: int, away: int) -> str:
    if market == "ml":
        diff = home - away
        return "win" if (diff > 0 and side == "home") or (diff < 0 and side == "away") or (diff == 0 and side == "draw") \
            else "loss"
    if market == "spread":
        own = (home - away) if side == "home" else (away - home)
        value = own + line
    else:
        value = (home + away - line) if side == "over" else (line - home - away)
    return "win" if value > 0 else "loss" if value < 0 else "push"


def grade(market: str, side: str, line: float | None, home: int, away: int) -> str:
    """win / loss / push on the 90-minute score; a quarter line (x.25 / x.75) is two half bets on the lines
    either side of it: half_win (a win and a push) or half_loss (a loss and a push)."""
    if market != "ml" and line is not None and (abs(line) * 4) % 2 == 1:
        a, b = _single(market, side, line - 0.25, home, away), _single(market, side, line + 0.25, home, away)
        if a == b:
            return a
        pair = {a, b}
        return "half_win" if pair == {"win", "push"} else "half_loss" if pair == {"loss", "push"} else "push"
    return _single(market, side, line, home, away)


def method_plays(groups: list[dict]) -> list[dict]:
    """groups: one row per game x market with the majority side (no tie): game_id, start_time, market, side, votes,
    total_votes. Returns the plays the owner's method makes, with method / bet_side / ET date and day group."""
    plays = []
    for g in groups:
        local = pd.Timestamp(g["start_time"]).tz_convert(TZ)
        weekday = local.day_of_week <= 4
        if weekday:
            if int(g["votes"]) < WEEKDAY_VOTES:
                continue
            method, bet = "follow", g["side"]
        else:
            if g["market"] != "spread" or int(g["total_votes"]) < WEEKEND_PICKS or g["side"] not in _OTHER:
                continue
            method, bet = "fade", _OTHER[g["side"]]
        plays.append({**g, "method": method, "bet_side": bet, "et_date": local.strftime("%Y-%m-%d"),
                      "day_group": "T2-6" if weekday else "T7-CN"})
    return plays
