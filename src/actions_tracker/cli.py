"""`python -m actions_tracker run` — picks from Action Network, scores and lines from The Odds API (spec §12)."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from actions_tracker import db
from actions_tracker.analysis import build_tables
from actions_tracker.build_site import build_site
from actions_tracker.config import LEAGUES
from actions_tracker.export_excel import write_report
from actions_tracker.fetch import FetchError, Fetcher, fetch_bygame, fetch_picks, fetch_public
from actions_tracker.matching import match_events
from actions_tracker.odds_api import OddsApi, OddsApiError, load_key, parse_lines, parse_scores
from actions_tracker.parse import ParseError, parse_bygame_page, parse_picks_page, parse_public_page
from actions_tracker.rules import RULE_LEAGUES, sync_rule_plays

MIN_CREDITS_FOR_ODDS = 30
SCORE_DELAY_H = 3     # a game is worth asking a score for 3h after kickoff
SCORE_WINDOW_D = 3    # The Odds API scores go back at most 3 days
# --budget (hourly schedule): The Odds API free plan is 500 credits/month, so lines are fetched only on the
# last run before a kickoff and scores are spaced out. NBA gets one odds/scores call per 12h.
BUDGET_ODDS_LEAD_MIN = 70
BUDGET_ODDS_EVERY_H = {"nba": 12.0}
BUDGET_SCORES_EVERY_H = {"nba": 12.0}
BUDGET_DEFAULT_ODDS_H = 0.75
BUDGET_DEFAULT_SCORES_H = 6.0
# games worth a score/line: any game with an expert pick or a logged rule play
_PICKED = ("(EXISTS (SELECT 1 FROM picks p WHERE p.game_id = games.id)"
           " OR EXISTS (SELECT 1 FROM rule_plays rp WHERE rp.game_id = games.id))")


class OfflineFetcher:
    """Serves `{league}_picks.html` from a folder instead of the network."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def get_text(self, url: str) -> str:
        m = re.search(r"\.com/([a-z]+)/(?:picks|public-betting)", url)
        kind = "public" if "/public-betting" in url else "bygame" if "/picks/game" in url else "picks"
        path = self.folder / f"{m.group(1)}_{kind}.html" if m else None
        if path is None or not path.exists():
            raise FetchError(f"offline fixture missing for {url}")
        return path.read_text("utf-8")


