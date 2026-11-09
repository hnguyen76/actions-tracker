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
from actions_tracker.fetch import FetchError, Fetcher, fetch_league
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


def run(db_path: Path, report_path: Path, site_dir: Path, leagues: list[str], fetcher, now: str) -> int:
    conn = db.connect(db_path)
    failed, parse_failed = 0, False
    for league in leagues:
        try:
            html, scoreboard = fetch_league(fetcher, league)
            page = parse_picks_page(html, league)
            board = parse_scoreboard(scoreboard, league)
        except (FetchError, ParseError) as e:
            failed += 1
            parse_failed |= isinstance(e, ParseError)
            db.mark_league(conn, league, False, now, f"{type(e).__name__}: {e}")
            print(f"[{league}] LOI: {type(e).__name__}: {e}")
            continue
        db.upsert_experts(conn, page.experts, now)
        db.upsert_games(conn, page.games, now)
        db.upsert_games(conn, board.games, now)
        db.upsert_picks(conn, page.picks, now)
        db.upsert_lines(conn, board.lines, now)
        db.mark_league(conn, league, True, now)
        print(f"[{league}] experts={len(page.experts)} picks={len(page.picks)} "
              f"games={len(board.games)} lines={len(board.lines)}")

    tables = build_tables(conn, now)
    write_report(tables, report_path)
    status = [dict(r) for r in conn.execute("SELECT * FROM league_status ORDER BY league")]
    build_site(tables, status, site_dir, report_path, now)
    total = conn.execute("SELECT count(*) FROM picks").fetchone()[0]
    print(f"Tong picks trong DB: {total}. Excel: {report_path}. Dashboard: {site_dir / 'index.html'}")
    conn.close()
    if parse_failed:
        return 2
    if leagues and failed == len(leagues):
        return 1
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
