"""Build a per-side history table (weeks 1..N) from By-Game week cards + Action Network weekly scoreboards.

Inputs
- cards JSON: {"Week 1": ["<card text>", ...], ...} read from the By-Game page's Week menu in a browser
  (each card: "AWY a - h HOM | ... | AWY Spread | n | HOM Spread | n | Over | n | Under | n | AWY ML | n | HOM ML | n").
- scoreboards: fetched once per week from Action Network (scores, consensus closing line, % public) and cached.

Output: data/history/<league>_sides.csv — one row per game x market x side with the number of expert picks on it,
the closing line/odds, public %, favourite/underdog, and the side's result at the closing line.

Usage:
  .venv/Scripts/python scripts/build_history.py nfl  <cards.json> <cache_dir>
  .venv/Scripts/python scripts/build_history.py ncaaf <cards.json> <cache_dir>
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from actions_tracker.config import TZ  # noqa: E402
from actions_tracker.fetch import Fetcher  # noqa: E402
from actions_tracker.grading import grade_side  # noqa: E402

SCOREBOARD = "https://api.actionnetwork.com/web/v2/scoreboard/{league}?bookIds=15&week={week}"
OPP = {"home": "away", "away": "home", "over": "under", "under": "over"}
_SCORE = re.compile(r"^(\S+) (\d+) - (\d+) (\S+)$")


def parse_card(text: str) -> dict | None:
    parts = [p.strip() for p in text.split("|")]
    score = next((p for p in parts if _SCORE.match(p)), None)
    if score is None:
        return None
    away, a_sc, h_sc, home = _SCORE.match(score).groups()

    def count(label: str) -> int:
        if label in parts:
            i = parts.index(label)
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                return int(parts[i + 1])
        return 0

    return {"away": away, "home": home, "away_score": int(a_sc), "home_score": int(h_sc),
            "counts": {("spread", "away"): count(f"{away} Spread"), ("spread", "home"): count(f"{home} Spread"),
                       ("total", "over"): count("Over"), ("total", "under"): count("Under"),
                       ("ml", "away"): count(f"{away} ML"), ("ml", "home"): count(f"{home} ML")}}


def scoreboard(fetcher: Fetcher, league: str, week: int, cache: Path) -> dict:
    path = cache / f"{league}_w{week}.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    data = fetcher.get_json(SCOREBOARD.format(league=league, week=week))
    path.write_text(json.dumps(data), "utf-8")
    return data


def build(league: str, cards_path: Path, cache: Path) -> pd.DataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    cards = json.loads(cards_path.read_text("utf-8"))
    fetcher = Fetcher()
    rows, unmatched = [], 0
    for week_label, texts in cards.items():
        week = int(week_label.split()[-1])
        board = scoreboard(fetcher, league, week, cache)
        games = {}
        for g in board.get("games", []):
            abbr = {t["id"]: t["abbr"] for t in g.get("teams") or []}
            games[(abbr.get(g["away_team_id"]), abbr.get(g["home_team_id"]))] = g
        for text in texts:
            card = parse_card(text)
            if card is None:
                continue
            g = games.get((card["away"], card["home"]))
            if g is None:
                unmatched += 1
                continue
            event = ((g.get("markets") or {}).get("15") or {}).get("event") or {}
            lines = {}
            for key, market in (("spread", "spread"), ("total", "total"), ("moneyline", "ml")):
                for o in event.get(key) or []:
                    info = o.get("bet_info") or {}
                    lines[(market, o.get("side"))] = (o.get("value"), o.get("odds"),
                                                      (info.get("tickets") or {}).get("percent"),
                                                      (info.get("money") or {}).get("percent"))
            local = pd.Timestamp(g["start_time"]).tz_convert(TZ)
            for (market, side), n in card["counts"].items():
                if (market, side) not in lines:
                    continue
                value, odds, tickets, money = lines[(market, side)]
                opp = lines.get((market, OPP[side]))
                if market == "spread":
                    fav = "favorite" if value < 0 else "underdog" if value > 0 else "pickem"
                elif market == "ml" and opp:
                    fav = "favorite" if odds < opp[1] else "underdog" if odds > opp[1] else "pickem"
                else:
                    fav = None
                rows.append({
                    "league": league, "week": week, "game_id": g["id"], "et_date": local.strftime("%Y-%m-%d"),
                    "day_group": "T2-6" if local.day_of_week <= 4 else "T7-CN",
                    "away": card["away"], "home": card["home"],
                    "away_score": card["away_score"], "home_score": card["home_score"],
                    "market": market, "side": side, "picks": n, "opp_picks": card["counts"][(market, OPP[side])],
                    "line": None if market == "ml" else value, "odds": odds, "opp_odds": opp[1] if opp else None,
                    "tickets_pct": tickets, "money_pct": money, "fav_dog": fav,
                    "result": grade_side(market, side, None if market == "ml" else value,
                                         card["home_score"], card["away_score"]),
                })
    print(f"{league}: {len(rows)} side rows from {len({r['game_id'] for r in rows})} games; unmatched cards {unmatched}")
    return pd.DataFrame(rows)


if __name__ == "__main__":
    league, cards_path, cache = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out = REPO / "data" / "history"
    out.mkdir(parents=True, exist_ok=True)
    df = build(league, cards_path, cache)
    df.to_csv(out / f"{league}_sides.csv", index=False)
    print("wrote", out / f"{league}_sides.csv")
