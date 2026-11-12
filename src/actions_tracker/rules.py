"""Frozen betting rules, logged before kickoff and graded after (forward test / paper trading).

The three rules were chosen on 2026-11-12 from the season history (NCAAF weeks 1-10) and must not be tuned
while they are being tested. Each run re-evaluates the upcoming games; the last evaluation before a game
starts is the one that counts (same policy as closing lines). History used pick counts from the By-Game
cards; live uses one vote per expert, so the forward test is also a check that the rule survives that change.
"""

import sqlite3

import pandas as pd

from actions_tracker.analysis.consensus import consensus_games
from actions_tracker.config import MONEY_TICKET_GAP, NIGHT_HOUR, TZ
from actions_tracker.grading import load_graded_picks, opposite

RULES = [
    {"id": "ncaaf_total_day_fade", "league": "ncaaf", "market": "total",
     "name": "NCAAF total ban ngày: đánh ngược consensus",
     "how": "Trận đá trước 19:00 giờ miền Đông, kèo total có đa số expert (≥ 3) về một bên → đặt bên còn lại.",
     "hist_wins": 56, "hist_losses": 35},
    {"id": "ncaaf_total_money", "league": "ncaaf", "market": "total",
     "name": "NCAAF total: theo side có tiền lớn",
     "how": f"Kèo total có % tiền cao hơn % số bet từ {MONEY_TICKET_GAP} điểm ở một bên → đặt bên đó.",
     "hist_wins": 91, "hist_losses": 60},
    {"id": "ncaaf_spread_away_dog_fade", "league": "ncaaf", "market": "spread",
     "name": "NCAAF spread: đánh ngược consensus đội khách underdog",
     "how": "Đa số expert (≥ 3) chọn spread đội khách và đội khách là underdog → đặt đội nhà (favorite).",
     "hist_wins": 74, "hist_losses": 54},
]
RULE_LEAGUES = sorted({r["league"] for r in RULES})


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def evaluate(conn: sqlite3.Connection, now: str) -> list[dict]:
    """Plays the rules select right now among games that have not started."""
    games = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, league, start_time, home_abbr, away_abbr FROM games WHERE start_time > ?", (now,))}
    splits = {(r["game_id"], r["market"], r["side"]): dict(r) for r in conn.execute("SELECT * FROM public_splits")}
    picks = load_graded_picks(conn)
    if not picks.empty:
        picks = picks[picks["game_id"].isin(games)]
    cg = consensus_games(picks)

    def expert_line(game_id, market, side=None):
        rows = picks[(picks["game_id"] == game_id) & (picks["market"] == market)]
        if side is not None:
            rows = rows[rows["pick_side"] == side]
        return _num(pd.to_numeric(rows["line"], errors="coerce").median()) if len(rows) else None

    def split(game_id, market, side, field):
        return _num((splits.get((game_id, market, side)) or {}).get(field))

    plays: list[dict] = []

    def add(rule_id, game_id, market, bet_side, line, basis):
        odds = split(game_id, market, bet_side, "odds")
        plays.append({"rule_id": rule_id, "game_id": int(game_id), "market": market, "bet_side": bet_side,
                      "line": line, "odds": None if odds is None else int(odds), "basis": basis})

    for r in cg.itertuples():
        game = games[r.game_id]
        if game["league"] != "ncaaf":
            continue
        votes = f"{r.votes}/{r.total_votes}"
        if r.market == "total":
            hour = pd.Timestamp(game["start_time"]).tz_convert(TZ).hour
            if hour < NIGHT_HOUR:
                bet = opposite(r.side)
                line = split(r.game_id, "total", bet, "line")
                add("ncaaf_total_day_fade", r.game_id, "total", bet,
                    line if line is not None else expert_line(r.game_id, "total"),
                    f"consensus {r.side} {votes} · đá {hour}h ET")
        elif r.market == "spread" and r.side == "away":
            away_line = split(r.game_id, "spread", "away", "line")
            if away_line is None:
                away_line = expert_line(r.game_id, "spread", "away")
            if away_line is not None and away_line > 0:
                home_line = split(r.game_id, "spread", "home", "line")
                add("ncaaf_spread_away_dog_fade", r.game_id, "spread", "home",
                    home_line if home_line is not None else -away_line,
                    f"consensus {game['away_abbr']} +{away_line:g} {votes}")

    for game_id, game in games.items():
        if game["league"] != "ncaaf":
            continue
        for side in ("over", "under"):
            tickets, money = split(game_id, "total", side, "tickets_pct"), split(game_id, "total", side, "money_pct")
            if tickets is not None and money is not None and money - tickets >= MONEY_TICKET_GAP:
                add("ncaaf_total_money", game_id, "total", side, split(game_id, "total", side, "line"),
                    f"{side}: {tickets:g}% số bet · {money:g}% tiền")
    return plays


def sync_rule_plays(conn: sqlite3.Connection, now: str) -> int:
    """Make rule_plays match the current evaluation for games that have not started; started games are frozen."""
    plays = evaluate(conn, now)
    keep = {(p["rule_id"], p["game_id"], p["market"]) for p in plays}
    open_rows = conn.execute(
        "SELECT r.rule_id, r.game_id, r.market FROM rule_plays r JOIN games g ON g.id = r.game_id "
        "WHERE g.start_time > ?", (now,)).fetchall()
    gone = [tuple(r) for r in open_rows if tuple(r) not in keep]
    conn.executemany("DELETE FROM rule_plays WHERE rule_id = ? AND game_id = ? AND market = ?", gone)
    conn.executemany(
        """INSERT INTO rule_plays(rule_id, game_id, market, bet_side, line, odds, basis, first_logged_at, logged_at)
           VALUES (:rule_id, :game_id, :market, :bet_side, :line, :odds, :basis, :now, :now)
           ON CONFLICT(rule_id, game_id, market) DO UPDATE SET
             bet_side=excluded.bet_side, line=excluded.line, odds=excluded.odds, basis=excluded.basis,
             logged_at=excluded.logged_at""",
        [p | {"now": now} for p in plays])
    conn.commit()
    return len(plays)
