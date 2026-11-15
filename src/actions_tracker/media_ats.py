"""Named experts' explicit ATS picks for the decision card, separate from outright winners.

CBS's locked week grids and source-linked editorial ATS articles retain each person's exact line.
Article reads after kickoff are display-only, require pregame publication/revision, and are labelled.
"""

import json
import math
import re
import time
from datetime import timedelta
from urllib.parse import urlparse

import pandas as pd

from actions_tracker.media_picks import (_Node, _Tree, _code, _download, _expert_key, _iso, _name, _time,
                                       media_games)

ATS_COLS = ["game_id", "league", "expert", "source", "pick_team", "line", "source_url", "fetched_at",
            "published_at", "modified_at", "source_note", "expert_key"]
_SOURCES = {"cbssports.com": "CBS Sports", "covers.com": "Covers", "sportingnews.com": "Sporting News",
            "sportsbettingdime.com": "SportsBettingDime", "nbcsports.com": "NBC Sports"}
_NATIVE = {**{_expert_key(n): "CBS Sports" for n in ("Pete Prisco", "Jared Dubin", "Ryan Wilson", "John Breech",
                                                   "Tyler Sullivan", "Dave Richard", "Jamey Eisenberg")},
           **{_expert_key(n): "Covers" for n in ("Chris Vasile", "Jason Logan")},
           **{_expert_key(n): "Sporting News" for n in ("Vinnie Iyer", "Bill Bender")},
           **{_expert_key(n): "NBC Sports" for n in ("Vaughn Dalzell", "Jay Croucher", "Drew Dinsick", "Trysta Krick")},
           **{_expert_key(n): "SportsBettingDime" for n in ("Zach Reger", "Sascha Paruk")}}
_LINE = re.compile(r"^([A-Za-z&.]+)\s+(PK|pk|[+-]?\d+(?:\.\d+)?)$")


def _source(url):
    try:
        p = urlparse(str(url or ""))
        host = (p.hostname or "").lower()
        port = p.port
    except ValueError:
        return None
    if p.scheme != "https" or p.username or p.password or port not in (None, 443):
        return None
    return next((name for domain, name in _SOURCES.items() if host == domain or host.endswith("." + domain)), None)


def _team_code(value, league):
    code = _code(value)
    return {"LA": "LAR", "WSH": "WAS", "WASH": "WAS", "LVR": "LV"}.get(code, code) if league == "nfl" else code


