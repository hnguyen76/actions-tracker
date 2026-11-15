"""CBS Sports expert picks AGAINST THE SPREAD, for the decision card ("Chuyên gia chọn spread").

The straight-up winner picks live in media_picks.py; this module only reads the CBS "Against the Spread" week
tables (public pages, one per league and week), keeps each expert's side and line, and stores them in their own
table so the two markets never mix. Picks are captured before kickoff only.
"""

import json
import re
from datetime import timedelta
from urllib.parse import urlparse

import pandas as pd

from actions_tracker.media_picks import _Node, _Tree, _allowed, _code, _time, media_games

ATS_COLS = ["game_id", "league", "expert", "source", "pick_team", "line", "source_url", "fetched_at"]
_LINE = re.compile(r"^([A-Za-z&.]+)\s+(PK|pk|[+-]?\d+(?:\.\d+)?)$")


def cbs_ats_url(league: str, week: int) -> str:
    section = "nfl" if league == "nfl" else "college-football"
    return f"https://www.cbssports.com/{section}/picks/experts/against-the-spread/{week}/"


def _pick(text: str):
    m = _LINE.match(" ".join(str(text).split()))
    if not m:
        return None
    line = 0.0 if m[2].upper() == "PK" else float(m[2])
    return m[1], line


def parse_cbs_ats(text: str, league: str, source_url: str) -> list[dict]:
    """[{expert, pick_code, line, away_code, home_code, event_date, week}] from a CBS ATS week table."""
    path = urlparse(source_url).path
    section = "nfl" if league == "nfl" else "college-football" if league == "ncaaf" else ""
    route = re.fullmatch(r"/" + section + r"/picks/experts/against-the-spread/(\d+)/?", path) if section else None
    if not _allowed(source_url) or not route:
        return []
    root = _Tree(text).root
    if not any("against the spread" in h.text().lower() and "expert picks" in h.text().lower() for h in root.walk("h1")):
        return []
    tables = list(root.walk("table", "TableExpertPicks"))
    if len(tables) != 1:
        return []
    table = tables[0]
    experts = [node.text() for node in table.walk(cls="AuthorHeadshotAndName-name")]
    rows = []
    for tr in table.walk("tr", "TableBase-bodyTr"):
        cells = [c for c in tr.children if isinstance(c, _Node) and c.tag == "td"]
        if not experts or len(cells) != len(experts) + 1:
            continue
        links = list(cells[0].walk("a", "GameMatchup"))
        match = re.search(r"/(NFL|NCAAF)_(\d{8})_([^@/]+)@([^/]+)/", links[0].attrs.get("href", "")) if links else None
        if not match or match[1] != ("NFL" if league == "nfl" else "NCAAF"):
            continue
        away, home = match[3], match[4]
        for expert, cell in zip(experts, cells[1:]):
            picked = None
            done = list(cell.walk("p", "TableExpertPicks-pick"))  # finished game: "NYG -2.5"
            if len(done) == 1:
                picked = _pick(done[0].text())
            else:  # upcoming game: a disabled bet button with the market name and the expert's label
                buttons = list(cell.walk("button", "BetButton"))
                try:
                    config = json.loads(buttons[0].attrs.get("data-config", "")) if len(buttons) == 1 else {}
                except (ValueError, TypeError):
                    config = {}
                labels = [b.get("expertLabel") for b in config.get("meta", {}).get("bets", [])]
                if config.get("marketName") == "Spread" and labels == [expert]:
                    texts = [n.text() for n in buttons[0].walk(cls="BetButton-text")]
                    picked = _pick(texts[0]) if len(texts) == 1 else None
            if not picked or _code(picked[0]) not in {_code(away), _code(home)}:
                continue
            rows.append(dict(league=league, expert=" ".join(expert.split()), pick_code=picked[0], line=picked[1],
                             away_code=away, home_code=home, event_date=f"{match[2][:4]}-{match[2][4:6]}-{match[2][6:]}",
                             week=int(route[1]), source="CBS Sports", source_url=source_url))
    return rows


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS media_ats(
        game_id INTEGER, league TEXT, expert TEXT, source TEXT, pick_team TEXT, line REAL, source_url TEXT,
        fetched_at TEXT, PRIMARY KEY(game_id, expert))""")
    conn.execute("CREATE TABLE IF NOT EXISTS media_ats_refresh(url TEXT PRIMARY KEY, attempted_at TEXT, error TEXT)")


def _game_for(record, games):
    """The board game this CBS row describes (same date in US/Eastern, both team codes)."""
    want = {_code(record["away_code"]), _code(record["home_code"])}
    out = []
    for g in games:
        if g["league"] != record["league"]:
            continue
        day = _time(g["start_time"]).tz_convert("America/New_York").normalize().tz_localize(None)
        # within two days: CBS keeps the original date when a game is moved (e.g. Saturday -> Sunday)
        close = abs((day - pd.Timestamp(record["event_date"])).days) <= 2
        if close and {_code(g["away_abbr"]), _code(g["home_abbr"])} == want:
            out.append(g)
    return out[0] if len(out) == 1 else None


def refresh_ats(conn, board, now, fetcher=None, force=False) -> int:
    """Read the CBS ATS week pages for the leagues/weeks on the board, at most hourly; returns rows stored."""
    games = media_games(conn, board, now, include_started=True)
    if not games:
        return 0
    _schema(conn)
    get = fetcher.get_text if hasattr(fetcher, "get_text") else fetcher
    urls = {}
    for g in games:
        week = int(g.get("week") or 0)
        if 1 <= week <= 25:
            urls[cbs_ats_url(g["league"], week)] = g["league"]
    stored = 0
    for url, league in sorted(urls.items()):
        last = conn.execute("SELECT attempted_at FROM media_ats_refresh WHERE url=?", (url,)).fetchone()
        if last and not force and _time(now) - _time(last[0]) < timedelta(hours=1):
            continue
        error = ""
        try:
            for record in parse_cbs_ats(get(url), league, url):
                game = _game_for(record, games)
                if game is None:
                    continue
                side = "home" if _code(record["pick_code"]) == _code(game["home_abbr"]) else "away"
                conn.execute("INSERT OR REPLACE INTO media_ats VALUES (?,?,?,?,?,?,?,?)",
                             (game["id"], league, record["expert"], record["source"], game[side + "_abbr"],
                              record["line"], url, now))
                stored += 1
        except Exception as exc:  # one unavailable page must never stop data collection
            error = type(exc).__name__
        conn.execute("INSERT OR REPLACE INTO media_ats_refresh VALUES (?,?,?)", (url, now, error))
    conn.commit()
    return stored


def load_ats(conn, board, now) -> pd.DataFrame:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_ats'").fetchone():
        return pd.DataFrame(columns=ATS_COLS)
    ids = {g["id"] for g in media_games(conn, board, now, include_started=True)}
    rows = [dict(r) for r in conn.execute("SELECT * FROM media_ats")]
    rows = [r for r in rows if r["game_id"] in ids]
    return (pd.DataFrame(rows, columns=ATS_COLS).sort_values(["game_id", "pick_team", "expert"], kind="stable")
            .reset_index(drop=True) if rows else pd.DataFrame(columns=ATS_COLS))