class OfflineOddsApi:
    """Serves `odds_{league}_{scores|odds}.json` from a folder."""

    remaining = None

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _load(self, league: str, kind: str) -> list[dict]:
        path = self.folder / f"odds_{league}_{kind}.json"
        if not path.exists():
            raise OddsApiError(f"offline fixture missing: {path.name}")
        return json.loads(path.read_text("utf-8"))

    def scores(self, league: str) -> list[dict]:
        return self._load(league, "scores")

    def odds(self, league: str) -> list[dict]:
        return self._load(league, "odds")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _shift(now: str, **delta) -> str:
    return (pd.Timestamp(now) + pd.Timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _store(conn, page, now: str) -> None:
    db.upsert_experts(conn, page.experts, now)
    db.upsert_games(conn, page.games, now)
    db.upsert_picks(conn, page.picks, now)
    db.insert_pick_forms(conn, page.forms, now)


def _board_game_id(conn, page, league: str, now: str) -> int | None:
    """Any game on the league's current board, to open its "By Game" page."""
    for row in (page.picks if page else []):
        return row["game_id"]
    for row in (page.games if page else []):
        return row["id"]
    r = conn.execute("SELECT id FROM games WHERE league = ? AND start_time > ? ORDER BY start_time LIMIT 1",
                     (league, now)).fetchone()
    return r[0] if r else None


def _collect_picks(conn, fetcher, league: str, now: str) -> list[Exception]:
    """Picks page first, then the By-Game page (every expert's picks for every game on the board)."""
    errors: list[Exception] = []
    page = None
    try:
        page = parse_picks_page(fetch_picks(fetcher, league), league)
        _store(conn, page, now)
        print(f"[{league}] picks page: experts={len(page.experts)} picks={len(page.picks)}")
    except Exception as e:  # noqa: BLE001 - one league must never stop the others
        errors.append(e)
    game_id = _board_game_id(conn, page, league, now)
    if game_id is not None:
        try:
            board = parse_bygame_page(fetch_bygame(fetcher, league, game_id), league)
            _store(conn, board, now)
            print(f"[{league}] by game: tran={len(board.games)} experts={len(board.experts)} picks={len(board.picks)}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    return errors


def _collect_rules(conn, fetcher, league: str, now: str) -> list[Exception]:
    """Public splits for the leagues that have rules, then log the plays the rules select before kickoff."""
    errors: list[Exception] = []
    try:
        games, splits = parse_public_page(fetch_public(fetcher, league), league)
        db.upsert_games(conn, games, now)
        db.upsert_public(conn, splits, now)
        print(f"[{league}] public: tran={len(games)} dong={len(splits)}")
    except Exception as e:  # noqa: BLE001 - rules still run on the last stored splits
        errors.append(e)
    try:
        print(f"[{league}] quy tac: {sync_rule_plays(conn, now)} keo sap da khop")
    except Exception as e:  # noqa: BLE001
        errors.append(e)
    return errors


def _games(conn, sql: str, params: tuple) -> list[dict]:
    return [dict(r) for r in conn.execute(
        f"SELECT id, start_time, home_name, away_name, odds_event_id FROM games WHERE {sql} AND {_PICKED}", params)]


def _match(games: list[dict], events: list[dict]) -> dict[int, dict]:
    by_id = {e["event_id"]: e for e in events}
    out = {g["id"]: by_id[g["odds_event_id"]] for g in games if g.get("odds_event_id") in by_id}
    rest = [g for g in games if g["id"] not in out]
    taken = {e["event_id"] for e in out.values()}
    out.update(match_events(rest, [e for e in events if e["event_id"] not in taken]))
    return out


def _recent(conn, key: str, now: str, hours: float) -> bool:
    """True when `key` (a meta timestamp) was set less than `hours` before `now`."""
    last = db.get_meta(conn, key)
    return last is not None and pd.Timestamp(last) > pd.Timestamp(now) - pd.Timedelta(hours=hours)


def _collect_odds(conn, api, league: str, now: str, budget: bool = False) -> list[Exception]:
    errors: list[Exception] = []
    upcoming = _games(conn, "league = ? AND start_time > ?", (league, now))
    past = _games(conn, "league = ? AND start_time <= ? AND start_time >= ? "
                        "AND (status IS NULL OR status != 'complete')",
                  (league, _shift(now, hours=-SCORE_DELAY_H), _shift(now, days=-SCORE_WINDOW_D)))
    if budget and upcoming:
        soon = _shift(now, minutes=BUDGET_ODDS_LEAD_MIN)
        if not any(g["start_time"] <= soon for g in upcoming):
            upcoming = []  # no picked game kicks off before the next hourly run
        elif _recent(conn, f"odds_at_{league}", now, BUDGET_ODDS_EVERY_H.get(league, BUDGET_DEFAULT_ODDS_H)):
            print(f"[{league}] odds: vua lay gan day, bo qua")
            upcoming = []
    if budget and past and _recent(conn, f"scores_at_{league}", now,
                                   BUDGET_SCORES_EVERY_H.get(league, BUDGET_DEFAULT_SCORES_H)):
        print(f"[{league}] ti so: vua hoi gan day, bo qua")
        past = []
    if upcoming:
        if api.remaining is not None and api.remaining < MIN_CREDITS_FOR_ODDS:
            print(f"[{league}] bo qua odds: chi con {api.remaining} credit")
        else:
            try:
                lines = parse_lines(api.odds(league))
                events = list({l["event_id"]: l for l in lines}.values())
                matched = _match(upcoming, events)
                by_event: dict[str, list[dict]] = {}
                for l in lines:
                    by_event.setdefault(l["event_id"], []).append(l)
                db.upsert_games(conn, [{"id": gid, "odds_event_id": e["event_id"]} for gid, e in matched.items()], now)
                db.upsert_lines(conn, [{**l, "game_id": gid} for gid, e in matched.items()
                                       for l in by_event[e["event_id"]]], now)
                db.set_meta(conn, f"odds_at_{league}", now)
                print(f"[{league}] odds: {len(matched)}/{len(upcoming)} tran sap da co line")
            except Exception as e:  # noqa: BLE001
                errors.append(e)
    if past:
        try:
            scores = parse_scores(api.scores(league))
            matched = _match(past, scores)
            db.upsert_games(conn, [{
                "id": gid, "odds_event_id": e["event_id"],
                "status": "complete" if e["completed"] else None,
                "home_score": e["home_score"], "away_score": e["away_score"],
            } for gid, e in matched.items()], now)
            db.set_meta(conn, f"scores_at_{league}", now)
            done = sum(1 for e in matched.values() if e["completed"])
            print(f"[{league}] ti so: {done}/{len(past)} tran da qua co ket qua")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    return errors


def _ungraded_past_games(conn, league: str, now: str) -> int:
    return conn.execute(
        f"SELECT count(*) FROM games WHERE league = ? AND start_time <= ? "
        f"AND (status IS NULL OR status != 'complete') AND {_PICKED}",
        (league, _shift(now, hours=-SCORE_DELAY_H))).fetchone()[0]


def run(db_path: Path, report_path: Path, site_dir: Path, leagues: list[str], fetcher, now: str,
        odds_api=None, budget: bool = False) -> int:
    """Exit codes: 0 ok, 1 every league failed, 2 page structure changed, 3 unexpected error,
    4 Excel file open, 5 no The Odds API key."""
    conn = db.connect(db_path)
    failed, parse_failed, unexpected = 0, False, False
    for league in leagues:
        errors = _collect_picks(conn, fetcher, league, now)
        if league in RULE_LEAGUES:
            errors += _collect_rules(conn, fetcher, league, now)
        if odds_api is not None:
            errors += _collect_odds(conn, odds_api, league, now, budget)
        if errors:
            failed += 1
            parse_failed |= any(isinstance(e, ParseError) for e in errors)
            unexpected |= any(not isinstance(e, (FetchError, ParseError, OddsApiError)) for e in errors)
            message = " | ".join(f"{type(e).__name__}: {e}" for e in errors)
            db.mark_league(conn, league, False, now, message)
            print(f"[{league}] LOI: {message}")
        else:
            db.mark_league(conn, league, True, now)
    if odds_api is None:
        print("CANH BAO: chua cau hinh ODDS_API_KEY - chi luu picks, khong co ti so/line.")
    elif odds_api.remaining is not None:
        db.set_meta(conn, "odds_api_remaining", str(odds_api.remaining))
        print(f"The Odds API con {odds_api.remaining} credit.")

    tables = build_tables(conn, now, Path(db_path).parent / "history")
    excel_ok = write_report(tables, report_path)
    if not excel_ok:
        print(f"CANH BAO: {report_path} dang mo trong Excel - dong file roi bam lai de cap nhat Excel.")
    status = [dict(r) | {"ungraded_past_games": _ungraded_past_games(conn, r["league"], now)}
              for r in conn.execute("SELECT * FROM league_status ORDER BY league")]
    remaining = db.get_meta(conn, "odds_api_remaining")
    meta = {"odds_api_remaining": int(remaining) if remaining is not None else None}
    build_site(tables, status, site_dir, report_path, now, meta)
    total = conn.execute("SELECT count(*) FROM picks").fetchone()[0]
    print(f"Tong picks trong DB: {total}. Excel: {report_path}. Dashboard: {site_dir / 'index.html'}")
    conn.close()
    if parse_failed:
        return 2
    if unexpected:
        return 3
    if leagues and failed == len(leagues):
        return 1
    if odds_api is None:
        return 5
    if not excel_ok:
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="actions_tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect picks, scores and lines, grade, analyse and export")
    r.add_argument("--leagues", default=",".join(k for k, on in LEAGUES.items() if on))
    r.add_argument("--db", default="data/actions.db")
    r.add_argument("--report", default="reports/actions_report.xlsx")
    r.add_argument("--site", default="site")
    r.add_argument("--budget", action="store_true",
                   help="hourly schedule: fetch lines only before kickoffs and scores sparingly (saves credits)")
    r.add_argument("--offline", help="folder with {league}_picks.html and odds_{league}_{scores|odds}.json")
    args = ap.parse_args(argv)
    leagues = [x.strip() for x in args.leagues.split(",") if x.strip()]
    if args.offline:
        fetcher, api = OfflineFetcher(Path(args.offline)), OfflineOddsApi(Path(args.offline))
    else:
        key = load_key(Path.cwd())
        fetcher, api = Fetcher(), (OddsApi(key) if key else None)
    return run(Path(args.db), Path(args.report), Path(args.site), leagues, fetcher, utc_now(), api, args.budget)


if __name__ == "__main__":
    sys.exit(main())
