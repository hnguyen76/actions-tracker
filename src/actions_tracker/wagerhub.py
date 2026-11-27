"""Read-only WagerHub history collector for the owner's Termux phone.

The only POST this module can make is the public login form.  Every account page is
fetched with GET and dangerous wager/cashier paths are rejected before a request is
sent.  Credentials and collected rows stay in gitignored, owner-only files.
"""

from __future__ import annotations

import getpass
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
DISCOVERY_FILE = "wagerhub_discovery.json"
LIVE_FILE = "wagerhub_live.json"
ALLOWED_HOSTS = {"wagerhub888.com", "www.wagerhub888.com", "classic.wagerhub888.com"}
TIMEOUT = 25

# The collector follows only read-oriented pages.  These words are checked against
# both paths and query strings before every account GET.
_BLOCKED = (
    "confirmwager", "placewager", "newwager", "submitwager", "betconfirm", "betslip",
    "cashier", "deposit", "withdraw", "payout", "transferfund", "delete", "cancelwager",
)
_HISTORY = ("history", "settled", "graded", "transaction", "statement", "account activity", "my wagers")
_NAVIGATION = _HISTORY + ("menu", "home", "main", "account", "report", "frame", "live", "in play", "in-play",
                          "score", "odds", "sports", "football", "basketball")
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
    if parts.scheme.lower() != "https" or host not in ALLOWED_HOSTS:
        raise WagerHubSafetyError("Đã chặn link ngoài WagerHub.")
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
            page_live, live_headers = parse_live_tables(supplied, _display_path(safe))
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
        now = datetime.now(timezone.utc).isoformat()
        summary = summarize(unique)
        private = Path(root) / PRIVATE_DIR
        discovery = {"updated_at": now, "visited_paths": sorted(set(visited)), "table_headers": headers,
                     "records_found": len(unique)}
        _write_private(private / DISCOVERY_FILE, discovery)
        if unique:
            _write_private(private / HISTORY_FILE,
                           {"updated_at": now, "source": "WagerHub", "summary": summary, "records": unique})
        if live_records:
            _write_private(private / LIVE_FILE,
                           {"updated_at": now, "source": "WagerHub", "records": live_records})
        return {"summary": summary, "discovery": discovery, "history_path": private / HISTORY_FILE,
                "discovery_path": private / DISCOVERY_FILE, "live_path": private / LIVE_FILE,
                "live_records": len(live_records)}


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
    if result["summary"].get("settled"):
        print(f"Chi tiết riêng tư: {result['history_path']} (không publish).")
    else:
        print(f"Sơ đồ an toàn: {result['discovery_path']}")
    return 0
