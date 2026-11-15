"""Named media experts' outright winners, separate from Action Network ATS picks.

CBS Straight Up grids and NFL.com score-pick cards are read automatically.
Reviewed ESPN/GameDay or syndicated picks can be added without counting an
expert twice. No odds subscription or user credentials are used here.
"""

import json
import re
import sqlite3
import unicodedata
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from actions_tracker.config import TZ
from actions_tracker.match_news import eligible_games
from actions_tracker.matching import normalize

MEDIA_PICK_COLS = ["game_id", "league", "expert", "source", "pick_team", "source_url", "published_at", "fetched_at", "source_note"]
_HOSTS = ("cbssports.com", "nfl.com", "espn.com", "espnpressroom.com", "sports.yahoo.com", "usatoday.com", "nbcsports.com")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_ALIASES = {"ARIZ": "ARI", "OKLA": "OU", "TEXAS": "TEX", "SCAR": "SC", "JAC": "JAX", "NOP": "NO", "NOR": "NO", "NOS": "NO", "NWE": "NE", "GNB": "GB", "SFO": "SF", "TAM": "TB"}
_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def _time(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def _iso(value):
    value = _time(value)
    return value.strftime("%Y-%m-%dT%H:%M:%S.000Z") if pd.notna(value) else None


def _code(value):
    value = str(value or "").upper()
    return _ALIASES.get(value, value)


def _name(value):
    value = normalize(str(value or "").replace("-", " "))
    return {"mississippi rebels": "ole miss rebels", "miami fl hurricanes": "miami hurricanes"}.get(value, value)


def _expert_key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "")).casefold() if c.isalnum())


def _allowed(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and any(host == h or host.endswith("." + h) for h in _HOSTS)


class _Node:
    def __init__(self, tag="", attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    def walk(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()):
                    yield child
                yield from child.walk(tag, cls)

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, _Node) else c for c in self.children).split())


class _Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_cbs(text, league, source_url):
    """Read only a validated Straight Up table; ATS pages are never inferred."""
    path = urlparse(source_url).path
    section = "nfl" if league == "nfl" else "college-football" if league == "ncaaf" else ""
    route = re.fullmatch(r"/" + section + r"/picks/experts/straight-up/(\d+)/?", path) if section else None
    if not _allowed(source_url) or not route:
        return []
    root = _Tree(text).root
    if not any("straight up" in h.text().lower() and "expert picks" in h.text().lower() for h in root.walk("h1")):
        return []
    tables = list(root.walk("table", "TableExpertPicks"))
    if len(tables) != 1:
        return []
    table = tables[0]
    experts = [node.text() for node in table.walk(cls="AuthorHeadshotAndName-name")]
    if not experts:
        return []
    rows = []
    for tr in table.walk("tr", "TableBase-bodyTr"):
        cells = [c for c in tr.children if isinstance(c, _Node) and c.tag == "td"]
        if len(cells) != len(experts) + 1:
            continue
        links = list(cells[0].walk("a", "GameMatchup"))
        match = re.search(r"/(NFL|NCAAF)_(\d{8})_([^@/]+)@([^/]+)/", links[0].attrs.get("href", "")) if links else None
        if not match or match[1] != ("NFL" if league == "nfl" else "NCAAF"):
            continue
        event_date = pd.to_datetime(match[2], format="%Y%m%d", errors="coerce")
        if pd.isna(event_date):
            continue
        away, home = match[3], match[4]
        status = " ".join(n.text() for n in cells[0].walk(cls="GameMatchup-gameStatus--status"))
        team_names = {}
        for cell in cells[1:]:
            for link in cell.walk("a"):
                team = re.search(r"/teams/([^/]+)/([^/]+)/", link.attrs.get("href", ""))
                if team:
                    team_names[team[1]] = team[2].replace("-", " ")
        for expert, cell in zip(experts, cells[1:]):
            picks = list(cell.walk("p", "TableExpertPicks-pick"))
            tokens = picks[0].text().split() if len(picks) == 1 else []
            if not tokens:
                buttons = list(cell.walk("button", "BetButton"))
                try:
                    config = json.loads(buttons[0].attrs.get("data-config", "")) if len(buttons) == 1 else {}
                    labels = [b.get("expertLabel") for b in config.get("meta", {}).get("bets", [])]
                    if config.get("marketName") != "Straight Up" or labels != [expert]:
                        continue
                except (ValueError, TypeError):
                    continue
                codes = [m[1] for link in cell.walk("a")
                         for m in [re.search(r"/teams/([^/]+)/", link.attrs.get("href", ""))] if m]
                tokens = codes if len(codes) == 1 else []
            if not tokens or _code(tokens[0]) not in {_code(away), _code(home)}:
                continue
            # A point spread (including a decimal line) signals the wrong market.
            if any(re.fullmatch(r"[+-]\d+(?:\.\d+)?", token) and
                   ("." in token or abs(float(token)) < 100) for token in tokens[1:]):
                continue
            rows.append(dict(league=league, expert=expert, pick_code=tokens[0],
                             away_code=away, home_code=home, away_name=team_names.get(away, ""),
                             home_name=team_names.get(home, ""), event_date=event_date.strftime("%Y-%m-%d"),
                             week=int(route[1]), season=int(match[2][:4]), status=status,
                             source="CBS Sports", source_url=source_url, published_at=None))
    return rows


