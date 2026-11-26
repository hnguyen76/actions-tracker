"""ESPN standings, current playoff picture and a small transparent projection model.

The ESPN rows are the source of truth for records/seeds/rankings.  ``playoff_prob`` is
our estimate, never an ESPN probability.  The NFL model simulates the remaining
regular-season schedule; the NCAAF model scores the current CFP ranking, record,
point differential and current conference-leader position.
"""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from collections import defaultdict

import pandas as pd
import requests

from actions_tracker.matching import normalize

REFRESH_HOURS = 6
PLAYOFF_CACHE_VERSION = 2
NFL_SIMS = 5000
NFL_STANDINGS = ("https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
                 "?region=us&lang=en&contentorigin=espn&type=0&level=3")
NFL_SCHEDULE = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
                "?limit=1000&dates={season}&seasontype=2")
NCAAF_STANDINGS = ("https://site.api.espn.com/apis/v2/sports/football/college-football/standings"
                   "?region=us&lang=en&contentorigin=espn&group=80&season={season}")
NCAAF_RANKINGS = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
                  "?region=us&lang=en&season={season}&seasontype=2")
NBA_STANDINGS = ("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
                 "?region=us&lang=en&contentorigin=espn&type=0&level=2")
CFP_RANKING = ("https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/"
               "seasons/{season}/types/2/weeks/{week}/rankings/21?lang=en&region=us")

STANDING_COLS = ["league", "team_id", "team", "abbr", "logo", "conference", "division", "record",
                 "conf_record", "wins", "losses", "ties", "point_diff", "seed", "captured_at"]
PLAYOFF_COLS = STANDING_COLS + ["rank", "playoff_prob", "picture", "bid", "model", "projected_seed",
                                    "projection_reason"]
NBA_COLS = STANDING_COLS + ["previous_seed", "seed_change", "picture", "bid", "season_type"]
PREGAME_COLS = ["game_id", "league", "side", "team_id", "team", "abbr", "logo", "conference", "division",
                "record", "conf_record", "seed", "rank", "playoff_prob", "picture", "bid", "captured_at"]
_ABBR_ALIASES = {("nfl", "JAC"): "JAX", ("nfl", "LA"): "LAR", ("nfl", "WAS"): "WSH"}


class PlayoffError(RuntimeError):
    pass


def _json(get, url: str) -> dict:
    try:
        response = get(url, timeout=25, headers={"User-Agent": "ActionsTracker/0.1 (+ESPN standings)"})
    except TypeError:  # tiny test doubles often only accept the URL
        response = get(url)
    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - normalize all transport/JSON failures
        raise PlayoffError(f"ESPN standings unavailable: {exc}") from exc
    if not isinstance(data, dict):
        raise PlayoffError("ESPN standings returned an invalid payload")
    return data


def _stats(entry: dict) -> dict[str, dict]:
    out = {}
    for stat in entry.get("stats", []):
        out.setdefault(stat.get("name"), stat)
        if stat.get("type") in {"vsconf", "overall"}:
            out[stat["type"]] = stat
    return out


def _value(stats: dict, name: str, default=0):
    value = stats.get(name, {}).get("value")
    return default if value is None else value


def _display(stats: dict, name: str, default="–") -> str:
    return str(stats.get(name, {}).get("displayValue") or default)


def _standing_row(entry: dict, league: str, conference: str, division: str, captured_at: str) -> dict:
    team, stats = entry.get("team", {}), _stats(entry)
    logos = team.get("logos") or []
    return {
        "league": league,
        "team_id": str(team.get("id") or ""),
        "team": team.get("displayName") or team.get("shortDisplayName") or team.get("abbreviation"),
        "abbr": team.get("abbreviation"),
        "logo": logos[0].get("href") if logos else None,
        "conference": conference,
        "division": division,
        "record": _display(stats, "overall"),
        "conf_record": _display(stats, "vsconf"),
        "wins": float(_value(stats, "wins")),
        "losses": float(_value(stats, "losses")),
        "ties": float(_value(stats, "ties")),
        "point_diff": float(_value(stats, "pointDifferential", _value(stats, "differential"))),
        "seed": int(_value(stats, "playoffSeed")) or None,
        "captured_at": captured_at,
    }


