"""Explicit, named human ATS selections in public weekly NFL articles.

These records are separate from winner picks, totals, props and model outputs.
Matching and capture-time policy belong to ``media_ats``; this module preserves
the original publisher, author, line and publication/modification timestamps.
"""

import json
import re
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd

from actions_tracker.match_news import _NFL
from actions_tracker.media_picks import _Node, _Tree, _iso, _time

SOURCES = {"covers.com": "Covers", "sportingnews.com": "Sporting News",
           "sportsbettingdime.com": "SportsBettingDime", "nbcsports.com": "NBC Sports"}
_HUBS = ["https://www.covers.com/nfl/picks", "https://www.sportingnews.com/us/nfl",
         "https://www.sportsbettingdime.com/news/nfl/", "https://www.nbcsports.com/betting/nfl"]
_KNOWN = {
    ("nfl", 10, 2026): [
        "https://www.sportingnews.com/us/nfl/news/nfl-picks-predictions-against-spread-week-10/96a8f2cc9f0b0ffc83e9d472",
        "https://www.nbcsports.com/betting/nfl/news/2026-nfl-week-10-best-bets-picks-predictions-player-props-odds-lions-vs-patriots-steelers-vs-bengals",
    ],
}
_PARTIAL_MARKET = re.compile(
    r"\b(?:(?:first|second|1st|2nd)\s*[- ]?half|[12]h|half[- ]?time|"
    r"(?:first|second|third|fourth|1st|2nd|3rd|4th)?\s*quarter|[1-4]q|q[1-4]|"
    r"alt(?:ernate)?[- ]+(?:spread|line|handicap))\b", re.I)


def source_hubs(league):
    return list(_HUBS) if league == "nfl" else []


def candidate_urls(league, week, season):
    """Predictable human-picks routes plus explicitly scoped known hashed URLs."""
    if league != "nfl" or not 1 <= int(week) <= 25:
        return []
    week, season = int(week), int(season)
    years = [season, season + 1] if week >= 17 else [season]
    out = []
    for year in years:
        out += [f"https://www.covers.com/nfl/picks-against-the-spread-week-{week}-{year}",
                f"https://www.covers.com/nfl/picks-and-predictions-week-{week}-{year}",
                f"https://www.sportsbettingdime.com/news/nfl/nfl-picks-against-the-spread-for-week-{week}-{year}/"]
    return out + _KNOWN.get((league, week, season), [])


def _source(url):
    p = urlparse(str(url or ""))
    host = (p.hostname or "").lower()
    if p.scheme != "https" or p.username or p.password:
        return None
    return next((name for domain, name in SOURCES.items() if host == domain or host == "www." + domain), None)


def _week(url):
    m = re.search(r"(?:^|[/-])week[-/](\d{1,2})(?=[/-]|$)", urlparse(url).path, re.I)
    return int(m[1]) if m and 1 <= int(m[1]) <= 25 else None


def discover_urls(html, base_url, league, week, season):
    """Only primary-source NFL links with the exact requested week in their path."""
    if league != "nfl" or not _source(base_url):
        return []
    allowed_years = {int(season), int(season) + 1} if int(week) >= 17 else {int(season)}
    out = set()
    for link in _Tree(html).root.walk("a"):
        p = urlparse(urljoin(base_url, link.attrs.get("href", "")))
        url = urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        if not _source(url) or "nfl" not in p.path.lower() or _week(url) != int(week):
            continue
        if not any(x in p.path.lower() for x in ("pick", "prediction", "best-bet")):
            continue
        years = {int(x) for x in re.findall(r"(?:^|[-/])(20\d{2})(?=[-/]|$)", p.path)}
        if years and not years.issubset(allowed_years):
            continue
        out.add(url)
    return sorted(out)


def _json_objects(value):
    if isinstance(value, dict):
        yield value
        for x in value.values():
            if isinstance(x, (dict, list)):
                yield from _json_objects(x)
    elif isinstance(value, list):
        for x in value:
            yield from _json_objects(x)


def _authors(value):
    if isinstance(value, list):
        return [name for x in value for name in _authors(x)]
    if isinstance(value, dict):
        if value.get("mainEntity"):
            return _authors(value["mainEntity"])
        return [value["name"]] if isinstance(value.get("name"), str) else []
    return [value] if isinstance(value, str) else []


def _canonical(value, source_url):
    if isinstance(value, dict):
        value = value.get("url") or value.get("@id")
    if not isinstance(value, str) or not value:
        return None
    origin = urlparse(source_url)
    base = source_url if value.startswith("#") else f"{origin.scheme}://{origin.netloc}/"
    p = urlparse(urljoin(base, value))
    return (p.scheme, (p.hostname or "").lower().removeprefix("www."), p.path.rstrip("/"))


