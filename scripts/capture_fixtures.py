"""Download real Action Network pages and save trimmed copies as test fixtures.

Usage: python scripts/capture_fixtures.py nfl ncaaf nba
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
PICKS_URL = "https://www.actionnetwork.com/{league}/picks"
SCOREBOARD_URL = "https://api.actionnetwork.com/web/v2/scoreboard/{league}?bookIds=15"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main(leagues: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA
    for league in leagues:
        html = session.get(PICKS_URL.format(league=league), timeout=30).text
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            raise SystemExit(f"{league}: __NEXT_DATA__ not found")
        experts = json.loads(m.group(1))["props"]["pageProps"]["initialExpertsResponse"]
        data = {"props": {"pageProps": {"initialExpertsResponse": experts}}}
        trimmed = (
            '<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data, separators=(",", ":"))
            + "</script></body></html>"
        )
        (OUT / f"{league}_picks.html").write_text(trimmed, encoding="utf-8")
        time.sleep(3)
        sb = session.get(SCOREBOARD_URL.format(league=league), timeout=30).json()
        (OUT / f"{league}_scoreboard.json").write_text(json.dumps(sb, separators=(",", ":")), encoding="utf-8")
        print(f"{league}: picks {len(trimmed):,} bytes, scoreboard {len(sb.get('games', []))} games")
        time.sleep(3)


if __name__ == "__main__":
    main(sys.argv[1:])