def parse_nfl_standings(data: dict, captured_at: str) -> list[dict]:
    rows = []
    for conf in data.get("children", []):
        conference = conf.get("abbreviation") or conf.get("name")
        for div in conf.get("children", []):
            division = div.get("abbreviation") or div.get("name")
            for entry in div.get("standings", {}).get("entries", []):
                rows.append(_standing_row(entry, "nfl", conference, division, captured_at))
    if len(rows) < 28:
        raise PlayoffError("ESPN NFL standings are incomplete")
    return rows


def parse_ncaaf_standings(data: dict, captured_at: str) -> list[dict]:
    rows = []
    for conf in data.get("children", []):
        conference = conf.get("shortName") or conf.get("abbreviation") or conf.get("name")
        for entry in conf.get("standings", {}).get("entries", []):
            rows.append(_standing_row(entry, "ncaaf", conference, "", captured_at))
        for division in conf.get("children", []):
            for entry in division.get("standings", {}).get("entries", []):
                rows.append(_standing_row(entry, "ncaaf", conference,
                                          division.get("shortName") or division.get("name") or "", captured_at))
    if len(rows) < 100:
        raise PlayoffError("ESPN NCAAF standings are incomplete")
    return rows


def _nba_season_type(data: dict, now: str) -> str:
    stamp = pd.Timestamp(now)
    for season in data.get("seasons", []):
        if int(season.get("year") or 0) != int(data.get("season", {}).get("year") or 0):
            continue
        for item in season.get("types", []):
            try:
                if pd.Timestamp(item.get("startDate")) <= stamp < pd.Timestamp(item.get("endDate")):
                    return "postseason" if str(item.get("id")) == "3" else "playin" if str(item.get("id")) == "5" else "regular"
            except (TypeError, ValueError):
                continue
    return "regular"


def parse_nba_standings(data: dict, captured_at: str, previous: dict[str, int] | None = None) -> list[dict]:
    previous = previous or {}
    phase = _nba_season_type(data, captured_at)
    rows = []
    for conf in data.get("children", []):
        conference = conf.get("abbreviation") or conf.get("name")
        for entry in conf.get("standings", {}).get("entries", []):
            row = _standing_row(entry, "nba", conference, "", captured_at)
            seed = int(row.get("seed") or 99)
            old = previous.get(str(row.get("team_id")))
            row.update({"previous_seed": old, "seed_change": (old - seed) if old else 0,
                        "picture": "field" if seed <= 6 else "bubble" if seed <= 10 else "outside",
                        "bid": "PLAYOFF" if seed <= 6 else "PLAY-IN" if seed <= 10 else "OUT",
                        "season_type": phase})
            rows.append(row)
    if len(rows) < 28:
        raise PlayoffError("ESPN NBA standings are incomplete")
    return sorted(rows, key=lambda r: (r["conference"], r.get("seed") or 99))