def _url_matches_game(url, game):
    source = _source(url)
    if not source:
        return False
    path = urlparse(url).path
    if source == "CBS Sports":
        section = "nfl" if game["league"] == "nfl" else "college-football"
        route = re.fullmatch(r"/" + section + r"/picks/experts/against-the-spread/(\d+)/?", path)
        return bool(route and int(route[1]) == int(game.get("week") or -1))
    sections = {
        "Covers": ("/nfl/", "/ncaaf/"),
        "Sporting News": ("/us/nfl/news/", "/us/ncaa-football/news/"),
        "SportsBettingDime": ("/news/nfl/", "/news/ncaaf/"),
        "NBC Sports": ("/betting/nfl/news/", "/betting/college-football/news/"),
    }
    prefixes = sections.get(source)
    return bool(prefixes and path.startswith(prefixes[0 if game["league"] == "nfl" else 1]))


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
    if _source(source_url) != "CBS Sports" or not route:
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
                             week=int(route[1]), season=int(match[2][:4]) - int(int(match[2][4:6]) <= 2),
                             source="CBS Sports", source_url=source_url))
    return rows


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS media_ats(
        game_id INTEGER, league TEXT, expert TEXT, source TEXT, pick_team TEXT, line REAL, source_url TEXT,
        fetched_at TEXT, published_at TEXT, modified_at TEXT, source_note TEXT, expert_key TEXT,
        PRIMARY KEY(game_id, expert))""")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(media_ats)")}
    for name in ("published_at", "modified_at", "source_note", "expert_key"):
        if name not in columns:
            conn.execute(f"ALTER TABLE media_ats ADD COLUMN {name} TEXT")
    # This migration belongs only to media_ats; it must not invoke the games/line migration.
    rows = [dict(zip([c[0] for c in cursor.description], r)) for cursor in
            [conn.execute("SELECT rowid AS _rowid,* FROM media_ats")] for r in cursor]
    by_expert = {}
    for row in rows:
        row["_stored_key"] = row.get("expert_key")
        key = _expert_key(row["expert"])
        if not key:
            key = f"invalid{row['_rowid']}"
        row["expert_key"] = key
        group = (row["game_id"], key)
        old = by_expert.get(group)
        if old is None or _preference(row) > _preference(old):
            by_expert[group] = row
    keep = {row["_rowid"] for row in by_expert.values()}
    for row in rows:
        if row["_rowid"] not in keep:
            conn.execute("DELETE FROM media_ats WHERE rowid=?", (row["_rowid"],))
    changed = [row for row in by_expert.values() if row["_stored_key"] != row["expert_key"]]
    # Clear changed keys first: an existing unique index may contain swapped/stale identities.
    for row in changed:
        conn.execute("UPDATE media_ats SET expert_key=NULL WHERE rowid=?", (row["_rowid"],))
    for row in changed:
        conn.execute("UPDATE media_ats SET expert_key=? WHERE rowid=?", (row["expert_key"], row["_rowid"]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS media_ats_expert_key ON media_ats(game_id,expert_key)")
    conn.execute("CREATE TABLE IF NOT EXISTS media_ats_refresh(url TEXT PRIMARY KEY, attempted_at TEXT, error TEXT)")
    conn.execute("""CREATE TABLE IF NOT EXISTS media_ats_urls(
        url TEXT, league TEXT, week INTEGER, season INTEGER, PRIMARY KEY(url,league,week,season))""")


def _stamp(row):
    for field in ("modified_at", "published_at", "fetched_at"):
        value = _time(row.get(field))
        if pd.notna(value):
            return value.value
    return -1


def _preference(row):
    key = row.get("expert_key") or _expert_key(row.get("expert"))
    return (int(_NATIVE.get(key) == row.get("source")), _stamp(row), str(row.get("source_url") or ""))


def _same_team(record, game, side):
    code = record.get(side + "_code")
    if code:
        return _team_code(code, game["league"]) == _team_code(game.get(side + "_abbr"), game["league"])
    name = record.get(side + "_name")
    return bool(name and game.get(side + "_name") and _name(name) == _name(game[side + "_name"]))


def _game_for(record, games):
    """Require league, season/week and both teams; never guess a matchup from one team alone."""
    out = []
    for g in games:
        if g["league"] != record.get("league") or int(g.get("week") or -1) != int(record.get("week") or -2):
            continue
        season = int(g.get("season") or _time(g["start_time"]).year)
        if record.get("season") is None or season != int(record["season"]):
            continue
        if record.get("away_code") or record.get("away_name"):
            if not (_same_team(record, g, "away") and _same_team(record, g, "home")):
                continue
        else:
            want = {_team_code(v, g["league"]) for v in record.get("team_codes", []) if v}
            actual = {_team_code(g.get(side + "_abbr"), g["league"]) for side in ("away", "home")}
            if len(want) != 2 or want != actual:
                continue
        day = _time(g["start_time"]).tz_convert("America/New_York").normalize().tz_localize(None)
        event_day = _time(record.get("event_date"))
        if record.get("event_date") and pd.isna(event_day):
            continue
        if pd.notna(event_day):
            source_day = event_day.tz_localize(None).normalize()
            days = abs((day - source_day).days)
            if days > (2 if record.get("source") == "CBS Sports" else 0):
                continue
        out.append(g)
    return out[0] if len(out) == 1 else None


def _store(conn, record, game, now):
    source = _source(record.get("source_url"))
    if not source or game.get("league") not in ("nfl", "ncaaf") or not _url_matches_game(record["source_url"], game):
        return 0
    if record.get("league", game["league"]) != game["league"]:
        return 0
    if any(record.get(field) is not None and str(record[field]) != str(game.get(field)) for field in ("week", "season")):
        return 0
    if (record.get("team_codes") or record.get("away_code") or record.get("away_name")) and _game_for(record, [game]) is None:
        return 0
    expert = " ".join(str(record.get("expert") or "").split())
    key = _expert_key(expert)
    if not key or len(expert) > 100 or re.search(r"\b(?:AI|model|computer|simulation|algorithm)\b", expert, re.I):
        return 0
    try:
        line = float(record.get("line"))
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(line) or abs(line) > 100 or str(record.get("market", "spread")).lower() not in ("spread", "ats"):
        return 0
    sides = [side for side in ("home", "away") if
             (_team_code(record.get("pick_code"), game["league"]) == _team_code(game.get(side + "_abbr"), game["league"]))
             or (record.get("pick_name") and _name(record["pick_name"]) == _name(game.get(side + "_name")))]
    if len(sides) != 1:
        return 0
    current, kickoff = _time(now), _time(game["start_time"])
    seen = _time(record.get("fetched_at", now))
    published, modified = _time(record.get("published_at")), _time(record.get("modified_at"))
    if pd.isna(current) or pd.isna(kickoff) or pd.isna(seen) or seen > current:
        return 0
    note = str(record.get("source_note") or "")[:160]
    if source != "CBS Sports":
        if pd.isna(published) or published > current or published >= kickoff or current - published > timedelta(days=14):
            return 0
        if pd.notna(modified) and (modified > current or modified >= kickoff or modified < published):
            return 0
        if current >= kickoff:
            note = "Đọc sau giờ bắt đầu" + (" · " + note if note else "")
    old_cursor = conn.execute("SELECT * FROM media_ats WHERE game_id=? AND expert_key=?", (game["id"], key))
    old = old_cursor.fetchone()
    old = dict(zip([c[0] for c in old_cursor.description], old)) if old else None
    row = dict(game_id=game["id"], league=game["league"], expert=expert, expert_key=key, source=source,
               pick_team=game[sides[0] + "_abbr"], line=line, source_url=record["source_url"],
               fetched_at=_iso(seen), published_at=_iso(published), modified_at=_iso(modified), source_note=note)
    if old:
        # A pregame capture remains the first observed timestamp if the exact pick is unchanged.
        same = old["pick_team"] == row["pick_team"] and old["line"] == row["line"]
        if source == "CBS Sports" and current >= kickoff and _time(old["fetched_at"]) < kickoff and not same:
            return 0
        if _preference(row) < _preference(old):
            return 0
        if same and pd.notna(_time(old.get("fetched_at"))) and _time(old["fetched_at"]) < seen:
            row["fetched_at"] = old["fetched_at"]
            if _time(old["fetched_at"]) < kickoff:
                row["source_note"] = str(old.get("source_note") or "")
    cols = ",".join(ATS_COLS)
    update = ",".join(f"{c}=excluded.{c}" for c in ATS_COLS if c not in ("game_id", "expert_key"))
    conn.execute(f"INSERT INTO media_ats({cols}) VALUES ({','.join('?' for _ in ATS_COLS)}) "
                 f"ON CONFLICT(game_id,expert_key) DO UPDATE SET {update}", tuple(row[c] for c in ATS_COLS))
    return 1


def add_verified_ats(conn, items, now):
    """Import reviewed explicit ATS records without pretending late article reads were pregame captures."""
    _schema(conn)
    count = 0
    for raw in items:
        cursor = conn.execute("SELECT * FROM games WHERE id=?", (raw.get("game_id"),))
        game = cursor.fetchone()
        if game:
            count += _store(conn, dict(raw), dict(zip([c[0] for c in cursor.description], game)), now)
    conn.commit()
    return count


def refresh_ats(conn, board, now, fetcher=None, force=False) -> int:
    """Refresh explicit human ATS from public grids/articles hourly, retaining independent source failures."""
    from actions_tracker import media_ats_articles as articles

    games = media_games(conn, board, now, include_started=True)
    if not games:
        return 0
    _schema(conn)
    conn.commit()
    began = time.monotonic()
    get = fetcher.get_text if hasattr(fetcher, "get_text") else fetcher or _download
    urls = {}
    scopes = set()
    for g in games:
        week = int(g.get("week") or 0)
        if 1 <= week <= 25:
            season = int(g.get("season") or _time(g["start_time"]).year)
            urls[cbs_ats_url(g["league"], week)] = ("cbs", g["league"])
            scopes.add((g["league"], week, season))
    scope = ",".join(str(g["id"]) for g in sorted(games, key=lambda g: g["id"]))

    def fetch(url):
        key = url + "#games=" + scope
        last = conn.execute("SELECT attempted_at FROM media_ats_refresh WHERE url=?", (key,)).fetchone()
        if last and not force and _time(now) - _time(last[0]) < timedelta(hours=1):
            return None, key
        try:
            # Never keep the schema/discovery/source writer transaction open during HTTP.
            conn.commit()
            return get(url), key
        except Exception as exc:
            conn.execute("INSERT OR REPLACE INTO media_ats_refresh VALUES (?,?,?)", (key, now, type(exc).__name__))
            conn.commit()
            return None, key

    def mark(key, error=""):
        conn.execute("INSERT OR REPLACE INTO media_ats_refresh VALUES (?,?,?)", (key, now, error))
        conn.commit()

    hub_texts = {}
    for league, week, season in sorted(scopes):
        for url in articles.candidate_urls(league, week, season):
            if _source(url) and _source(url) != "CBS Sports":
                conn.execute("INSERT OR IGNORE INTO media_ats_urls VALUES (?,?,?,?)", (url, league, week, season))
        for hub in articles.source_hubs(league):
            if not _source(hub):
                continue
            if hub in hub_texts:
                text, key = hub_texts[hub], hub + "#games=" + scope
            else:
                text, key = fetch(hub)
                hub_texts[hub] = text
            if text is None:
                continue
            try:
                for url in articles.discover_urls(text, hub, league, week, season):
                    if _source(url) and _source(url) != "CBS Sports":
                        conn.execute("INSERT OR IGNORE INTO media_ats_urls VALUES (?,?,?,?)", (url, league, week, season))
                mark(key)
            except Exception as exc:
                mark(key, type(exc).__name__)
        for row in conn.execute("SELECT url FROM media_ats_urls WHERE league=? AND week=? AND season=?", (league, week, season)):
            if _source(row[0]):
                urls[row[0]] = ("article", league)
    stored = 0
    for url, (kind, league) in sorted(urls.items()):
        text, key = fetch(url)
        if text is None:
            continue
        error = ""
        try:
            records = parse_cbs_ats(text, league, url) if kind == "cbs" else articles.parse_article(text, league, url)
            if not records:
                error = "no_explicit_ats_picks"
            for record in records:
                game = _game_for(record, games)
                if game is None:
                    continue
                captured = _time(now) + pd.Timedelta(seconds=int(time.monotonic() - began))
                captured = captured.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                stored += _store(conn, dict(record, source_url=url, fetched_at=captured), game, captured)
        except Exception as exc:  # one unavailable page must never stop data collection
            error = type(exc).__name__
        mark(key, error)
    conn.commit()
    return stored


def load_ats(conn, board, now) -> pd.DataFrame:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_ats'").fetchone():
        return pd.DataFrame(columns=ATS_COLS)
    games = {g["id"]: g for g in media_games(conn, board, now, include_started=True)}
    cursor = conn.execute("SELECT * FROM media_ats")
    rows = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor]
    unique = {}
    for raw in rows:
        game, source = games.get(raw["game_id"]), _source(raw.get("source_url"))
        if game is None or not source or not _url_matches_game(raw["source_url"], game) or pd.isna(_time(raw.get("fetched_at"))) or _time(raw["fetched_at"]) > _time(now):
            continue
        try:
            if not math.isfinite(float(raw["line"])) or abs(float(raw["line"])) > 100:
                continue
        except (TypeError, ValueError):
            continue
        if _team_code(raw["pick_team"], game["league"]) not in {_team_code(game.get(s + "_abbr"), game["league"]) for s in ("away", "home")}:
            continue
        row = {c: raw.get(c) for c in ATS_COLS}
        row.update(source=source, expert_key=_expert_key(raw["expert"]), source_note=str(raw.get("source_note") or ""))
        if source != "CBS Sports":
            published, modified, kickoff = _time(raw.get("published_at")), _time(raw.get("modified_at")), _time(game["start_time"])
            if pd.isna(published) or published >= kickoff or published > _time(now) or (pd.notna(modified) and (modified >= kickoff or modified > _time(now))):
                continue
        key = (row["game_id"], row["expert_key"])
        if row["expert_key"] and (key not in unique or _preference(row) > _preference(unique[key])):
            unique[key] = row
    rows = list(unique.values())
    return (pd.DataFrame(rows, columns=ATS_COLS).sort_values(["game_id", "pick_team", "expert"], kind="stable")
            .reset_index(drop=True) if rows else pd.DataFrame(columns=ATS_COLS))
