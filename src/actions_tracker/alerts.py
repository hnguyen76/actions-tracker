"""Telegram alert shortly before kickoff: the game-day decision for every game with picks that starts soon.

A scheduled task (scripts/alert_task.py, every 5 minutes) calls `python -m actions_tracker alert`. When a game
with picks kicks off within ALERT_WINDOW_MIN minutes and has not been announced yet, fresh data is collected
first, then one message per kickoff time is sent: every game at that time with its spread / total / moneyline
decision, the same as the "Quyết định" card on the dashboard (totals only with at least TOTAL_MIN_EXPERTS
experts). Credentials live in gitignored files: .telegram_bot_token and .telegram_chat_id.
"""

import html
import os
import sqlite3
from pathlib import Path

import pandas as pd
import requests

from actions_tracker.config import TZ

ALERT_WINDOW_MIN = 18     # the task runs every 5 minutes -> the message arrives about 13-18 minutes before kickoff
TOTAL_MIN_EXPERTS = 5     # same filter as the Total section of the dashboard
TG_LIMIT = 3800           # Telegram allows 4096 characters per message
DASHBOARD = "https://hnguyen76.github.io/actions-tracker/"
TOKEN_FILE, CHAT_FILE = ".telegram_bot_token", ".telegram_chat_id"
_DAY = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
_LEAGUE = {"nfl": "NFL", "ncaaf": "NCAAF", "nba": "NBA"}
_MARKET = {"spread": "Spread", "total": "Total", "ml": "Moneyline"}
_ORDER = {"bet": 0, "paper": 1, "conflict": 2, "skip": 3}

_SCHEMA = "CREATE TABLE IF NOT EXISTS alerts_sent(game_id INTEGER PRIMARY KEY, sent_at TEXT)"


def _iso(ts: pd.Timestamp) -> str:
    return ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.000Z")


def due_games(conn: sqlite3.Connection, now: str, window_min: int = ALERT_WINDOW_MIN) -> list[dict]:
    """Games with picks that start within the window and were not announced yet (no network)."""
    conn.execute(_SCHEMA)
    until = _iso(pd.Timestamp(now) + pd.Timedelta(minutes=window_min))
    rows = conn.execute(
        "SELECT id, league, start_time, home_abbr, away_abbr FROM games g "
        "WHERE start_time > ? AND start_time <= ? AND EXISTS (SELECT 1 FROM picks p WHERE p.game_id = g.id) "
        "AND id NOT IN (SELECT game_id FROM alerts_sent) ORDER BY start_time, league, id", (now, until))
    return [dict(r) for r in rows]


def mark_sent(conn: sqlite3.Connection, game_ids: list[int], now: str) -> None:
    conn.execute(_SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO alerts_sent(game_id, sent_at) VALUES (?, ?)",
                     [(int(g), now) for g in game_ids])
    conn.commit()


def _local(start: str) -> pd.Timestamp:
    return pd.Timestamp(start).tz_convert(TZ)


def _game_lines(game: dict, decisions: pd.DataFrame, experts: dict) -> tuple[list[str], int]:
    """Text lines for one game and how many of them are bets."""
    gid = int(game["id"])
    mine = decisions[decisions["game_id"].astype(int) == gid] if not decisions.empty else decisions
    lines, bets = [], 0
    for r in sorted(mine.itertuples(), key=lambda r: (_ORDER.get(r.action, 9), r.market)):
        n = experts.get((gid, r.market), 0)
        if r.market == "total" and n < TOTAL_MIN_EXPERTS:
            continue
        market = _MARKET.get(r.market, r.market)
        pick = html.escape(str(r.pick))
        if r.action == "bet":
            bets += 1
            lines.append(f"✅ {market}: <b>{pick}</b> · {n} expert · ĐẶT {r.stake_u:g}u")
        elif r.action == "paper":
            lines.append(f"📝 {market}: {pick} · {n} expert")
        elif r.action == "conflict":
            lines.append(f"⚠️ {market}: {pick} · {n} expert · hai quy tắc ngược nhau, bỏ qua")
        else:
            lines.append(f"▫️ {market}: {pick} · {n} expert · bỏ qua")
        if r.action in ("bet", "paper") and r.reason:
            reason = str(r.reason)
            lines.append(f"    <i>{html.escape(reason if len(reason) <= 160 else reason[:157] + '…')}</i>")
    if not lines:
        n = max((v for (g, _), v in experts.items() if g == gid), default=0)
        lines.append(f"▫️ Không có kèo đủ điều kiện ({n} expert pick)")
    return lines, bets