def _remaining_nfl_games(data: dict, now: str) -> list[tuple[str, str]]:
    games = []
    current = pd.Timestamp(now)
    for event in data.get("events", []):
        season_type = event.get("season", {}).get("type")
        if season_type not in (None, 2) or pd.Timestamp(event.get("date")) <= current:
            continue
        comp = (event.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("completed"):
            continue
        teams = {c.get("homeAway"): str(c.get("team", {}).get("id") or c.get("id") or "")
                 for c in comp.get("competitors", [])}
        if teams.get("home") and teams.get("away"):
            games.append((teams["home"], teams["away"]))
    return games


def _logit(p: float) -> float:
    p = min(0.92, max(0.08, p))
    return math.log(p / (1 - p))


def nfl_projection(rows: list[dict], schedule: dict, now: str, season: int) -> list[dict]:
    by_id = {r["team_id"]: r for r in rows}
    remaining = [(h, a) for h, a in _remaining_nfl_games(schedule, now) if h in by_id and a in by_id]
    strength = {}
    for team_id, row in by_id.items():
        games = max(1.0, row["wins"] + row["losses"] + row["ties"])
        win_pct = (row["wins"] + row["ties"] * .5) / games
        strength[team_id] = .65 * _logit(win_pct) + .045 * (row["point_diff"] / games)

    made = defaultdict(int)
    rng = random.Random(season * 1009 + len(remaining))  # stable until inputs change
    for _ in range(NFL_SIMS):
        wins = {k: v["wins"] + .5 * v["ties"] for k, v in by_id.items()}
        for home, away in remaining:
            p_home = 1 / (1 + math.exp(-(strength[home] - strength[away] + .12)))
            wins[home if rng.random() < p_home else away] += 1
        for conference in {r["conference"] for r in rows}:
            conference_ids = [k for k, r in by_id.items() if r["conference"] == conference]
            division_winners = []
            for division in {by_id[k]["division"] for k in conference_ids}:
                ids = [k for k in conference_ids if by_id[k]["division"] == division]
                division_winners.append(max(ids, key=lambda k: (wins[k], strength[k])))
            wild = sorted((k for k in conference_ids if k not in division_winners),
                          key=lambda k: (wins[k], strength[k]), reverse=True)[:3]
            for team_id in division_winners + wild:
                made[team_id] += 1

    projected = {}
    for conference in {r["conference"] for r in rows}:
        conference_ids = [k for k, r in by_id.items() if r["conference"] == conference]
        division_winners = []
        for division in {by_id[k]["division"] for k in conference_ids}:
            ids = [k for k in conference_ids if by_id[k]["division"] == division]
            division_winners.append(max(ids, key=lambda k: (made[k] / NFL_SIMS, strength[k])))
        division_winners.sort(key=lambda k: (made[k] / NFL_SIMS, strength[k]), reverse=True)
        wild = sorted((k for k in conference_ids if k not in division_winners),
                      key=lambda k: (made[k] / NFL_SIMS, strength[k]), reverse=True)[:3]
        projected.update({team_id: seed for seed, team_id in enumerate(division_winners + wild, start=1)})

    out = []
    for row in rows:
        seed = row.get("seed") or 99
        predicted = projected.get(row["team_id"])
        chance = made[row["team_id"]] / NFL_SIMS
        out.append({**row, "rank": None, "playoff_prob": made[row["team_id"]] / NFL_SIMS,
                    "picture": "field" if predicted else "bubble" if chance >= .20 else "outside",
                    "bid": "DIV" if predicted and predicted <= 4 else "WC" if predicted else "",
                    "model": f"{NFL_SIMS:,} mô phỏng · tiebreak xấp xỉ", "projected_seed": predicted,
                    "projection_reason": (f"{chance * 100:.0f}% qua {NFL_SIMS:,} mô phỏng · "
                                          f"{row['record']} · DIFF {row['point_diff']:+g}")})
    return sorted(out, key=lambda r: (r.get("projected_seed") or 99, -r["playoff_prob"]))


def _cfp_payload(rankings: dict, season: int, get) -> dict:
    available = next((r for r in rankings.get("availableRankings", []) if str(r.get("id")) == "21"), None)
    if available:
        return _json(get, CFP_RANKING.format(season=season, week=available["week"]))
    polls = rankings.get("rankings", [])
    return next((r for r in polls if r.get("type") == "cfp"),
                next((r for r in polls if r.get("type") == "ap"), {}))


def ncaaf_projection(rows: list[dict], ranking: dict) -> list[dict]:
    by_id = {r["team_id"]: r for r in rows}
    ranked = {}
    for item in ranking.get("ranks", []):
        team = item.get("team", {})
        ref_id = re.search(r"/teams/(\d+)(?:\?|$)", str(team.get("$ref") or ""))
        team_id = str(team.get("id") or (ref_id.group(1) if ref_id else ""))
        ranked[team_id] = {"rank": int(item.get("current") or 99), "previous": item.get("previous")}

    leaders = {}
    conferences = {r["conference"] for r in rows if "indep" not in str(r["conference"]).lower()}
    for conference in conferences:
        group = [r for r in rows if r["conference"] == conference]
        leaders[conference] = max(group, key=lambda r: (
            _record_pct(r.get("conf_record")), _record_pct(r.get("record")), r["point_diff"]))
    auto = {r["team_id"] for r in sorted(leaders.values(), key=lambda r: (
        ranked.get(r["team_id"], {"rank": 99})["rank"], -_record_pct(r.get("record")), r.get("conference") or ""))[:5]}
    field = set(auto)
    for team_id, _ in sorted(ranked.items(), key=lambda x: x[1]["rank"]):
        if len(field) >= 12:
            break
        field.add(team_id)
    candidates = set(ranked) | auto

    output = []
    selected = sorted(field, key=lambda k: ranked.get(k, {"rank": 99})["rank"])
    seeds = {team_id: i + 1 for i, team_id in enumerate(selected)}
    for team_id in candidates:
        row = by_id.get(team_id)
        if not row:
            continue
        rank = ranked.get(team_id, {"rank": 99})["rank"]
        games = max(1.0, row["wins"] + row["losses"] + row["ties"])
        win_pct = (row["wins"] + .5 * row["ties"]) / games
        conf_leader = team_id in {r["team_id"] for r in leaders.values()}
        score = (13 - rank) + 2.2 * (win_pct - .75) + .06 * (row["point_diff"] / games) + (1.4 if conf_leader else 0)
        probability = min(.99, max(.01, 1 / (1 + math.exp(-score / 2.1))))
        output.append({**row, "seed": seeds.get(team_id), "rank": None if rank == 99 else rank,
                       "playoff_prob": probability,
                       "picture": "field" if team_id in field else "bubble" if rank <= 18 else "outside",
                       "bid": "AUTO" if team_id in auto else "AT-LARGE" if team_id in field else "",
                       "model": "CFP rank + record + DIFF + conference", "projected_seed": seeds.get(team_id),
                       "projection_reason": (f"CFP #{rank if rank != 99 else 'NR'} · {row['record']} · "
                                             f"DIFF {row['point_diff']:+g}" +
                                             (" · conference leader" if conf_leader else ""))})
    return sorted(output, key=lambda r: (r.get("seed") or 99, r.get("rank") or 99, -r["playoff_prob"]))


def _record_pct(record: str | None) -> float:
    try:
        parts = [float(x) for x in str(record).split("-")]
        wins, losses, ties = (parts + [0, 0, 0])[:3]
        return (wins + .5 * ties) / max(1, wins + losses + ties)
    except (TypeError, ValueError):
        return 0


def _save(conn: sqlite3.Connection, league: str, standings: list[dict], playoff: list[dict], captured_at: str,
          source_at: str | None = None) -> None:
    payload = json.dumps({"schema_version": PLAYOFF_CACHE_VERSION, "standings": standings, "playoff": playoff},
                         ensure_ascii=False, separators=(",", ":"))
    conn.execute("""INSERT INTO playoff_cache(league,payload,captured_at,source_at) VALUES (?,?,?,?)
                    ON CONFLICT(league) DO UPDATE SET payload=excluded.payload,
                    captured_at=excluded.captured_at,source_at=excluded.source_at""",
                 (league, payload, captured_at, source_at))
    conn.commit()


def _cache_supports_predictions(conn: sqlite3.Connection) -> bool:
    """Reject a fresh-but-old cache after the prediction payload changes shape."""
    rows = conn.execute("SELECT league,payload FROM playoff_cache").fetchall()
    payloads = {}
    try:
        payloads = {row["league"]: json.loads(row["payload"]) for row in rows}
    except (KeyError, TypeError, json.JSONDecodeError):
        return False
    if not {"nfl", "ncaaf", "nba"}.issubset(payloads):
        return False
    if any(payloads[league].get("schema_version") != PLAYOFF_CACHE_VERSION
           for league in ("nfl", "ncaaf", "nba")):
        return False
    nfl = payloads["nfl"].get("playoff", [])
    return bool(nfl) and all("projected_seed" in row for row in nfl)


def refresh_playoff_picture(conn: sqlite3.Connection, now: str, get=requests.get, force: bool = False) -> int:
    cache = conn.execute("SELECT count(*), min(captured_at) FROM playoff_cache").fetchone()
    oldest = cache[1]
    if (not force and cache[0] >= 3 and oldest and _cache_supports_predictions(conn)
            and pd.Timestamp(oldest) > pd.Timestamp(now) - pd.Timedelta(hours=REFRESH_HOURS)):
        return 0
    stamp = pd.Timestamp(now)
    season = stamp.year if stamp.month >= 7 else stamp.year - 1
    nfl_data = _json(get, NFL_STANDINGS)
    nfl_rows = parse_nfl_standings(nfl_data, now)
    nfl_schedule = _json(get, NFL_SCHEDULE.format(season=season))
    # ESPN's ``dates=YYYY`` follows the calendar, while NFL weeks 17–18 are in January.
    january = _json(get, NFL_SCHEDULE.format(season=season + 1))
    nfl_schedule["events"] = list(nfl_schedule.get("events", [])) + list(january.get("events", []))
    nfl_playoff = nfl_projection(nfl_rows, nfl_schedule, now, season)
    _save(conn, "nfl", nfl_rows, nfl_playoff, now, nfl_data.get("season", {}).get("displayName"))

    ncaaf_data = _json(get, NCAAF_STANDINGS.format(season=season))
    ncaaf_rows = parse_ncaaf_standings(ncaaf_data, now)
    ranking_index = _json(get, NCAAF_RANKINGS.format(season=season))
    ranking = _cfp_payload(ranking_index, season, get)
    ncaaf_playoff = ncaaf_projection(ncaaf_rows, ranking)
    _save(conn, "ncaaf", ncaaf_rows, ncaaf_playoff, now, ranking.get("lastUpdated"))

    previous_nba = {}
    cached = conn.execute("SELECT payload FROM playoff_cache WHERE league='nba'").fetchone()
    if cached:
        try:
            previous_nba = {str(r.get("team_id")): int(r.get("seed") or 0)
                            for r in json.loads(cached["payload"]).get("standings", []) if r.get("seed")}
        except (TypeError, ValueError, json.JSONDecodeError):
            previous_nba = {}
    nba_data = _json(get, NBA_STANDINGS)
    nba_rows = parse_nba_standings(nba_data, now, previous_nba)
    _save(conn, "nba", nba_rows, nba_rows, now, nba_data.get("season", {}).get("displayName"))
    return len(nfl_rows) + len(ncaaf_rows) + len(nba_rows)


def load_playoff_tables(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    out = {
        "NFL_Standings": pd.DataFrame(columns=STANDING_COLS),
        "NFL_Playoff": pd.DataFrame(columns=PLAYOFF_COLS),
        "NCAAF_Standings": pd.DataFrame(columns=STANDING_COLS),
        "NCAAF_Playoff": pd.DataFrame(columns=PLAYOFF_COLS),
        "NBA_Standings": pd.DataFrame(columns=NBA_COLS),
        "NBA_Playoff": pd.DataFrame(columns=NBA_COLS),
    }
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='playoff_cache'").fetchone()
    if not exists:
        return out
    for row in conn.execute("SELECT league,payload FROM playoff_cache"):
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        prefix = str(row["league"]).upper()
        standing_cols = NBA_COLS if prefix == "NBA" else STANDING_COLS
        playoff_cols = NBA_COLS if prefix == "NBA" else PLAYOFF_COLS
        out[f"{prefix}_Standings"] = pd.DataFrame(payload.get("standings", []), columns=standing_cols)
        out[f"{prefix}_Playoff"] = pd.DataFrame(payload.get("playoff", []), columns=playoff_cols)
    return out


def pregame_playoff_table(games: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Attach the latest ESPN standings/playoff row to each NFL/NCAAF team on the game board.

    NCAAF's projection table contains only CFP candidates, so every other FBS team keeps its standings row and is
    labelled outside the current field without inventing a probability. Team names are the fallback when Action and
    ESPN use different abbreviations.
    """
    if games is None or games.empty:
        return pd.DataFrame(columns=PREGAME_COLS)
    output = []
    for league in ("nfl", "ncaaf"):
        standings = tables.get(f"{league.upper()}_Standings", pd.DataFrame())
        playoff = tables.get(f"{league.upper()}_Playoff", pd.DataFrame())
        if standings is None or standings.empty:
            continue
        standing_rows = standings.to_dict("records")
        by_abbr = {str(r.get("abbr") or "").upper(): r for r in standing_rows}
        by_name = {normalize(r.get("team")): r for r in standing_rows if normalize(r.get("team"))}
        playoff_by_id = {str(r.get("team_id")): r for r in playoff.to_dict("records")} if len(playoff) else {}
        for game in games[games["league"] == league].to_dict("records"):
            for side in ("away", "home"):
                abbr = str(game.get(f"{side}_abbr") or "").upper()
                lookup = _ABBR_ALIASES.get((league, abbr), abbr)
                standing = by_abbr.get(lookup) or by_name.get(normalize(game.get(f"{side}_name")))
                if not standing:
                    continue
                projected = playoff_by_id.get(str(standing.get("team_id")))
                merged = {**standing, **(projected or {})}
                if projected is None and league == "ncaaf":
                    merged.update({"seed": None, "rank": None, "playoff_prob": None,
                                   "picture": "outside", "bid": ""})
                output.append({"game_id": int(game["id"]), "side": side,
                               **{c: merged.get(c) for c in PREGAME_COLS if c not in {"game_id", "side"}}})
    return pd.DataFrame(output, columns=PREGAME_COLS)
