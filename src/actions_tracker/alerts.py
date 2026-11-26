"""Telegram alert shortly before kickoff: the game-day decision for every game with picks that starts soon.

A scheduled task (scripts/alert_task.py, every 5 minutes) calls `python -m actions_tracker alert`. When a game
with picks kicks off within ALERT_WINDOW_MIN minutes and has not been announced yet, fresh data is collected
first, then one message per kickoff time is sent: every game at that time with its spread / total / moneyline
decision, the same as the "Quyết định" card on the dashboard (rule/consensus totals need
TOTAL_MIN_EXPERTS; the user's weekday method can start at two majority-side experts). Credentials live in
gitignored files: .telegram_bot_token and .telegram_chat_id.
"""

import html
import os
import re
import sqlite3
import time
from pathlib import Path

import pandas as pd
import requests

from actions_tracker.config import TZ

ALERT_WINDOW_MIN = 18     # the task runs every 5 minutes -> the message arrives about 13-18 minutes before kickoff
TOTAL_MIN_EXPERTS = 5     # same filter as the Total section of the dashboard
TG_LIMIT = 3800           # Telegram allows 4096 characters per message
TG_SEND_ATTEMPTS = 3      # keep a transient network/rate-limit error from losing the pregame alert
TG_RETRY_MAX_S = 30       # stay below the scheduled task's stale-lock window
LATE_GAME_MIN = 5         # a live lean only joins the daily recap in the last five minutes of Q4 or in OT
DOMINANT_DAY_PCT = 80     # call out a strongly one-sided day in the last-game alert
DASHBOARD = "https://hnguyen76.github.io/actions-tracker/"
TOKEN_FILE, CHAT_FILE = ".telegram_bot_token", ".telegram_chat_id"
_DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_LEAGUE = {"nfl": "NFL", "ncaaf": "NCAAF", "nba": "NBA"}
_MARKET = {"spread": "Spread", "total": "Total", "ml": "Moneyline"}
_ORDER = {"bet": 0, "paper": 1, "conflict": 2, "skip": 3}

_SCHEMA = "CREATE TABLE IF NOT EXISTS alerts_sent(game_id INTEGER PRIMARY KEY, sent_at TEXT)"
DELIVERY_ERROR_KEY = "telegram_alert_error"


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


def record_delivery_error(conn: sqlite3.Connection, now: str, error: Exception) -> None:
    """Persist a safe, short diagnostic so an unattended phone failure can be inspected remotely."""
    value = f"{now}|{str(error)[:200]}"
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (DELIVERY_ERROR_KEY, value))
    conn.commit()


