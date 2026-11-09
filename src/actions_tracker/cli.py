"""`python -m actions_tracker run` — collect, grade, analyse, export (spec §4, §10)."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from actions_tracker import db
from actions_tracker.analysis import build_tables
from actions_tracker.build_site import build_site
from actions_tracker.config import LEAGUES
from actions_tracker.export_excel import write_report
from actions_tracker.backfill import backfill_queries, stale_games
from actions_tracker.fetch import FetchError, Fetcher, fetch_picks, fetch_scoreboard
from actions_tracker.parse import ParseError, parse_picks_page, parse_scoreboard


class OfflineFetcher:
    """Serves `{league}_picks.html` / `{league}_scoreboard.json` from a folder instead of the network."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _file(self, url: str) -> Path:
        m = re.search(r"/scoreboard/([a-z]+)", url) or re.search(r"\.com/([a-z]+)/picks", url)
        kind = "scoreboard.json" if "/scoreboard/" in url else "picks.html"
        path = self.folder / f"{m.group(1)}_{kind}" if m else None
        if path is None or not path.exists():
            raise FetchError(f"offline fixture missing for {url}")
        return path

    def get_text(self, url: str) -> str:
        return self._file(url).read_text("utf-8")

    def get_json(self, url: str) -> dict:
        return json.loads(self._file(url).read_text("utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _collect(conn, fetcher, league: str, now: str) -> list[Exception]:
    """Picks page and scoreboard are stored independently, so one failing never discards the other."""
    errors: list[Exception] = []
    try:
        page = parse_picks_page(fetch_picks(fetcher, league), league)
        db.upsert_experts(conn, page.experts, now)
        db.upsert_games(conn, page.games, now)
        db.upsert_picks(conn, page.picks, now)
        print(f"[{league}] experts={len(page.experts)} picks={len(page.picks)}")
    except Exception as e:  # noqa: BLE001 - one league must never stop the others
        errors.append(e)
    try:
        board = parse_scoreboard(fetch_scoreboard(fetcher, league), league)
        db.upsert_games(conn, board.games, now)
        db.upsert_lines(conn, board.lines, now)
        print(f"[{league}] scoreboard games={len(board.games)} lines={len(board.lines)}")
    except Exception as e:  # noqa: BLE001
        errors.append(e)
    for query in backfill_queries(conn, league, now):
        try:
            past = parse_scoreboard(fetch_scoreboard(fetcher, league, query), league)
            db.upsert_games(conn, past.games, now)  # scores only; lines are frozen after kickoff anyway
            print(f"[{league}] bo sung ket qua {query}: {len(past.games)} tran")
        except Exception as e:  # noqa: BLE001 - missing past scores show up as ungraded_past_games
            print(f"[{league}] khong lay duoc ket qua {query}: {type(e).__name__}: {e}")
    return errors


def _ungraded_past_games(conn, league: str, now: str) -> int:
    ids = [g["id"] for g in stale_games(conn, league, now)]
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    return conn.execute(f"SELECT count(DISTINCT game_id) FROM picks WHERE game_id IN ({marks})", ids).fetchone()[0]


def run(db_path: Path, report_path: Path, site_dir: Path, leagues: list[str], fetcher, now: str) -> int:
    """Exit codes: 0 ok, 1 every league failed, 2 page structure changed, 3 unexpected error, 4 Excel file open."""
    conn = db.connect(db_path)
    failed, parse_failed, unexpected = 0, False, False
    for league in leagues:
        errors = _collect(conn, fetcher, league, now)
        if errors:
            failed += 1
            parse_failed |= any(isinstance(e, ParseError) for e in errors)
            unexpected |= any(not isinstance(e, (FetchError, ParseError)) for e in errors)
            message = " | ".join(f"{type(e).__name__}: {e}" for e in errors)
            db.mark_league(conn, league, False, now, message)
            print(f"[{league}] LOI: {message}")
        else:
            db.mark_league(conn, league, True, now)

    tables = build_tables(conn, now)
    excel_ok = write_report(tables, report_path)
    if not excel_ok:
        print(f"CANH BAO: {report_path} dang mo trong Excel - dong file roi bam lai de cap nhat Excel.")
    status = [dict(r) | {"ungraded_past_games": _ungraded_past_games(conn, r["league"], now)}
              for r in conn.execute("SELECT * FROM league_status ORDER BY league")]
    build_site(tables, status, site_dir, report_path, now)
    total = conn.execute("SELECT count(*) FROM picks").fetchone()[0]
    print(f"Tong picks trong DB: {total}. Excel: {report_path}. Dashboard: {site_dir / 'index.html'}")
    conn.close()
    if parse_failed:
        return 2
    if unexpected:
        return 3
    if leagues and failed == len(leagues):
        return 1
    if not excel_ok:
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="actions_tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect picks, grade, analyse and export")
    r.add_argument("--leagues", default=",".join(k for k, on in LEAGUES.items() if on))
    r.add_argument("--db", default="data/actions.db")
    r.add_argument("--report", default="reports/actions_report.xlsx")
    r.add_argument("--site", default="site")
    r.add_argument("--offline", help="folder with {league}_picks.html / {league}_scoreboard.json")
    args = ap.parse_args(argv)
    leagues = [x.strip() for x in args.leagues.split(",") if x.strip()]
    fetcher = OfflineFetcher(Path(args.offline)) if args.offline else Fetcher()
    return run(Path(args.db), Path(args.report), Path(args.site), leagues, fetcher, utc_now())


if __name__ == "__main__":
    sys.exit(main())
