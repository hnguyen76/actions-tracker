"""Read-only WagerHub history collector for the owner's Termux phone.

The only POST this module can make is the public login form.  Every account page is
fetched with GET and dangerous wager/cashier paths are rejected before a request is
sent.  Credentials and collected rows stay in gitignored, owner-only files.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


LANDING_URL = "https://www.wagerhub888.com/"
LOGIN_URL = "https://classic.wagerhub888.com/login.aspx"
CREDENTIAL_FILE = ".wagerhub_credentials.json"
PRIVATE_DIR = Path("data/private")
HISTORY_FILE = "wagerhub_history.json"
STATS_FILE = "wagerhub_stats.json"
STATS_HISTORY_FILE = "wagerhub_stats_history.json"
DISCOVERY_FILE = "wagerhub_discovery.json"
LIVE_FILE = "wagerhub_live.json"
PERIOD_LINES_FILE = "wagerhub_period_lines.json"
PERIOD_LINE_HISTORY_FILE = "wagerhub_period_line_history.json"
ALLOWED_HOSTS = {"wagerhub888.com", "www.wagerhub888.com", "classic.wagerhub888.com", "live.viggames.com"}
TIMEOUT = 25

# The collector follows only read-oriented pages.  These words are checked against
# both paths and query strings before every account GET.
_BLOCKED = (
    "confirmwager", "placewager", "newwager", "submitwager", "betconfirm", "betslip",
    "cashier", "deposit", "withdraw", "payout", "transferfund", "delete", "cancelwager",
)
_HISTORY = ("history", "settled", "graded", "transaction", "statement", "account activity", "my wagers")
_NAVIGATION = _HISTORY + ("menu", "home", "main", "account", "report", "frame", "live", "in play", "in-play",
                          "score", "odds", "sports", "football", "basketball", "1h", "2h", "1st half",
                          "2nd half", "first half", "second half", "halftime")
_HEADER_HINTS = (
    "date", "time", "ticket", "sport", "league", "event", "description", "wager", "type",
    "risk", "to win", "status", "result", "win loss", "net", "amount",
)


class WagerHubError(RuntimeError):
    """Safe user-facing WagerHub failure; messages never contain credentials."""


class WagerHubAuthError(WagerHubError):
    pass


class WagerHubSafetyError(WagerHubError):
    pass


@dataclass(frozen=True)
class Link:
    url: str
    label: str
    embedded: bool = False


class _LoginParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden: dict[str, str] = {}
        self.has_account = False
        self.has_password = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        data = {str(k).lower(): v or "" for k, v in attrs}
        name = data.get("name", "")
        kind = data.get("type", "").lower()
        if kind == "hidden" and name:
            self.hidden[name] = data.get("value", "")
        self.has_account |= name.lower() == "account"
        self.has_password |= name.lower() == "password" or kind == "password"


class _LinkParser(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.links: list[Link] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {str(k).lower(): v or "" for k, v in attrs}
        if tag.lower() == "a" and data.get("href"):
            self._href, self._parts = data["href"], []
        elif tag.lower() in {"frame", "iframe"} and data.get("src"):
            self.links.append(Link(urljoin(self.base, data["src"]), "frame", True))

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            label = " ".join(" ".join(self._parts).split())
            self.links.append(Link(urljoin(self.base, self._href), label))
            self._href, self._parts = None, []


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._depth == 0:
                self._table = []
            self._depth += 1
        elif self._depth and tag == "tr" and self._row is None:
            self._row = []
        elif self._depth and tag in {"th", "td"} and self._row is not None and self._cell is None:
            self._cell = []
        elif self._cell is not None and tag == "br":
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._cell is not None and tag in {"th", "td"}:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth and tag == "tr" and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._table is not None:
                if self._table:
                    self.tables.append(self._table)
                self._table = None


def _clean_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    # The book may move an authenticated session to a regional/mobile subdomain.
    # Accept only the registrable WagerHub domain and its real subdomains; a name
    # such as wagerhub888.com.example.org still fails this boundary check.
    same_site = host == "wagerhub888.com" or host.endswith(".wagerhub888.com") or host == "live.viggames.com"
    if parts.scheme.lower() != "https" or not same_site:
        label = host or "không rõ host"
        raise WagerHubSafetyError(f"Đã chặn link ngoài WagerHub ({label}).")
    target = (parts.path + "?" + parts.query).lower()
    if any(word in target for word in _BLOCKED):
        raise WagerHubSafetyError("Đã chặn trang có thể thay đổi cược hoặc tiền.")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _display_path(url: str) -> str:
    parts = urlsplit(url)
    return parts.path or "/"  # never print a query string; it may contain a session value


def _looks_history(value: str) -> bool:
    value = value.lower()
    return any(word in value for word in _HISTORY)


def _looks_navigation(value: str) -> bool:
    value = value.lower()
    return any(word in value for word in _NAVIGATION)


def parse_history_tables(html: str, source: str = "") -> tuple[list[dict[str, str]], list[list[str]]]:
    parser = _TableParser()
    parser.feed(html or "")
    records: list[dict[str, str]] = []
    headers_seen: list[list[str]] = []
    for table in parser.tables:
        header_index = None
        for index, row in enumerate(table[:8]):
            cleaned = [_clean_header(cell) for cell in row]
            if len(cleaned) >= 2 and sum(any(hint in cell for hint in _HEADER_HINTS) for cell in cleaned) >= 2:
                header_index = index
                break
        if header_index is None:
            continue
        headers = table[header_index]
        headers_seen.append(headers)
        for row in table[header_index + 1:]:
            if len(row) < 2 or not any(row):
                continue
            padded = row + [""] * max(0, len(headers) - len(row))
            record = {headers[i] or f"column_{i + 1}": padded[i] for i in range(len(headers))}
            record["_source"] = source
            records.append(record)
    return records, headers_seen


def parse_live_tables(html: str, source: str = "") -> tuple[list[dict[str, str]], list[list[str]]]:
    """Extract score/odds tables without following or submitting market controls."""
    parser = _TableParser()
    parser.feed(html or "")
    records, headers_seen = [], []
    hints = ("team", "event", "match", "score", "spread", "handicap", "total", "odds", "moneyline", "line")
    for table in parser.tables:
        header_index = None
        for index, row in enumerate(table[:8]):
            cleaned = [_clean_header(cell) for cell in row]
            if len(cleaned) >= 2 and sum(any(hint in cell for hint in hints) for cell in cleaned) >= 2:
                header_index = index
                break
        if header_index is None:
            continue
        headers = table[header_index]
        headers_seen.append(headers)
        for row in table[header_index + 1:]:
            if len(row) < 2 or not any(row):
                continue
            padded = row + [""] * max(0, len(headers) - len(row))
            records.append({**{headers[i] or f"column_{i + 1}": padded[i] for i in range(len(headers))},
                            "_source": source})
    return records, headers_seen


def normalize_period_lines(records: list[dict[str, str]], captured_at: str) -> list[dict]:
    """Normalize read-only 1H/2H rows while retaining their private raw source row."""
    output = []
    for record in records:
        text = " ".join(str(value) for value in record.values()).lower()
        if re.search(r"\b(1h|1st half|first half|half 1)\b", text):
            period = "1H"
        elif re.search(r"\b(2h|2nd half|second half|half 2)\b", text):
            period = "2H"
        else:
            continue
        if re.search(r"\b(over|under|total|o/u)\b", text):
            market = "total"
        elif re.search(r"\b(moneyline|money line|ml)\b", text):
            market = "moneyline"
        else:
            market = "spread"
        if re.search(r"\b(halftime|half time)\b", text):
            phase = "halftime"
        elif re.search(r"\b(live|in[ -]?play|score)\b", text):
            phase = "live"
        else:
            phase = "pregame"
        output.append({
            "captured_at": captured_at,
            "period": period,
            "phase": phase,
            "market": market,
            "matchup": _field(record, ("match", "event", "game", "description")),
            "selection": _field(record, ("selection", "team", "pick", "wager")),
            "line": _field(record, ("spread", "handicap", "total", "line")),
            "odds": _field(record, ("odds", "price", "american")),
            "source": record.get("_source"),
            "raw": {key: value for key, value in record.items() if key != "_source"},
        })
    return output


def _period_key(row: dict) -> str:
    return "|".join(str(row.get(key) or "").strip().lower()
                    for key in ("period", "phase", "market", "matchup", "selection"))


def _write_period_lines(private: Path, captured_at: str, rows: list[dict]) -> None:
    _write_private(private / PERIOD_LINES_FILE,
                   {"updated_at": captured_at, "source": "WagerHub", "records": rows})
    history_path = private / PERIOD_LINE_HISTORY_FILE
    history = []
    if history_path.is_file():
        try:
            history = json.loads(history_path.read_text("utf-8")).get("snapshots", [])
        except (OSError, ValueError, TypeError):
            history = []
    latest = {}
    for old in history:
        latest[_period_key(old)] = (old.get("line"), old.get("odds"))
    for row in rows:
        value = (row.get("line"), row.get("odds"))
        if latest.get(_period_key(row)) != value:
            history.append(row)
            latest[_period_key(row)] = value
    _write_private(history_path, {"updated_at": captured_at, "snapshots": history[-5000:]})


def _field(record: dict[str, str], names: tuple[str, ...]) -> str | None:
    fields = [(_clean_header(key), value) for key, value in record.items() if not key.startswith("_")]
    for name in names:
        for key, value in fields:
            if key == name or name in key:
                return value
    return None


def _money(value: str | None) -> float | None:
    if not value:
        return None
    raw = value.strip()
    negative = (raw.startswith("(") and raw.endswith(")")) or bool(re.match(r"^-\s*[$€£]?\s*\d", raw))
    compact = re.sub(r"[$€£\s]", "", raw)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", compact)
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    return -abs(number) if negative else number


def summarize(records: list[dict[str, str]]) -> dict[str, float | int | None]:
    wins = losses = pushes = 0
    net_values: list[float] = []
    risk_values: list[float] = []
    for record in records:
        status = (_field(record, ("status", "result", "win loss", "w l")) or "").strip().lower()
        # "Payout" often includes the returned stake and is not net profit, so it is intentionally excluded.
        profit = _money(_field(record, ("net", "profit", "result amount", "win loss")))
        if re.search(r"\b(push|void|cancelled|canceled|no action)\b", status):
            pushes += 1
        elif re.search(r"\b(win|won|winner|w)\b", status) or not status and profit is not None and profit > 0:
            wins += 1
        elif re.search(r"\b(loss|lost|lose|loser|l)\b", status) or not status and profit is not None and profit < 0:
            losses += 1
        else:
            continue
        if profit is not None:
            net_values.append(profit)
        risk = _money(_field(record, ("risk", "stake", "wager amount", "amount wagered")))
        if risk is not None and risk != 0:
            risk_values.append(abs(risk))
    decisions = wins + losses
    settled = decisions + pushes
    # Never present a partial money total as the account total. W-L-P remains useful when a table omits amounts.
    risked = round(sum(risk_values), 2) if settled and len(risk_values) == settled else None
    net = round(sum(net_values), 2) if settled and len(net_values) == settled else None
    return {
        "records": len(records), "settled": settled, "wins": wins, "losses": losses, "pushes": pushes,
        "win_pct": round(wins / decisions * 100, 1) if decisions else None,
        "risked": risked, "net": net,
        "roi_pct": round(net / risked * 100, 1) if net is not None and risked else None,
    }


def _record_key(record: dict[str, str]) -> str:
    ticket = _field(record, ("ticket", "transaction id", "wager id", "confirmation"))
    if ticket:
        return "ticket:" + ticket.strip().lower()
    stable = {key: value for key, value in record.items() if key != "_source"}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "row:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _merge_history(root: Path, current: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep settled tickets across scans; current rows replace older versions of the same ticket."""
    path = Path(root) / PRIVATE_DIR / HISTORY_FILE
    previous: list[dict[str, str]] = []
    if path.is_file():
        try:
            value = json.loads(path.read_text("utf-8"))
            previous = [row for row in value.get("records", []) if isinstance(row, dict)]
        except (OSError, ValueError, TypeError):
            previous = []
    merged = {_record_key(row): row for row in previous}
    merged.update({_record_key(row): row for row in current})
    return list(merged.values())