def _published(root):
    for script in root.walk("script"):
        if script.attrs.get("type") != "application/ld+json":
            continue
        try:
            data = json.loads(script.text())
        except ValueError:
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if isinstance(obj, dict) and pd.notna(_time(obj.get("datePublished"))):
                return _iso(obj["datePublished"])
    return None


def parse_nfl(text, source_url):
    """NFL.com AUTHOR PICKS explicitly supplies a winner logo and predicted score."""
    route = re.fullmatch(r"/news/nfl-picks-week-(\d+)-(\d{4})-nfl-season/?", urlparse(source_url).path)
    if not _allowed(source_url) or not route:
        return []
    root = _Tree(text).root
    published = _published(root)
    if not published:
        return []
    week, year = map(int, route.groups())
    names, context, event_date, rows = [], None, None, []
    for node in root.walk():
        if node.tag == "h2":
            date = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})\b", node.text())
            if date and date[1][:3].lower() in _MONTHS:
                try:
                    month = _MONTHS[date[1][:3].lower()]
                    event_year = year + 1 if month <= 2 else year
                    event_date = f"{event_year:04d}-{month:02d}-{int(date[2]):02d}"
                    pd.Timestamp(event_date)
                except ValueError:
                    event_date = None
        if node.tag == "a":
            label = node.attrs.get("aria-label", "")
            if label.startswith("View details for "):
                names = (names + [label[len("View details for "):]])[-2:]
            game = re.search(r"/games/.+-at-.+-(\d{4})-reg-(\d+)(?:[/?#]|$)", node.attrs.get("href", ""))
            if game and len(names) == 2 and (int(game[1]), int(game[2])) == (year, week):
                context = tuple(names)
        if node.tag != "section" or not any(h.text() == "AUTHOR PICKS" for h in node.walk("h2")) or not context or not event_date:
            continue
        grids = [c for c in node.children if isinstance(c, _Node) and "grid" in c.attrs.get("class", "").split()]
        if not grids:
            continue
        for card in [c for c in grids[0].children if isinstance(c, _Node)]:
            experts = [n.text() for n in card.walk("span") if "lg:max-xl:hidden" in n.attrs.get("class", "").split()]
            winner = [img.attrs.get("alt") for img in card.walk("img") if img.attrs.get("alt")]
            if len(experts) != 1 or len(winner) != 1 or _name(winner[0]) not in {_name(n) for n in context}:
                continue
            rows.append(dict(league="nfl", expert=experts[0], pick_name=winner[0], away_name=context[0],
                             home_name=context[1], away_code="", home_code="", event_date=event_date,
                             week=week, season=year, status="", source="NFL.com", source_url=source_url,
                             published_at=published))
    return rows