def _metadata(root, source_url):
    candidates = []
    for script in root.walk("script"):
        if script.attrs.get("type") != "application/ld+json":
            continue
        try:
            candidates += [x for x in _json_objects(json.loads(script.text()))
                           if x.get("@type") in ("Article", "NewsArticle", "BlogPosting")]
        except (ValueError, TypeError):
            continue
    for item in candidates:
        headline = str(item.get("headline") or "")
        week = _week(source_url)
        match = re.search(r"\bweek\s+(\d+)\b", headline, re.I)
        if not match or int(match[1]) != week or "nfl" not in headline.lower():
            continue
        if _norm(headline) not in {_norm(h.text()) for h in root.walk("h1")}:
            continue
        # Related-article schema must never lend its author to this page's picks.
        canonical = _canonical(source_url, source_url)
        references = [item[k] for k in ("url", "mainEntityOfPage") if item.get(k)]
        if any(_canonical(reference, source_url) != canonical for reference in references):
            continue
        if item.get("isAccessibleForFree") is False:
            continue
        authors = list(dict.fromkeys(" ".join(x.split()) for x in _authors(item.get("author"))))
        if len(authors) != 1 or len(authors[0].split()) < 2 or re.search(r"\b(?:AI|model|staff|editorial|computer|team)\b", authors[0], re.I):
            continue
        pub, modified = _time(item.get("datePublished")), _time(item.get("dateModified"))
        if pd.isna(pub) or (item.get("dateModified") and pd.isna(modified)) or pd.notna(modified) and modified < pub:
            continue
        # January NFL articles may cover the preceding season's final weeks.
        season = pub.year - 1 if pub.month == 1 and week >= 17 else pub.year
        path_years = {int(x) for x in re.findall(r"(?:^|[-/])(20\d{2})(?=[-/]|$)", urlparse(source_url).path)}
        if path_years and path_years != {pub.year}:
            continue
        return dict(expert=authors[0], week=week, season=season, published_at=_iso(pub),
                    modified_at=_iso(modified), headline=headline, description=str(item.get("description") or ""))
    return None


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


_TEAM_ALIASES = {}
_cities = {}
for _name, _code in _NFL.items():
    _TEAM_ALIASES[_name] = _code
    _TEAM_ALIASES[_name.split()[-1]] = _code
    _TEAM_ALIASES[_code.lower()] = _code
    _city = " ".join(_name.split()[:-1])
    _cities.setdefault(_city, set()).add(_code)
for _city, _codes in _cities.items():
    if len(_codes) == 1:
        _TEAM_ALIASES[_city] = next(iter(_codes))
_TEAM_ALIASES.update({"l a chargers": "LAC", "l a rams": "LAR", "niners": "SF"})
_TEAM_PATTERN = "(?:" + "|".join(re.escape(x).replace(r"\ ", r"\s+") for x in sorted(_TEAM_ALIASES, key=len, reverse=True)) + ")"
_TEAM_RE = re.compile(r"(?<!\w)(" + _TEAM_PATTERN + r")(?!\w)", re.I)
_SIDE_RE = re.compile(r"(?<!\w)(" + _TEAM_PATTERN + r")(?!\w)\s*\(?\s*([+-]\d{1,2}(?:\.\d+)?|PK)(?![\d.])", re.I)


def _teams(value):
    text = _norm(value)
    return list(dict.fromkeys(_TEAM_ALIASES[_norm(m[1])] for m in _TEAM_RE.finditer(text)))


def _pair(value):
    # Strip point spreads/totals but preserve the explicit at/vs connector.
    teams = _teams(value)
    if len(teams) != 2 or not re.search(r"\b(?:at|vs|versus|over)\b|@", value, re.I):
        return None
    out = {"team_codes": teams}
    if re.search(r"\bat\b|@", value, re.I):
        out.update(away_code=teams[0], home_code=teams[1])
    return out


def _side_lines(value):
    # Normalize punctuation except signed numbers, since _TEAM_RE aliases have normalized names.
    value = re.sub(r"[’']", "", str(value)).replace("L.A.", "L A")
    out = {}
    for m in _SIDE_RE.finditer(value):
        team, line = _TEAM_ALIASES[_norm(m[1])], 0.0 if m[2].upper() == "PK" else float(m[2])
        out[team] = line
    return out


def _simple_pick(value):
    value = " ".join(str(value).split())
    if _PARTIAL_MARKET.search(value):
        return None
    value = re.sub(r"^(?:Picks?:\s*|\d+(?:\.\d+)?\s*units?:\s*)", "", value, flags=re.I)
    value = re.sub(r"\s*\((?:\d+(?:\.\d+)?\s*units?|[+-]\d{3,4})\)\s*", "", value, flags=re.I).strip().rstrip(".")
    m = re.fullmatch(r"(" + _TEAM_PATTERN + r")\s*\(?\s*([+-]\d{1,2}(?:\.\d+)?|PK)\)?", value, re.I)
    return (_TEAM_ALIASES[_norm(m[1])], 0.0 if m[2].upper() == "PK" else float(m[2])) if m else None