def _record_date(record: dict[str, str], now: datetime) -> datetime | None:
    value = (_field(record, ("date", "settled date", "graded date", "time", "placed")) or "").strip()
    value = re.sub(r"\s+", " ", value)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d", "%m-%d-%Y", "%b %d %Y", "%b %d"):
        try:
            parsed = datetime.strptime(value.split(" ")[0] if fmt in {"%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d", "%m-%d-%Y"} else value, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=now.year)
                if parsed.date() > now.date():
                    parsed = parsed.replace(year=now.year - 1)
            return parsed
        except ValueError:
            continue
    return None


def _market(record: dict[str, str]) -> str:
    explicit = (_field(record, ("market", "type", "bet type")) or "").lower()
    wager = (_field(record, ("wager", "description", "selection", "play")) or "").lower()
    text = explicit + " " + wager
    if re.search(r"\b(over|under|total|o/u)\b", text):
        return "total"
    if re.search(r"\b(moneyline|money line|ml)\b", text):
        return "moneyline"
    return "spread"


def statistical_report(records: list[dict[str, str]], now: datetime) -> dict:
    groups: dict[str, dict[str, list[dict[str, str]]]] = {
        "day": {}, "week": {}, "month": {}, "market": {}, "sport": {}}
    for record in records:
        date = _record_date(record, now)
        if date:
            iso = date.isocalendar()
            keys = {"day": date.strftime("%Y-%m-%d"), "week": f"{iso.year}-W{iso.week:02d}",
                    "month": date.strftime("%Y-%m")}
            for name, key in keys.items():
                groups[name].setdefault(key, []).append(record)
        groups["market"].setdefault(_market(record), []).append(record)
        sport = (_field(record, ("sport", "league")) or "Unknown").strip() or "Unknown"
        groups["sport"].setdefault(sport, []).append(record)
    output = {name: {key: summarize(rows) for key, rows in sorted(values.items())}
              for name, values in groups.items()}
    output["overall"] = summarize(records)
    return output