def clear_delivery_error(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM meta WHERE key = ?", (DELIVERY_ERROR_KEY,))
    conn.commit()


def _local(start: str) -> pd.Timestamp:
    return pd.Timestamp(start).tz_convert(TZ)


def _table(tables: dict, name: str) -> pd.DataFrame:
    value = tables.get(name)
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _last_slot(start: str, tables: dict) -> bool:
    """Whether this kickoff is the latest picked game on its Eastern calendar day."""
    day = _local(start).strftime("%Y-%m-%d")
    source = _table(tables, "Picks")
    if source.empty or "start_time" not in source:
        source = _table(tables, "Decision_Method")
    starts = []
    for value in source.get("start_time", pd.Series(dtype=object)).dropna().astype(str).unique():
        try:
            if _local(value).strftime("%Y-%m-%d") == day:
                starts.append(pd.Timestamp(value))
        except (TypeError, ValueError):
            continue
    return bool(starts) and pd.Timestamp(start) == max(starts)


def _clock_seconds(value) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not match or int(match.group(2)) >= 60:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _late_live(row, situation=None) -> bool:
    """Final, OT, or no more than LATE_GAME_MIN minutes left in the fourth quarter."""
    if str(getattr(row, "state", "")).lower() == "final":
        return True
    info = situation if isinstance(situation, dict) else {}
    period, clock = info.get("period"), info.get("clock")
    try:
        period = int(period) if period is not None else None
    except (TypeError, ValueError):
        period = None
    detail = str(getattr(row, "detail", "") or "")
    if period is None:
        if re.search(r"\b(?:OT|overtime)\b", detail, re.I):
            period = 5
        elif re.search(r"\b4(?:th|Q)\b|\bQ4\b", detail, re.I):
            period = 4
    if clock is None:
        match = re.search(r"\b(\d{1,2}:\d{2})\b", detail)
        clock = match.group(1) if match else None
    seconds = _clock_seconds(clock)
    return bool(period and (period > 4 or (period == 4 and seconds is not None and seconds <= LATE_GAME_MIN * 60)))


def _day_record(tables: dict, final_start: str) -> dict[str, int]:
    """Results before the last game: graded selections plus live selections very near the finish.

    A game can have separate spread/total/moneyline selections, so the denominator is explicitly the number
    of selections whose outcome is already known or strongly indicated late in the game.
    """
    plays = _table(tables, "Decision_Method")
    result = {"wins": 0, "losses": 0, "pushes": 0, "late_live": 0}
    needed = {"game_id", "market", "start_time", "result"}
    if plays.empty or not needed.issubset(plays.columns):
        return result
    day = _local(final_start).strftime("%Y-%m-%d")
    prior = plays[(plays["start_time"].astype(str) < final_start)].copy()
    if "et_date" in prior:
        prior = prior[prior["et_date"].astype(str) == day]
    else:
        prior = prior[prior["start_time"].map(lambda value: _local(value).strftime("%Y-%m-%d") == day)]
    prior = prior.drop_duplicates(["game_id", "market"], keep="last")

    in_play = _table(tables, "In_Play")
    if not in_play.empty and "source" in in_play:
        in_play = in_play[in_play["source"] == "Cách của bạn"]
    live_by_key = {(int(r.game_id), str(r.market)): r for r in in_play.itertuples()} if not in_play.empty else {}
    scores = _table(tables, "Scores")
    situations = ({int(r.game_id): r.situation for r in scores.itertuples()}
                  if not scores.empty and {"game_id", "situation"}.issubset(scores.columns) else {})

    for play in prior.itertuples():
        outcome = play.result if isinstance(play.result, str) else None
        if outcome not in ("win", "loss", "push"):
            live = live_by_key.get((int(play.game_id), str(play.market)))
            if live is None or not _late_live(live, situations.get(int(play.game_id))):
                continue
            outcome = live.now if isinstance(live.now, str) else None
            if outcome in ("win", "loss", "push"):
                result["late_live"] += 1
        if outcome == "win":
            result["wins"] += 1
        elif outcome == "loss":
            result["losses"] += 1
        elif outcome == "push":
            result["pushes"] += 1
    return result


def _last_game_note(start: str, group_size: int, tables: dict) -> list[str]:
    if not _last_slot(start, tables):
        return []
    label = "TRẬN CUỐI TRONG NGÀY" if group_size == 1 else "KHUNG GIỜ CUỐI TRONG NGÀY"
    lines = [f"🏁 <b>{label}</b>"]
    record = _day_record(tables, start)
    decided = record["wins"] + record["losses"]
    if not decided:
        return lines + ["📊 Chưa có kèo trước đó đủ kết quả để tính tỷ lệ."]
    win_pct = round(record["wins"] * 100 / decided)
    loss_pct = 100 - win_pct
    live = f" · gồm {record['late_live']} kèo gần hết giờ" if record["late_live"] else ""
    pushes = f" · {record['pushes']} push" if record["pushes"] else ""
    lines.append(f"📊 Trước trận cuối: {record['wins']} thắng · {record['losses']} thua{pushes} — "
                 f"thắng {win_pct}% / thua {loss_pct}%{live}")
    dominant, pct = ("thắng", win_pct) if win_pct >= loss_pct else ("thua", loss_pct)
    if pct >= DOMINANT_DAY_PCT:
        icon = "🟢" if dominant == "thắng" else "🔴"
        lines.append(f"{icon} <b>Hôm nay {dominant} chiếm đa số: {pct}%</b>")
    return lines


def _game_lines(game: dict, decisions: pd.DataFrame, experts: dict) -> tuple[list[str], int]:
    """Text lines for one game and how many of them are bets."""
    gid = int(game["id"])
    mine = decisions[decisions["game_id"].astype(int) == gid] if not decisions.empty else decisions
    lines, bets = [], 0
    for r in sorted(mine.itertuples(), key=lambda r: (_ORDER.get(r.action, 9), r.market)):
        n = experts.get((gid, r.market), 0)
        if r.market == "total" and n < TOTAL_MIN_EXPERTS and r.action != "mine":
            continue
        market = _MARKET.get(r.market, r.market)
        pick = html.escape(str(r.pick))
        if r.action == "bet":
            bets += 1
            lines.append(f"✅ {market}: <b>{pick}</b> · {n} expert · ĐẶT {r.stake_u:g}u")
        elif r.action == "mine":
            lines.append(f"⭐ {market}: <b>{pick}</b> · {n} expert")
        elif r.action == "paper":
            lines.append(f"📝 {market}: {pick} · {n} expert")
        elif r.action == "conflict":
            lines.append(f"⚠️ {market}: {pick} · {n} expert · hai quy tắc ngược nhau, bỏ qua")
        else:
            lines.append(f"▫️ {market}: {pick} · {n} expert · bỏ qua")
        if r.action in ("bet", "mine", "paper") and r.reason:
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
        chunk = [head, *_last_game_note(start, len(blocks), tables)]
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


def _retry_delay(response, attempt: int) -> float:
    """Telegram includes a precise delay for HTTP 429; otherwise use a short exponential backoff."""
    fallback = 2 ** attempt
    try:
        delay = float(response.json().get("parameters", {}).get("retry_after", fallback))
    except (AttributeError, TypeError, ValueError):
        delay = fallback
    return min(TG_RETRY_MAX_S, max(0, delay))


def send_telegram(token: str, chat_id: str, text: str, post=requests.post, sleep=time.sleep) -> None:
    """Send once successfully, retrying only failures that can recover without changing credentials."""
    last_error = ""
    for attempt in range(TG_SEND_ATTEMPTS):
        try:
            r = post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                     data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": "true"})
        except requests.RequestException as e:  # never echo the URL: it carries the token
            last_error = type(e).__name__
            if attempt + 1 < TG_SEND_ATTEMPTS:
                sleep(_retry_delay(None, attempt))
                continue
            raise TelegramError(last_error) from None
        if r.status_code == 200:
            return
        last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        if (r.status_code == 429 or r.status_code >= 500) and attempt + 1 < TG_SEND_ATTEMPTS:
            sleep(_retry_delay(r, attempt))
            continue
        raise TelegramError(last_error)
    raise TelegramError(last_error)


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


# --- ESPN spread changed from plus to minus ---------------------------------------------------------------
_SPREAD_FLIP_SCHEMA = ("CREATE TABLE IF NOT EXISTS spread_flip_alerts(game_id INTEGER, side TEXT, sent_at TEXT, "
                       "PRIMARY KEY(game_id, side))")


def due_spread_flips(conn: sqlite3.Connection, flips: pd.DataFrame | None, now: str) -> list[dict]:
    """Upcoming spread sides first seen above zero and now below zero, not announced before."""
    conn.execute(_SPREAD_FLIP_SCHEMA)
    if flips is None or flips.empty:
        return []
    seen = {(int(r[0]), str(r[1])) for r in conn.execute("SELECT game_id, side FROM spread_flip_alerts")}
    rows = flips[flips["start_time"].astype(str) > now].to_dict("records")
    unique = {}
    for row in rows:
        key = (int(row["game_id"]), str(row["side"]))
        if key not in seen:
            unique[key] = row
    return sorted(unique.values(), key=lambda r: (r["start_time"], r["league"], r["game_id"], r["side"]))


def mark_spread_flips(conn: sqlite3.Connection, rows: list[dict], now: str) -> None:
    conn.execute(_SPREAD_FLIP_SCHEMA)
    conn.executemany("INSERT OR IGNORE INTO spread_flip_alerts(game_id, side, sent_at) VALUES (?, ?, ?)",
                     [(int(r["game_id"]), str(r["side"]), now) for r in rows])
    conn.commit()


def _signed_line(value) -> str:
    number = float(value)
    text = f"{number:+g}" if number != 0 else "0"
    return text.replace("-", "−").replace(".", ",")


def _flip_time(value: str) -> str:
    return _local(value).strftime("%H:%M")


def spread_flip_messages(rows: list[dict]) -> list[str]:
    """Build compact messages; the opening value is the first line observed by S21."""
    head = f"⚠️ <b>Spread + → −</b> · {len(rows)} trận"
    blocks = []
    for row in rows:
        local = _local(row["start_time"])
        team = html.escape(str(row["team"]))
        blocks.append(
            f"<b>{_LEAGUE.get(row['league'], str(row['league']).upper())} · "
            f"{html.escape(str(row['away_abbr']))} @ {html.escape(str(row['home_abbr']))}</b> — "
            f"{local:%H:%M} {_DAY[local.day_of_week]} {local:%d/%m}\n"
            f"🔄 <b>{team} {_signed_line(row['open_line'])} → {_signed_line(row['current_line'])}</b> · "
            f"dịch {_signed_line(row['move'])}\n"
            f"S21 thấy đầu {_flip_time(row['first_seen_at'])} · đổi dấu {_flip_time(row['crossed_at'])} ET"
        )
    messages, chunk = [], [head]
    for block in blocks:
        if len("\n\n".join(chunk + [block, DASHBOARD])) > TG_LIMIT and len(chunk) > 1:
            messages.append("\n\n".join(chunk + [DASHBOARD]))
            chunk = [head + " (tiếp)"]
        chunk.append(block)
    messages.append("\n\n".join(chunk + [DASHBOARD]))
    return messages


def notify_spread_flips(conn: sqlite3.Connection, flips: pd.DataFrame | None, now: str,
                        telegram: tuple[str | None, str | None], post=requests.post) -> int:
    """Alert once per game/side after ESPN snapshots cross from a positive to a negative spread."""
    token, chat = telegram
    if not token or not chat:
        return 0
    rows = due_spread_flips(conn, flips, now)
    if not rows:
        return 0
    for text in spread_flip_messages(rows):
        send_telegram(token, chat, text, post=post)
    mark_spread_flips(conn, rows, now)
    return len(rows)


def db_meta(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


# --- 2H: the user's halftime method (tracked, not a bet), sent once when a game is seen at halftime -----------
_H2_SCHEMA = ("CREATE TABLE IF NOT EXISTS second_half_alerts(game_id INTEGER, market TEXT, sent_at TEXT, "
              "PRIMARY KEY(game_id, market))")


def _h2_num(v) -> str:
    return f"{float(v):g}".replace(".", ",")


def _h2_signed(v) -> str:
    return ("+" if float(v) > 0 else "") + _h2_num(v)


def due_second_half(conn: sqlite3.Connection, now: str) -> list[dict]:
    """2H plays decided at the halftime seen in this run (snapshot saved now) that were not sent yet.
    Snapshots from earlier runs are left alone, so old games are never announced late."""
    from actions_tracker.analysis.second_half import second_half_plays
    conn.execute(_H2_SCHEMA)
    plays = second_half_plays(conn)
    if plays.empty:
        return []
    sent = {(int(g), m) for g, m in conn.execute("SELECT game_id, market FROM second_half_alerts")}
    fresh = plays[(plays["captured_at"].astype(str) == now) & (plays["result"] == "pending")]
    return [r for r in fresh.to_dict("records") if (int(r["game_id"]), r["market"]) not in sent]


def second_half_message(rows: list[dict]) -> str:
    """One game: 1H score, then the 2H spread / total picks with the first-half result behind each."""
    first = rows[0]
    source = html.escape(str(first.get("second_source") or "ESPN"))
    away_1h, home_1h = (int(x) for x in str(first["score_1h"]).split("-"))
    head = (f"⏸ <b>2H · {_LEAGUE.get(first['league'], str(first['league']).upper())} · "
            f"{html.escape(str(first['match']))}</b>\n1H {away_1h}–{home_1h} · {source} · theo dõi")
    lines = []
    for r in sorted(rows, key=lambda x: 0 if x["market"] == "spread" else 1):
        pick = html.escape(str(r["pick"]))
        if r["market"] == "spread":
            lines.append(f"↩ <b>{pick} {_h2_signed(r['line'])}</b> · 1H {pick} {_h2_signed(r['first_line'])} thua ATS")
        else:
            over = r["pick_side"] == "over"
            lines.append(f"{'↑' if over else '↓'} <b>{pick} {_h2_num(r['line'])}</b> · 1H {away_1h + home_1h} "
                         f"{'&lt;' if over else '&gt;'} {_h2_num(r['first_line'])}")
    return "\n".join([head, *lines, DASHBOARD])


def notify_second_half(conn: sqlite3.Connection, now: str, telegram: tuple[str | None, str | None] | None,
                       post=requests.post) -> int:
    """Send each game's new 2H plays (one message per game); returns how many plays were sent. A failed send
    raises TelegramError and leaves the plays unmarked, so the next run during the same halftime retries."""
    token, chat = telegram or (None, None)
    if not token or not chat:
        return 0
    rows = due_second_half(conn, now)
    games: dict[int, list[dict]] = {}
    for r in sorted(rows, key=lambda x: (str(x["start_time"]), int(x["game_id"]))):
        games.setdefault(int(r["game_id"]), []).append(r)
    sent = 0
    for game_id, plays in games.items():
        send_telegram(token, chat, second_half_message(plays), post=post)
        conn.executemany("INSERT OR IGNORE INTO second_half_alerts(game_id, market, sent_at) VALUES (?, ?, ?)",
                         [(game_id, r["market"], now) for r in plays])
        conn.commit()
        sent += len(plays)
    return sent


# --- a move of an announced 2H line during halftime: sent at once, with every line seen so far ------------------
_MOVE_SCHEMA = ("CREATE TABLE IF NOT EXISTS second_half_line_alerts(game_id INTEGER, market TEXT, seen_at TEXT, "
                "sent_at TEXT, PRIMARY KEY(game_id, market, seen_at))")


def due_line_changes(conn: sqlite3.Connection, now: str) -> list[tuple]:
    """(game_id, market, seen_at) of 2H line moves not sent yet, on markets whose play was announced, while the
    game is still at halftime (its snapshot was saved in this run). The first line seen is not a move."""
    from actions_tracker import live
    for schema in (live.SECOND_HALF_SCHEMA, live.LINE_HISTORY_SCHEMA, _H2_SCHEMA, _MOVE_SCHEMA):
        conn.execute(schema)
    return [tuple(r) for r in conn.execute(
        "SELECT h.game_id, h.market, h.seen_at FROM second_half_line_history h "
        "JOIN second_half_alerts a ON a.game_id = h.game_id AND a.market = h.market "
        "JOIN second_half_snapshots s ON s.game_id = h.game_id AND s.captured_at = ? "
        "WHERE h.seen_at > (SELECT min(f.seen_at) FROM second_half_line_history f "
        "                   WHERE f.game_id = h.game_id AND f.market = h.market) "
        "AND NOT EXISTS (SELECT 1 FROM second_half_line_alerts x WHERE x.game_id = h.game_id "
        "                AND x.market = h.market AND x.seen_at = h.seen_at) "
        "ORDER BY h.game_id, h.market, h.seen_at", (now,))]


def line_change_message(plays: list[dict], history: dict[str, list[tuple]]) -> str:
    """One game: per moved market, the announced line -> the line now, then every line seen with its ET time."""
    first = plays[0]
    head = (f"🔄 <b>Line 2H · {_LEAGUE.get(first['league'], str(first['league']).upper())} · "
            f"{html.escape(str(first['match']))}</b>")
    lines = []
    for p in sorted(plays, key=lambda x: 0 if x["market"] == "spread" else 1):
        spread = p["market"] == "spread"
        sign = -1 if spread and p["pick_side"] == "home" else 1      # the stored spread is the away team's line
        seen = [(sign * float(line), at) for line, at in history[p["market"]]]
        fmt = _h2_signed if spread else _h2_num
        icon = "↩" if spread else "↑" if p["pick_side"] == "over" else "↓"
        lines.append(f"{icon} {html.escape(str(p['pick']))} {fmt(seen[0][0])} → <b>{fmt(seen[-1][0])}</b>")
        lines.append(" · ".join(f"{_local(at):%H:%M} {fmt(v)}" for v, at in seen))
    return "\n".join([head, *lines, DASHBOARD])


def notify_line_changes(conn: sqlite3.Connection, now: str, telegram: tuple[str | None, str | None] | None,
                        post=requests.post) -> int:
    """Send each game's new 2H line moves (one message per game); returns how many moved markets were sent.
    A failed send raises TelegramError and leaves them unmarked for the next run during the same halftime."""
    token, chat = telegram or (None, None)
    if not token or not chat:
        return 0
    due = due_line_changes(conn, now)
    if not due:
        return 0
    from actions_tracker.analysis.second_half import second_half_plays
    plays = second_half_plays(conn).to_dict("records")
    games: dict[int, dict[str, list[str]]] = {}
    for game_id, market, seen_at in due:
        games.setdefault(int(game_id), {}).setdefault(market, []).append(seen_at)
    sent = 0
    for game_id, markets in games.items():
        rows = [p for p in plays if int(p["game_id"]) == game_id and p["market"] in markets]
        if not rows:
            continue
        history = {m: [tuple(r) for r in conn.execute(
            "SELECT line, seen_at FROM second_half_line_history WHERE game_id = ? AND market = ? ORDER BY seen_at",
            (game_id, m))] for m in markets}
        send_telegram(token, chat, line_change_message(rows, history), post=post)
        conn.executemany("INSERT OR IGNORE INTO second_half_line_alerts(game_id, market, seen_at, sent_at) "
                         "VALUES (?, ?, ?, ?)", [(game_id, m, at, now) for m, seen in markets.items() for at in seen])
        conn.commit()
        sent += len(markets)
    return sent
