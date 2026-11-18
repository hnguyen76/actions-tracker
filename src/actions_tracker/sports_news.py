"""Cached Vietnamese sports headlines from ESPN breaking news and Yahoo Sports RSS."""

from urllib.parse import urlparse
from xml.etree import ElementTree

import pandas as pd
import requests


ESPN_URL = "https://now.core.api.espn.com/v1/sports/news?limit=50"
YAHOO_URL = "https://sports.yahoo.com/rss/"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
COLS = ["id", "source", "is_breaking", "headline_vi", "headline_en", "section", "url", "published_at", "fetched_at"]
MAX_ESPN = 10
MAX_YAHOO = 10
YAHOO_FRESH_HOURS = 18


def _time(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def _iso(value):
    stamp = _time(value)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.000Z") if pd.notna(stamp) else ""


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS sports_news(
        id TEXT, source TEXT, is_breaking INTEGER, headline_vi TEXT, headline_en TEXT,
        section TEXT, url TEXT, published_at TEXT, fetched_at TEXT, active INTEGER DEFAULT 1,
        PRIMARY KEY(source,id))""")


def _allowed(url, source):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    allowed = (host == "espn.com" or host.endswith(".espn.com")) if source == "ESPN" else (
        host == "yahoo.com" or host.endswith(".yahoo.com"))
    return parsed.scheme == "https" and not parsed.username and allowed


def _espn_articles(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("breakingNews"), list):
        raise ValueError("ESPN response has no breakingNews list")
    rows = []
    for record in payload["breakingNews"]:
        if not isinstance(record, dict):
            continue
        links = record.get("links") if isinstance(record.get("links"), dict) else {}
        web = links.get("web") if isinstance(links.get("web"), dict) else {}
        row = {
            "id": str(record.get("id") or record.get("nowId") or web.get("href") or "").strip(),
            "source": "ESPN", "is_breaking": 1,
            "headline_en": str(record.get("headline") or record.get("title") or "").strip()[:300],
            "section": str(record.get("section") or record.get("root") or "ESPN").strip()[:40],
            "url": web.get("href") or record.get("link") or "",
            "published_at": _iso(record.get("published") or record.get("originallyPosted")),
        }
        if row["id"] and row["headline_en"] and _allowed(row["url"], row["source"]):
            rows.append(row)
    return rows[:MAX_ESPN]


def _yahoo_articles(xml, now):
    root = ElementTree.fromstring(xml)
    cutoff = _time(now) - pd.Timedelta(hours=YAHOO_FRESH_HOURS)
    rows = []
    for item in root.findall("./channel/item"):
        def value(name):
            node = item.find(name)
            return (node.text or "").strip() if node is not None else ""
        published = _time(value("pubDate"))
        if pd.isna(published) or published < cutoff:
            continue
        row = {"id": value("guid") or value("link"), "source": "Yahoo Sports", "is_breaking": 0,
               "headline_en": value("title")[:300], "section": value("category")[:40] or "Sports",
               "url": value("link"), "published_at": _iso(published)}
        if row["id"] and row["headline_en"] and _allowed(row["url"], row["source"]):
            rows.append(row)
    rows.sort(key=lambda row: row["published_at"], reverse=True)
    return rows[:MAX_YAHOO]


def _download_json(url):
    response = requests.get(url, timeout=12, headers={"User-Agent": "ActionsTracker/0.1 (+sports-news)"})
    response.raise_for_status()
    return response.json()


def _download_text(url):
    response = requests.get(url, timeout=12, headers={"User-Agent": "ActionsTracker/0.1 (+sports-news)"})
    response.raise_for_status()
    return response.text


def translate_vi(text):
    """Translate one public headline; results are cached and no private data is sent."""
    response = requests.get(TRANSLATE_URL, params={"client": "gtx", "sl": "en", "tl": "vi", "dt": "t", "q": text},
                            timeout=10, headers={"User-Agent": "ActionsTracker/0.1"})
    response.raise_for_status()
    payload = response.json()
    translated = "".join(str(part[0]) for part in (payload[0] if isinstance(payload, list) and payload else [])
                         if isinstance(part, list) and part and part[0])
    return translated.replace("\u200b", "").strip()


def _store_source(conn, source, articles, now, translator):
    """Replace one source's active set, writing only when its content actually changed."""
    rows = []
    for item in articles:
        old = conn.execute("SELECT headline_en,headline_vi FROM sports_news WHERE source=? AND id=?",
                           (source, item["id"])).fetchone()
        headline_vi = old[1] if old and old[0] == item["headline_en"] and old[1] else translator(item["headline_en"])
        if headline_vi:
            rows.append(item | {"headline_vi": headline_vi[:300], "fetched_at": now})
    new_ids = {row["id"] for row in rows}
    old_ids = {str(row[0]) for row in conn.execute("SELECT id FROM sports_news WHERE source=? AND active=1", (source,))}
    if new_ids != old_ids:
        conn.execute("UPDATE sports_news SET active=0 WHERE source=? AND active=1", (source,))
    changed = len(old_ids - new_ids)
    for row in rows:
        old = conn.execute("SELECT is_breaking,headline_vi,headline_en,section,url,published_at,active "
                           "FROM sports_news WHERE source=? AND id=?", (source, row["id"])).fetchone()
        values = (row["is_breaking"], row["headline_vi"], row["headline_en"], row["section"], row["url"],
                  row["published_at"], 1)
        if old and tuple(old) == values:
            continue
        conn.execute("""INSERT INTO sports_news
            (id,source,is_breaking,headline_vi,headline_en,section,url,published_at,fetched_at,active)
            VALUES (:id,:source,:is_breaking,:headline_vi,:headline_en,:section,:url,:published_at,:fetched_at,1)
            ON CONFLICT(source,id) DO UPDATE SET is_breaking=excluded.is_breaking,
              headline_vi=excluded.headline_vi, headline_en=excluded.headline_en, section=excluded.section,
              url=excluded.url, published_at=excluded.published_at, fetched_at=excluded.fetched_at, active=1""", row)
        changed += 1
    return changed


def refresh_sports_news(conn, now, get_json=None, get_text=None, translator=None):
    """Refresh both public sources independently; one failure never clears the other source or blocks the app."""
    _schema(conn)
    translate = translator or translate_vi
    changed = 0
    try:
        changed += _store_source(conn, "ESPN", _espn_articles((get_json or _download_json)(ESPN_URL)), now, translate)
    except Exception:
        pass
    try:
        changed += _store_source(conn, "Yahoo Sports", _yahoo_articles((get_text or _download_text)(YAHOO_URL), now), now, translate)
    except Exception:
        pass
    conn.commit()
    return changed


def load_sports_news(conn):
    """Read-only active headlines for the static-site payload."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sports_news'").fetchone():
        return pd.DataFrame(columns=COLS)
    rows = [dict(row) for row in conn.execute(
        "SELECT id,source,is_breaking,headline_vi,headline_en,section,url,published_at,fetched_at "
        "FROM sports_news WHERE active=1 ORDER BY is_breaking DESC,published_at DESC")]
    return pd.DataFrame(rows, columns=COLS)