def build_messages(games: list[dict], tables: dict, now: str) -> list[str]:
    """One message per kickoff time (split if it would exceed Telegram's limit)."""
    decisions = tables.get("Decisions", pd.DataFrame())
    board = tables.get("Upcoming_Board", pd.DataFrame())
    experts = ({(int(r.game_id), r.market): int(r.total_votes) for r in board.itertuples()}
               if board is not None and not board.empty else {})
    messages = []
    for start, group in pd.DataFrame(games).groupby("start_time", sort=True):
        local = _local(start)
        mins = max(0, round((pd.Timestamp(start) - pd.Timestamp(now)).total_seconds() / 60))
        blocks, bets = [], 0
        for game in group.to_dict("records"):
            lines, b = _game_lines(game, decisions, experts)
            bets += b
            title = f"<b>{_LEAGUE.get(game['league'], game['league'].upper())} · " \
                    f"{html.escape(game['away_abbr'])} @ {html.escape(game['home_abbr'])}</b>"
            blocks.append("\n".join([title, *lines]))
        head = (f"⏰ <b>{local:%H:%M} ET {_DAY[local.day_of_week]} {local:%d/%m}</b> — còn {mins} phút · "
                f"{len(blocks)} trận")
        foot = DASHBOARD
        chunk = [head]
        for block in blocks:
            if len("\n\n".join(chunk + [block, foot])) > TG_LIMIT and len(chunk) > 1:
                messages.append("\n\n".join(chunk))
                chunk = [head + " (tiếp)"]
            chunk.append(block)
        messages.append("\n\n".join(chunk + [foot]))
    return messages


def load_telegram(root: Path) -> tuple[str | None, str | None]:
    def read(env: str, name: str) -> str | None:
        v = os.environ.get(env, "").strip()
        if v:
            return v
        p = Path(root) / name
        return (p.read_text("utf-8").strip() or None) if p.exists() else None
    return read("TELEGRAM_BOT_TOKEN", TOKEN_FILE), read("TELEGRAM_CHAT_ID", CHAT_FILE)


class TelegramError(Exception):
    pass


def send_telegram(token: str, chat_id: str, text: str, post=requests.post) -> None:
    try:
        r = post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                 data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
    except requests.RequestException as e:  # never echo the URL: it carries the token
        raise TelegramError(type(e).__name__) from None
    if r.status_code != 200:
        raise TelegramError(f"HTTP {r.status_code}: {r.text[:200]}")


def find_chat_id(token: str, get=requests.get) -> str | None:
    """Chat id of the newest message sent to the bot (the user presses Start / sends any text first)."""
    try:
        r = get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    except requests.RequestException as e:
        raise TelegramError(type(e).__name__) from None
    if r.status_code != 200:
        raise TelegramError(f"HTTP {r.status_code}")
    chats = [u.get("message", {}).get("chat", {}).get("id") for u in r.json().get("result", [])]
    chats = [c for c in chats if c is not None]
    return str(chats[-1]) if chats else None


# --- a market just reached RISE_PICKS experts --------------------------------------------------------------
RISE_PICKS = 5
HEAVY_PICKS = 10  # every rising-picks message also lists all upcoming markets with at least this many picks
_RISE_SCHEMA = ("CREATE TABLE IF NOT EXISTS pick_rise_alerts(game_id INTEGER, market TEXT, threshold INTEGER, "
                "votes TEXT, sent_at TEXT, PRIMARY KEY(game_id, market, threshold))")
_SIDE = {"home": None, "away": None, "over": "Over", "under": "Under"}