def _matches(record, game):
    status = record.get("status", "").lower()
    if re.search(r"\b(?:final|live|halftime|in[ -]?progress|overtime|[1-4](?:st|nd|rd|th)(?:\s+quarter)?|q[1-4])\b", status):
        return False
    if record["league"] != game["league"] or int(record["week"]) != int(game.get("week") or -1):
        return False
    if game.get("season") and int(record["season"]) != int(game["season"]):
        return False
    for side in ("home", "away"):
        expected = _name(game.get(side + "_name"))
        actual = _name(record.get(side + "_name"))
        if actual and expected:
            if actual != expected:
                return False
        elif _code(record.get(side + "_code")) != _code(game.get(side + "_abbr")):
            return False
    event_day = pd.Timestamp(record["event_date"])
    game_day = _time(game["start_time"]).tz_convert(TZ).normalize().tz_localize(None)
    shift = abs((event_day - game_day).total_seconds()) / 3600
    return shift == 0 or ("postponed" in record.get("status", "").lower() and shift <= 36)


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS media_picks(
        game_id INTEGER, league TEXT, expert TEXT, source TEXT, pick_team TEXT, source_url TEXT,
        published_at TEXT, fetched_at TEXT, source_note TEXT, expert_key TEXT,
        PRIMARY KEY(game_id,expert_key))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS media_picks_refresh(
        url TEXT PRIMARY KEY, attempted_at TEXT, error TEXT)""")


def _source_rank(url):
    host = (urlparse(url).hostname or "").lower()
    return 1 if host.endswith("sports.yahoo.com") else 2


def _store(conn, item, game, now):
    if not _allowed(item.get("source_url")) or game["league"] not in ("nfl", "ncaaf"):
        return 0
    if item.get("league", game["league"]) != game["league"]:
        return 0
    current, kickoff = _time(now), _time(game["start_time"])
    seen, published = _time(item.get("fetched_at", now)), _time(item.get("published_at"))
    if pd.isna(seen) or seen > current or seen >= kickoff or current >= kickoff:
        return 0
    if pd.notna(published) and (published > current or published >= kickoff or current - published > timedelta(days=14)):
        return 0
    expert = " ".join(str(item.get("expert", "")).split())
    key = _expert_key(expert)
    if not key or len(expert) > 100 or item.get("pick_team") not in (game["home_abbr"], game["away_abbr"]):
        return 0
    market = str(item.get("market", "straight_up")).lower()
    if market not in ("straight_up", "winner", "ml", "h2h"):
        return 0
    path = urlparse(item["source_url"]).path
    if "cbssports.com" in (urlparse(item["source_url"]).hostname or ""):
        route = re.fullmatch(r"/(nfl|college-football)/picks/experts/straight-up/(\d+)/?", path)
        if not route or route[1] != ("nfl" if game["league"] == "nfl" else "college-football") or int(route[2]) != int(game.get("week") or -1):
            return 0
    old = conn.execute("SELECT pick_team,source_url,published_at,fetched_at FROM media_picks WHERE game_id=? AND expert_key=?", (game["id"], key)).fetchone()
    if old:
        if _source_rank(item["source_url"]) < _source_rank(old[1]):
            return 0
        if old[0] == item["pick_team"]:
            seen = min(seen, _time(old[3]))
        else:
            effective = published if pd.notna(published) else seen
            previous = _time(old[2]) if pd.notna(_time(old[2])) else _time(old[3])
            if effective < previous:
                return 0
    row = dict(item, game_id=game["id"], league=game["league"], expert=expert,
               published_at=_iso(published), fetched_at=_iso(seen), source_note=str(item.get("source_note") or "")[:150])
    conn.execute("INSERT OR REPLACE INTO media_picks VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(row.get(c, "") for c in MEDIA_PICK_COLS) + (key,))
    return 1


def add_verified_picks(conn, items, now):
    """Import reviewed outright picks; Yahoo republications remain one expert vote."""
    _schema(conn)
    count = 0
    for raw in items:
        cursor = conn.execute("SELECT * FROM games WHERE id=?", (raw.get("game_id"),))
        names = [c[0] for c in cursor.description]
        row = cursor.fetchone()
        if row:
            count += _store(conn, dict(raw), dict(zip(names, row)), now)
    conn.commit()
    return count


def _download(url):
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; ActionsTracker/0.1)"})
    response.raise_for_status()
    return response.text


def refresh_picks(conn, board, now, fetcher=None, force=False):
    """Refresh selected football matchups hourly, independently of odds credits."""
    games = eligible_games(conn, board, now)
    if not games:
        return 0
    _schema(conn)
    routes = {}
    for game in games:
        week, year = int(game.get("week") or 0), int(game.get("season") or _time(game["start_time"]).year)
        if not 1 <= week <= 25:
            continue
        section = "nfl" if game["league"] == "nfl" else "college-football"
        routes[f"https://www.cbssports.com/{section}/picks/experts/straight-up/{week}/"] = ("cbs", game["league"])
        if game["league"] == "nfl":
            routes[f"https://www.nfl.com/news/nfl-picks-week-{week}-{year}-nfl-season"] = ("nfl", "nfl")
    get = fetcher.get_text if hasattr(fetcher, "get_text") else fetcher or _download
    scope = ",".join(str(g["id"]) for g in sorted(games, key=lambda g: g["id"]))
    count = 0
    for url, (kind, league) in sorted(routes.items()):
        cache_key = url + "#games=" + scope
        last = conn.execute("SELECT attempted_at FROM media_picks_refresh WHERE url=?", (cache_key,)).fetchone()
        if last and not force and _time(now) - _time(last[0]) < timedelta(hours=1):
            continue
        error = ""
        try:
            text = get(url)
            records = parse_cbs(text, league, url) if kind == "cbs" else parse_nfl(text, url)
            if not records:
                error = "no_verified_winner_picks"
            for record in records:
                matched = [game for game in games if _matches(record, game)]
                if len(matched) != 1:
                    continue
                game = matched[0]
                if record.get("pick_name"):
                    side = next((s for s in ("home", "away") if _name(record["pick_name"]) == _name(game.get(s + "_name"))), None)
                else:
                    side = next((s for s in ("home", "away") if _code(record["pick_code"]) == _code(record[s + "_code"])), None)
                if not side:
                    continue
                item = dict(record, game_id=game["id"], pick_team=game[side + "_abbr"], fetched_at=now,
                            source_note="Picks cho lịch cũ; trận đã dời ngày" if "postponed" in record.get("status", "").lower() else "")
                count += _store(conn, item, game, now)
        except Exception as exc:  # One unavailable publisher must not interrupt data collection.
            error = type(exc).__name__
        conn.execute("INSERT OR REPLACE INTO media_picks_refresh VALUES (?,?,?)", (cache_key, now, error))
    conn.commit()
    return count


def load_picks(conn, board, now):
    """Read-only current winner selections; absent tables and ineligible games are empty."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_picks'").fetchone():
        return pd.DataFrame(columns=MEDIA_PICK_COLS)
    games = {g["id"]: g for g in eligible_games(conn, board, now)}
    cursor = conn.execute("SELECT * FROM media_picks")
    names = [c[0] for c in cursor.description]
    rows = []
    for values in cursor:
        item = dict(zip(names, values))
        game = games.get(item["game_id"])
        if game and _allowed(item["source_url"]) and item["pick_team"] in (game["home_abbr"], game["away_abbr"]):
            if _time(item["fetched_at"]) <= _time(now) and _time(item["fetched_at"]) < _time(game["start_time"]) and (pd.isna(_time(item["published_at"])) or _time(item["published_at"]) <= _time(now) and _time(item["published_at"]) < _time(game["start_time"])):
                rows.append(item)
    return pd.DataFrame(rows, columns=MEDIA_PICK_COLS).sort_values(["game_id", "pick_team", "expert"], kind="stable").reset_index(drop=True) if rows else pd.DataFrame(columns=MEDIA_PICK_COLS)
