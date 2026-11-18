"""Source-linked availability news for upcoming and recent live NFL, NCAAF and NBA games.

Only explicit availability updates are classified automatically. Analysis from the
other approved publishers can be added with ``add_verified_news`` after review.
"""

import re
import sqlite3
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from actions_tracker.config import TZ

HOT_PICKS = 8
NEWS_COLS = ["game_id", "league", "team_abbr", "sentiment", "summary", "source", "url", "published_at", "fetched_at"]
_HOSTS = ("pff.com", "rotowire.com", "247sports.com", "nfl.com")
_FRESH_HOURS = 72
_QUALIFIERS = {"state", "tech", "atlantic", "international", "central", "coastal", "southern",
               "northern", "eastern", "western", "oh", "ohio", "a"}
_NFL = dict(zip(
    ["arizona cardinals", "atlanta falcons", "baltimore ravens", "buffalo bills", "carolina panthers",
     "chicago bears", "cincinnati bengals", "cleveland browns", "dallas cowboys", "denver broncos",
     "detroit lions", "green bay packers", "houston texans", "indianapolis colts", "jacksonville jaguars",
     "kansas city chiefs", "las vegas raiders", "los angeles chargers", "los angeles rams", "miami dolphins",
     "minnesota vikings", "new england patriots", "new orleans saints", "new york giants", "new york jets",
     "philadelphia eagles", "pittsburgh steelers", "san francisco 49ers", "seattle seahawks",
     "tampa bay buccaneers", "tennessee titans", "washington commanders"],
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LV LAC LAR MIA MIN NE NO NYG NYJ PHI PIT SF SEA TB TEN WAS".split()))
_NFL_ALIASES = {"JAC": "JAX", "NOR": "NO", "NOS": "NO", "NWE": "NE", "GNB": "GB", "SFO": "SF", "TAM": "TB"}
_NBA = dict(zip(
    ["atlanta hawks", "boston celtics", "brooklyn nets", "charlotte hornets", "chicago bulls",
     "cleveland cavaliers", "dallas mavericks", "denver nuggets", "detroit pistons", "golden state warriors",
     "houston rockets", "indiana pacers", "los angeles clippers", "los angeles lakers", "memphis grizzlies",
     "miami heat", "milwaukee bucks", "minnesota timberwolves", "new orleans pelicans", "new york knicks",
     "oklahoma city thunder", "orlando magic", "philadelphia 76ers", "phoenix suns", "portland trail blazers",
     "sacramento kings", "san antonio spurs", "toronto raptors", "utah jazz", "washington wizards"],
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS".split()))
_NBA_ALIASES = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTH": "UTA", "WSH": "WAS"}


def _time(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def _iso(value):
    return _time(value).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _norm(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    if text == "mississippi":
        return "ole miss"
    for old, new in (("north carolina state", "nc state"), ("southern california", "usc"),
                     ("central florida", "ucf"), ("southern methodist", "smu"), ("brigham young", "byu"),
                     ("texas san antonio", "utsa"), ("miami fl", "miami"), ("miami ohio", "miami oh"),
                     ("mississippi rebels", "ole miss rebels"), ("southern miss", "southern mississippi")):
        if text == old or text.startswith(old + " "):
            text = new + text[len(old):]
    return text


def _allowed(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and not parsed.username and any(host == h or host.endswith("." + h) for h in _HOSTS)


def eligible_games(conn, board, now):
    """Future NFL/NCAAF games with at least eight picks on any one market."""
    if board is None or board.empty or not {"game_id", "total_votes"}.issubset(board.columns):
        return []
    ids = sorted({int(r.game_id) for r in board.itertuples()
                  if pd.notna(r.game_id) and pd.notna(r.total_votes) and float(r.total_votes) >= HOT_PICKS})
    if not ids:
        return []
    cursor = conn.execute(f"SELECT * FROM games WHERE id IN ({','.join('?' for _ in ids)})", ids)
    names = [c[0] for c in cursor.description]
    return [g for row in cursor for g in [dict(zip(names, row))]
            if g["league"] in ("nfl", "ncaaf", "nba") and _time(g["start_time"]) > _time(now)
            and g.get("status") not in ("complete", "closed", "canceled", "cancelled", "postponed")]


RECENT_H = 12  # games that kicked off this recently keep showing the news verified before kickoff


def board_games(conn, board, now, include_started=False):
    """Every NFL/NCAAF game with picks on the upcoming board (the whole decision card), optionally plus picked
    games that kicked off within RECENT_H hours."""
    ids = set()
    if board is not None and not board.empty and "game_id" in board.columns:
        ids = {int(g) for g in board["game_id"] if pd.notna(g)}
    games = []
    if ids:
        cursor = conn.execute(f"SELECT * FROM games WHERE id IN ({','.join('?' for _ in ids)})", sorted(ids))
        names = [c[0] for c in cursor.description]
        games = [g for row in cursor for g in [dict(zip(names, row))]
                 if g["league"] in ("nfl", "ncaaf", "nba") and _time(g["start_time"]) > _time(now)
                 and g.get("status") not in ("complete", "closed", "canceled", "cancelled", "postponed")]
    if include_started:
        since = (_time(now) - timedelta(hours=RECENT_H)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        upto = _time(now).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        cursor = conn.execute("SELECT * FROM games g WHERE league IN ('nfl','ncaaf','nba') AND start_time > ? AND start_time <= ? "
                              "AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id)", (since, upto))
        names = [c[0] for c in cursor.description]
        seen = {g["id"] for g in games}
        games += [g for row in cursor for g in [dict(zip(names, row))]
                  if g["id"] not in seen and g.get("status") not in
                  ("complete", "closed", "canceled", "cancelled", "postponed")]
    return games


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS match_news(
        game_id INTEGER, league TEXT, team_abbr TEXT, sentiment TEXT, summary TEXT,
        source TEXT, url TEXT, published_at TEXT, fetched_at TEXT, subject TEXT,
        expires_at TEXT, priority INTEGER DEFAULT 0, PRIMARY KEY(game_id, team_abbr, subject))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS match_news_refresh(
        url TEXT PRIMARY KEY, attempted_at TEXT, error TEXT)""")


def _same_team(record, game, side):
    source, full = _norm(record.get("team")), _norm(game.get(side + "_name"))
    abbr = str(game.get(side + "_abbr") or "").upper()
    if game["league"] in ("nfl", "nba"):
        teams, aliases = (_NFL, _NFL_ALIASES) if game["league"] == "nfl" else (_NBA, _NBA_ALIASES)
        expected = teams.get(full, aliases.get(abbr, abbr))
        return str(record.get("team_code", "")).upper() == expected or source == full and bool(full)
    if not source:
        return False
    if source in (full, _norm(abbr)):
        return True
    if full.startswith(source + " "):
        return full[len(source) + 1:].split()[0] not in _QUALIFIERS
    return False


class _RotoWire(HTMLParser):
    """Read the publicly visible report; never collect subscriber analysis."""
    fields = {"news-update__player-link": "player", "news-update__headline": "headline",
              "news-update__timestamp": "date", "news-update__news": "body", "news-update__meta": "team"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.row, self.stack = [], None, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if self.row is None:
            if tag != "div" or "news-update" not in classes:
                return
            self.row, self.stack = {}, []
        field = self.stack[-1][1] if self.stack else None
        for cls in classes:
            if cls in self.fields:
                field = self.fields[cls]
        if "news-update__pos" in classes or "news-update__inj" in classes or "news-update__analysis" in classes:
            field = None
        if "news-update__headline" in classes:
            self.row["url"] = urljoin("https://www.rotowire.com", attrs.get("href", ""))
        if "news-update__logo" in classes:
            self.row["team_code"] = attrs.get("alt", "")
        if tag not in ("img", "br", "hr", "input", "meta", "link"):
            self.stack.append((tag, field))

    def handle_endtag(self, tag):
        if self.row is None:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if not self.stack:
            self.items.append({k: " ".join(v.split()) for k, v in self.row.items()})
            self.row = None

    def handle_data(self, data):
        if self.row is not None and self.stack and self.stack[-1][1]:
            key = self.stack[-1][1]
            self.row[key] = self.row.get(key, "") + data + " "


def parse_rotowire(text):
    parser = _RotoWire()
    parser.feed(text)
    return parser.items


_STATUS = [
    (r"season.ending|out for (?:the )?season", "negative", "vắng hết mùa"),
    (r"ruled out|won.t play|will not play|deemed unavailable|not (?:be )?available|remain\w* out|out for", "negative", "không thi đấu"),
    (r"injured reserve|placed on ir|pup (?:list|to)|remain on pup", "negative", "vẫn trong danh sách chấn thương"),
    (r"doubtful", "negative", "khả năng ra sân thấp"),
    (r"questionable|game.time decision", "negative", "chưa chắc ra sân"),
    (r"limited (?:practice|participant)|practice.*limited", "negative", "tập hạn chế; cần theo dõi"),
    (r"did not practice|didn.t practice|missed practice|not practicing|no practice", "negative", "nghỉ tập; cần theo dõi"),
    (r"full (?:practice|participant)", "positive", "tập luyện đầy đủ"),
    (r"no injury designation|cleared (?:for|to)|will play|will be available|available (?:saturday|sunday|monday)|good to go", "positive", "được xác nhận sẵn sàng thi đấu"),
    (r"expected to play|expected to be available|likely to play", "positive", "dự kiến có thể thi đấu"),
]


def classify(record):
    """Conservative factual Vietnamese wording, with headline taking precedence."""
    player = record.get("player", "").strip()
    surname = player.split()[-1] if player else ""
    body = record.get("body", "")
    # An availability tag can coexist with an explicit same-player game-time caveat.
    # Keep that caveat rather than turning the headline into confirmed participation.
    if surname and re.search(r"whether or not\s+" + re.escape(surname) +
                             r"\s+will\s+(?:actually\s+)?play", body, re.I):
        return "negative", f"{player}: chưa chắc ra sân; chờ quyết định sát giờ"[:150]
    for text in (record.get("headline", ""), record.get("body", "").split(", while")[0]):
        for pattern, sentiment, phrase in _STATUS:
            if re.search(pattern, text, re.I):
                return sentiment, f"{record.get('player', '').strip()}: {phrase}".strip(": ")[:150]
    return None


def _fresh(item, now):
    published, expiry, current = _time(item.get("published_at")), _time(item.get("expires_at")), _time(now)
    return pd.notna(published) and current - timedelta(days=7) <= published <= current and expiry > current


def _priority(url):
    match = re.search(r"-(\d+)/?$", str(url or ""))
    return int(match.group(1)) if match else 0


def _store(conn, item, now):
    if not _allowed(item.get("url")) or not _fresh(item, now):
        return 0
    subject = _norm(item.get("subject") or item["url"])
    priority = int(item.get("priority", 0))
    old = conn.execute("SELECT published_at, priority, fetched_at FROM match_news WHERE game_id=? AND team_abbr=? AND subject=?",
                       (int(item["game_id"]), item["team_abbr"], subject)).fetchone()
    if old and tuple(old) > (item["published_at"], priority, now):
        return 0
    conn.execute("INSERT OR REPLACE INTO match_news VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 tuple(item.get(c, now if c == "fetched_at" else "") for c in NEWS_COLS) +
                 (subject, item["expires_at"], priority))
    return 1


def add_verified_news(conn, items, now):
    """Add reviewed, source-linked summaries (optional subject and expires_at)."""
    _schema(conn)
    count = 0
    for raw in items:
        item = dict(raw)
        game = conn.execute("SELECT league,home_abbr,away_abbr,start_time FROM games WHERE id=?", (item.get("game_id"),)).fetchone()
        if not game or game[0] not in ("nfl", "ncaaf") or item.get("team_abbr") not in game[1:3] or _time(game[3]) <= _time(now):
            continue
        if item.get("sentiment") not in ("positive", "negative") or not str(item.get("summary", "")).strip():
            continue
        item.update(league=game[0], summary=str(item["summary"])[:150], fetched_at=now)
        item["published_at"] = _iso(item.get("published_at", now))
        item["expires_at"] = item.get("expires_at", _iso(_time(item["published_at"]) + timedelta(hours=_FRESH_HOURS)))
        item.setdefault("priority", _priority(item.get("url")))
        count += _store(conn, item, now)
    conn.commit()
    return count


def _download(url):
    response = requests.get(url, timeout=12, headers={"User-Agent": "ActionsTracker/0.1 (+public-news-summary)"})
    response.raise_for_status()
    return response.text


def refresh_news(conn, board, now, fetcher=None, force=False):
    """Refresh public reports for upcoming and recent live games; failures leave fresh cache intact."""
    try:
        games = board_games(conn, board, now, include_started=True)  # upcoming board plus picked games live <12h
        if not games:
            return 0
        _schema(conn)
        urls = set()
        for game in games:
            if game["league"] == "ncaaf":
                urls.update(("https://www.rotowire.com/cfootball/news.php", "https://www.rotowire.com/cfootball/news.php?view=injuries"))
            else:
                for side in ("home", "away"):
                    abbr = str(game.get(side + "_abbr") or "").upper()
                    teams, aliases = (_NBA, _NBA_ALIASES) if game["league"] == "nba" else (_NFL, _NFL_ALIASES)
                    code = teams.get(_norm(game.get(side + "_name")), aliases.get(abbr, abbr))
                    sport = "basketball" if game["league"] == "nba" else "football"
                    urls.add(f"https://www.rotowire.com/{sport}/news.php" + ("?team=" + code if code in teams.values() else ""))
        records = []
        scope = ",".join(str(game["id"]) for game in games)
        for url in sorted(urls):
            # A newly highlighted game needs its teams checked immediately, even
            # when this aggregate source was fetched for other teams this hour.
            cache_key = url + "#games=" + scope
            last = conn.execute("SELECT attempted_at FROM match_news_refresh WHERE url=?", (cache_key,)).fetchone()
            if not force and last and _time(now) - _time(last[0]) < timedelta(hours=1):
                continue
            error = ""
            try:
                download = getattr(fetcher, "get_text", fetcher) if fetcher is not None else _download
                parsed = parse_rotowire(download(url))
                if not parsed:
                    error = "no_public_reports"
                league = "ncaaf" if "/cfootball/" in url else "nba" if "/basketball/" in url else "nfl"
                records.extend((league, r) for r in parsed)
            except Exception as exc:  # a news provider must never stop the picks collector
                error = type(exc).__name__
            conn.execute("INSERT OR REPLACE INTO match_news_refresh VALUES (?,?,?)", (cache_key, now, error))
        latest = {}
        for league, record in records:
            try:
                day = pd.Timestamp(record["date"]).tz_localize(TZ).tz_convert("UTC")
                rank = _priority(record.get("url"))
                record.update(published_at=_iso(day), priority=rank)
            except (KeyError, ValueError, AttributeError):
                continue
            key = (league, _norm(record.get("team")), _norm(record.get("player")))
            if key not in latest or (record["published_at"], rank) > (latest[key]["published_at"], latest[key]["priority"]):
                latest[key] = record
        count = 0
        for (league, _, _), record in latest.items():
            classified = classify(record)
            for game in games:
                if league != game["league"]:
                    continue
                for side in ("home", "away"):
                    if _same_team(record, game, side):
                        item = dict(record, game_id=game["id"], league=league, team_abbr=game[side + "_abbr"],
                                    sentiment=classified[0] if classified else "neutral", summary=classified[1] if classified else "",
                                    subject=record.get("player"), source="RotoWire", fetched_at=now,
                                    expires_at=_iso(_time(record["published_at"]) + timedelta(hours=_FRESH_HOURS)))
                        count += _store(conn, item, now)
        conn.commit()
        return count
    except (sqlite3.Error, ValueError, TypeError):
        return 0


def load_news(conn, board, now):
    """No-network, read-only view for the current highlighted games only."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_news'").fetchone():
        return pd.DataFrame(columns=NEWS_COLS)
    ids = {g["id"] for g in board_games(conn, board, now, include_started=True)}
    if not ids:
        return pd.DataFrame(columns=NEWS_COLS)
    cursor = conn.execute("SELECT * FROM match_news")
    names = [c[0] for c in cursor.description]
    items = [dict(zip(names, row)) for row in cursor]
    items = [r for r in items if r["game_id"] in ids and r["sentiment"] in ("positive", "negative") and _allowed(r["url"]) and _fresh(r, now)]
    items.sort(key=lambda r: (r["published_at"], r["priority"], r["fetched_at"]), reverse=True)
    counts, selected = {}, []
    for item in items:
        key = (item["game_id"], item["team_abbr"], item["sentiment"])
        if counts.get(key, 0) < 2:
            selected.append(item)
            counts[key] = counts.get(key, 0) + 1
    return pd.DataFrame(selected, columns=NEWS_COLS)