def _write_stat_history(private: Path, now: datetime, summary: dict) -> None:
    path = private / STATS_HISTORY_FILE
    snapshots = []
    if path.is_file():
        try:
            snapshots = json.loads(path.read_text("utf-8")).get("snapshots", [])
        except (OSError, ValueError, TypeError):
            snapshots = []
    day = now.strftime("%Y-%m-%d")
    snapshots = [item for item in snapshots if item.get("date") != day]
    snapshots.append({"date": day, "summary": summary})
    _write_private(path, {"updated_at": now.isoformat(), "snapshots": snapshots[-400:]})


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def save_credentials(root: Path, username: str, password: str) -> Path:
    username, password = username.strip(), password.strip()
    if not username or not password or any(ord(char) < 32 for char in username + password):
        raise WagerHubAuthError("Username/password không hợp lệ.")
    path = Path(root) / CREDENTIAL_FILE
    _write_private(path, {"username": username, "password": password})
    return path


def load_credentials(root: Path) -> tuple[str, str]:
    path = Path(root) / CREDENTIAL_FILE
    if not path.is_file():
        raise WagerHubAuthError("Chưa setup WagerHub trên máy này.")
    if path.stat().st_mode & 0o077:
        raise WagerHubAuthError("File WagerHub không an toàn; chạy chmod 600 .wagerhub_credentials.json.")
    try:
        value = json.loads(path.read_text("utf-8"))
        username, password = str(value["username"]), str(value["password"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise WagerHubAuthError("Không đọc được file setup WagerHub.") from error
    if not username or not password:
        raise WagerHubAuthError("File setup WagerHub còn thiếu username/password.")
    return username, password


class WagerHubClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
            "Accept-Language": "en-US,en;q=0.8",
        })
        self.home_url: str | None = None
        self.home_html: str | None = None

    def login(self, username: str, password: str) -> None:
        try:
            landing = self.session.get(LANDING_URL, timeout=TIMEOUT)
            landing.raise_for_status()
            parser = _LoginParser()
            parser.feed(landing.text)
            payload = {"IdBook": parser.hidden.get("IdBook", "15,42,33,115,147,151,302"),
                       "account": username, "password": password, "btn_login": "Login"}
            # This exact POST is the sole write-shaped request in the module. It only creates a session.
            response = self.session.post(LOGIN_URL, data=payload, headers={"Referer": LANDING_URL},
                                         timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException as error:
            raise WagerHubAuthError("Không kết nối được trang đăng nhập WagerHub.") from error
        try:
            _safe_url(response.url)
        except WagerHubSafetyError as error:
            raise WagerHubAuthError("WagerHub chuyển sang domain không an toàn.") from error
        check = _LoginParser()
        check.feed(response.text)
        path = urlsplit(response.url).path.lower()
        if "sessionend" in path or "login.aspx" in path or check.has_account and check.has_password:
            raise WagerHubAuthError("Đăng nhập không thành công; kiểm tra username/password trên S21.")
        self.home_url, self.home_html = response.url, response.text

    def _get(self, url: str) -> requests.Response:
        safe = _safe_url(url)
        try:
            response = self.session.get(safe, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            for step in [*(getattr(response, "history", []) or []), response]:
                _safe_url(step.url)
        except WagerHubSafetyError:
            raise
        except requests.RequestException as error:
            raise WagerHubError(f"Không đọc được trang {_display_path(safe)}.") from error
        if "sessionend" in urlsplit(response.url).path.lower():
            raise WagerHubAuthError("Phiên WagerHub đã hết; collector cần đăng nhập lại.")
        return response

    def collect(self, root: Path, max_pages: int = 30) -> dict:
        if not self.home_url or self.home_html is None:
            raise WagerHubAuthError("Collector chưa đăng nhập.")
        queue: list[tuple[str, str | None, int, str]] = [(self.home_url, self.home_html, 0, "home")]
        seen: set[str] = set()
        visited: list[str] = []
        headers: list[list[str]] = []
        records: list[dict[str, str]] = []
        live_records: list[dict[str, str]] = []
        while queue and len(seen) < max_pages:
            url, supplied, depth, label = queue.pop(0)
            try:
                safe = _safe_url(url)
            except WagerHubSafetyError:
                continue
            identity = safe.split("#", 1)[0]
            if identity in seen:
                continue
            seen.add(identity)
            if supplied is None:
                response = self._get(safe)
                safe, supplied = response.url, response.text
            visited.append(_display_path(safe))
            page_records, page_headers = parse_history_tables(supplied, _display_path(safe))
            if _looks_history(label + " " + safe) or page_records:
                records.extend(page_records)
                headers.extend(page_headers)
            page_live, live_headers = parse_live_tables(supplied, f"{label} {_display_path(safe)}")
            if page_live:
                live_records.extend(page_live)
                headers.extend(live_headers)
            if depth >= 3:
                continue
            parser = _LinkParser(safe)
            parser.feed(supplied)
            for link in parser.links:
                context = f"{link.label} {urlsplit(link.url).path}"
                if not (link.embedded or _looks_navigation(context)):
                    continue
                try:
                    next_url = _safe_url(link.url)
                except WagerHubSafetyError:
                    continue
                if next_url not in seen:
                    queue.append((next_url, None, depth + 1, context))
        # Same history table can be linked from more than one menu. Deduplicate without the diagnostic source path.
        unique: list[dict[str, str]] = []
        ticket_fingerprints: set[str] = set()
        for record in records:
            ticket = _field(record, ("ticket", "transaction id", "wager id", "confirmation"))
            # Only collapse rows when the book supplies a stable ticket id. Two genuinely separate wagers can
            # otherwise have identical visible date/side/risk values.
            if ticket:
                fingerprint = ticket.strip().lower()
                if fingerprint in ticket_fingerprints:
                    continue
                ticket_fingerprints.add(fingerprint)
            unique.append(record)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        private = Path(root) / PRIVATE_DIR
        accumulated = _merge_history(root, unique)
        summary = summarize(accumulated)
        stats = statistical_report(accumulated, now_dt)
        discovery = {"updated_at": now, "visited_paths": sorted(set(visited)), "table_headers": headers,
                     "records_found": len(unique)}
        _write_private(private / DISCOVERY_FILE, discovery)
        if accumulated:
            _write_private(private / HISTORY_FILE,
                           {"updated_at": now, "source": "WagerHub", "summary": summary, "records": accumulated})
            _write_private(private / STATS_FILE,
                           {"updated_at": now, "source": "WagerHub", "statistics": stats})
            _write_stat_history(private, now_dt, summary)
        if live_records:
            _write_private(private / LIVE_FILE,
                           {"updated_at": now, "source": "WagerHub", "records": live_records})
        period_lines = normalize_period_lines(live_records, now)
        if period_lines:
            _write_period_lines(private, now, period_lines)
        return {"summary": summary, "discovery": discovery, "history_path": private / HISTORY_FILE,
                "discovery_path": private / DISCOVERY_FILE, "live_path": private / LIVE_FILE,
                "live_records": len(live_records), "period_lines": len(period_lines)}


def _summary_line(summary: dict) -> str:
    if not summary.get("settled"):
        return "Chưa nhận diện được bảng settled trong giao diện tài khoản."
    win = f"{summary['win_pct']:.1f}%" if summary.get("win_pct") is not None else "n/a"
    line = f"WagerHub settled: {summary['wins']}-{summary['losses']}-{summary['pushes']} · win {win}"
    if summary.get("net") is not None:
        line += f" · net {summary['net']:+.2f}"
    if summary.get("roi_pct") is not None:
        line += f" · ROI {summary['roi_pct']:+.1f}%"
    return line


def setup(root: Path, input_fn: Callable[[str], str] = input,
          getpass_fn: Callable[[str], str] = getpass.getpass,
          client_factory: Callable[[], WagerHubClient] = WagerHubClient) -> int:
    print("Setup chỉ-đọc: không đặt/xác nhận cược, không nạp/rút tiền.")
    username = input_fn("WagerHub username: ").strip()
    password = getpass_fn("WagerHub password (không hiện trên màn hình): ")
    client = client_factory()
    try:
        client.login(username, password)
        path = save_credentials(root, username, password)
        result = client.collect(root)
    except WagerHubError as error:
        print(f"LỖI WagerHub: {error}")
        return 7
    print(f"Đã đăng nhập và lưu credentials cục bộ: {path.name} (chmod 600, gitignored).")
    print(_summary_line(result["summary"]))
    print(f"WagerHub 1H/2H: {result['period_lines']} line.")
    if not result["summary"].get("settled"):
        print(f"Đã lưu sơ đồ trang an toàn tại {result['discovery_path']} để hoàn thiện parser.")
    return 0


def collect(root: Path, client_factory: Callable[[], WagerHubClient] = WagerHubClient) -> int:
    try:
        username, password = load_credentials(root)
        client = client_factory()
        client.login(username, password)
        result = client.collect(root)
    except WagerHubError as error:
        print(f"LỖI WagerHub: {error}")
        return 7
    print(_summary_line(result["summary"]))
    print(f"WagerHub 1H/2H: {result['period_lines']} line.")
    if result["summary"].get("settled"):
        print(f"Chi tiết riêng tư: {result['history_path']} (không publish).")
    else:
        print(f"Sơ đồ an toàn: {result['discovery_path']}")
    return 0