def _record(meta, source, url, pair, side):
    if not pair or not side or side[0] not in pair["team_codes"]:
        return None
    return {k: v for k, v in dict(meta, **pair, league="nfl", source=source, source_url=url,
                                 pick_code=side[0], line=side[1]).items() if k not in ("headline", "description")}


def _covers(root, meta, source, url):
    out = []
    for h in root.walk():
        if h.tag not in ("h2", "h3"):
            continue
        text = h.text()
        if _PARTIAL_MARKET.search(text):
            continue
        if ":" in text:
            matchup, pick = text.rsplit(":", 1)
            row = _record(meta, source, url, _pair(matchup), _simple_pick(pick))
        else:
            pair, sides = _pair(text), _side_lines(text)
            row = _record(meta, source, url, pair, next(iter(sides.items())) if len(sides) == 1 else None)
        if row:
            out.append(row)
    return out


def _sbd(root, meta, source, url):
    out = []
    for table in root.walk("table"):
        rows = list(table.walk("tr"))
        if not rows:
            continue
        headers = [c.text().lower() for c in rows[0].children if isinstance(c, _Node) and c.tag in ("th", "td")]
        if headers.count("ats pick") != 1 or headers.count("matchup") != 1:
            continue
        for tr in rows[1:]:
            cells = [c.text() for c in tr.children if isinstance(c, _Node) and c.tag in ("th", "td")]
            if len(cells) != len(headers):
                continue
            row = _record(meta, source, url, _pair(cells[headers.index("matchup")]), _simple_pick(cells[headers.index("ats pick")]))
            if row:
                out.append(row)
    return out


def _sporting(root, meta, source, url):
    out, heading = [], None
    for block in root.walk():
        if block.tag == "h3":
            heading = None if _PARTIAL_MARKET.search(block.text()) else block.text()
        elif block.tag == "p" and heading and re.match(r"^Pick:\s*", block.text(), re.I):
            pair, lines, value = _pair(heading), _side_lines(heading), re.sub(r"^Pick:\s*", "", block.text(), flags=re.I)
            winner = _teams(value.split(" win", 1)[0])
            if not pair or len(winner) != 1 or winner[0] not in pair["team_codes"]:
                continue
            fail = re.search(r"(?:fail to|don.t|do not|won.t|not) cover", value, re.I)
            if not re.search(r"\bcover\b", value, re.I):
                # Explicit "Dolphins (+2.5) over Colts" heading is itself the ATS selection.
                if " over " not in heading.lower() or winner[0] not in lines:
                    continue
            picked = next(t for t in pair["team_codes"] if t != winner[0]) if fail else winner[0]
            line = lines.get(picked)
            other = next(t for t in pair["team_codes"] if t != picked)
            if line is None and other in lines:
                line = -lines[other]
            row = _record(meta, source, url, pair, (picked, line) if line is not None else None)
            if row:
                out.append(row)
            heading = None
    return out


def _nbc(root, meta, source, url):
    out, pair = [], None
    bodies = list(root.walk(cls="RichTextArticleBody"))
    body = bodies[0] if len(bodies) == 1 else root
    for block in body.walk():
        if block.tag in ("h2", "h3"):
            pair = None if _PARTIAL_MARKET.search(block.text()) else _pair(block.text())
        elif block.tag in ("p", "li") and re.match(r"^Picks?:", block.text(), re.I):
            for pick in re.sub(r"^Picks?:\s*", "", block.text(), flags=re.I).split(","):
                row = _record(meta, source, url, pair, _simple_pick(pick))
                if row:
                    out.append(row)
    return out


def parse_article(html, league, source_url):
    """Return only explicitly selected full-game spreads from a single named author."""
    source = _source(source_url)
    if league != "nfl" or not source or "nfl" not in urlparse(source_url).path.lower() or not _week(source_url):
        return []
    root = _Tree(html).root
    meta = _metadata(root, source_url)
    if not meta or _PARTIAL_MARKET.search(meta["headline"]):
        return []
    headings = " ".join(n.text() for n in root.walk() if n.tag in ("h1", "h2"))
    intro = " ".join(n.text() for n in root.walk("p"))[:7000]
    if re.search(r"\b(?:SBD\s+AI|AI[- ](?:model|generated|picks)|computer[- ]simulat|simulation[- ]model)\b",
                 " ".join((meta["headline"], meta["description"], intro)), re.I):
        return []
    if source != "NBC Sports" and not re.search(r"against (?:the )?spread|\bATS\b", meta["headline"] + " " + headings, re.I):
        return []
    parser = {"Covers": _covers, "Sporting News": _sporting, "SportsBettingDime": _sbd, "NBC Sports": _nbc}[source]
    rows = parser(root, meta, source, source_url)
    unique = {}
    for row in rows:
        key = tuple(sorted(row["team_codes"]))
        old = unique.get(key)
        if old and (old["pick_code"], old["line"]) != (row["pick_code"], row["line"]):
            unique[key] = None
        elif key not in unique:
            unique[key] = row
    return [r for r in unique.values() if r is not None]