def rising_markets(conn: sqlite3.Connection, board: pd.DataFrame, now: str, threshold: int = RISE_PICKS) -> list[dict]:
    """Upcoming game x market that now has >= threshold experts and was not reported yet."""
    conn.execute(_RISE_SCHEMA)
    if board is None or board.empty:
        return []
    seen = {(r[0], r[1]) for r in conn.execute("SELECT game_id, market FROM pick_rise_alerts WHERE threshold = ?",
                                                (threshold,))}
    up = board[(board["total_votes"] >= threshold) & (board["start_time"].astype(str) > now)]
    return [r for r in up.to_dict("records") if (int(r["game_id"]), r["market"]) not in seen]


def mark_rising(conn: sqlite3.Connection, rows: list[dict], now: str, threshold: int = RISE_PICKS) -> None:
    conn.execute(_RISE_SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO pick_rise_alerts(game_id, market, threshold, votes, sent_at) "
                     "VALUES (?, ?, ?, ?, ?)",
                     [(int(r["game_id"]), r["market"], threshold, f"{r['a_votes']}-{r['b_votes']}", now) for r in rows])
    conn.commit()


def _side(r: dict, k: str) -> str:
    side = r[f"{k}_side"]
    name = r["home_abbr"] if side == "home" else r["away_abbr"] if side == "away" else _SIDE.get(side) or side
    line = r.get(f"{k}_line")
    if line is None or pd.isna(line) or r["market"] == "ml":
        return f"{name} {int(r[f'{k}_votes'])}"
    ln = f"+{line:g}" if r["market"] == "spread" and line > 0 else f"{line:g}"
    return f"{name} {ln.replace('.', ',')} {int(r[f'{k}_votes'])}"


def _market_block(r: dict) -> str:
    local = _local(r["start_time"])
    return (f"<b>{_LEAGUE.get(r['league'], r['league'].upper())} · {html.escape(r['away_abbr'])} @ "
            f"{html.escape(r['home_abbr'])}</b> — {local:%H:%M} {_DAY[local.day_of_week]} {local:%d/%m}\n"
            f"{_MARKET.get(r['market'], r['market'])}: {html.escape(_side(r, 'a'))} · {html.escape(_side(r, 'b'))} "
            f"({int(r['total_votes'])} picks)")


def _by_time(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["start_time"], r["league"], r["market"]))


def rising_messages(rows: list[dict], threshold: int = RISE_PICKS, heavy: list[dict] | None = None) -> list[str]:
    head = f"📈 <b>Kèo vừa lên ≥ {threshold} picks</b> · {len(rows)} kèo"
    blocks = [_market_block(r) for r in _by_time(rows)]
    if heavy is not None:
        blocks.append(f"🔥 <b>Kèo đang ≥ {HEAVY_PICKS} picks</b> · {len(heavy)} kèo"
                      + ("" if heavy else "\nChưa có kèo nào."))
        blocks += [_market_block(r) for r in _by_time(heavy)]
    messages, chunk = [], [head]
    for block in blocks:
        if len("\n\n".join(chunk + [block, DASHBOARD])) > TG_LIMIT and len(chunk) > 1:
            messages.append("\n\n".join(chunk))
            chunk = [head + " (tiếp)"]
        chunk.append(block)
    messages.append("\n\n".join(chunk + [DASHBOARD]))
    return messages


def notify_rising(conn: sqlite3.Connection, board: pd.DataFrame, now: str, telegram: tuple[str | None, str | None],
                  post=requests.post) -> int:
    """Send the markets that just reached RISE_PICKS experts. The first run only records what is already there
    (no flood of old markets). Returns how many markets were reported."""
    token, chat = telegram
    if not token or not chat:
        return 0
    conn.execute(_RISE_SCHEMA)
    first = conn.execute("SELECT count(*) FROM pick_rise_alerts").fetchone()[0] == 0 and \
        db_meta(conn, "pick_rise_started") is None
    rows = rising_markets(conn, board, now)
    if first:
        mark_rising(conn, rows, now)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('pick_rise_started', ?)", (now,))
        conn.commit()
        return 0
    if not rows:
        return 0
    heavy = [] if board is None or board.empty else board[
        (board["total_votes"] >= HEAVY_PICKS) & (board["start_time"].astype(str) > now)].to_dict("records")
    for text in rising_messages(rows, heavy=heavy):
        send_telegram(token, chat, text, post=post)
    mark_rising(conn, rows, now)
    return len(rows)


def db_meta(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None
