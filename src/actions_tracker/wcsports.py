"""GET-only WCSports live table collector for the owner's Termux phone."""

from __future__ import annotations

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from actions_tracker.wagerhub import _LinkParser, _write_private, parse_live_tables

LANDING_URL = "https://wcsports1.com/"
LOGIN_URL = "https://wcsports1.com/player-api/identity/CustomerLoginRedir?RedirToHome=1"
CREDENTIAL_FILE = ".wcsports_credentials.json"
PRIVATE_DIR = Path("data/private")
DISCOVERY_FILE = "wcsports_discovery.json"
LIVE_FILE = "wcsports_live.json"
API_FILE = "wcsports_api.json"
ALLOWED_HOSTS = {"wcsports1.com", "www.wcsports1.com"}
TIMEOUT = 25
SCOREBOARD_URL = "https://wcsports1.com/player-api/api/scoreboard"
SPORTS_AVAILABLE_URL = "https://wcsports1.com/player-api/api/wager/sportsavailablebyplayeronleague/false"
READ_API_URLS = {SCOREBOARD_URL.lower(), SPORTS_AVAILABLE_URL.lower()}
_BLOCKED = ("placebet", "submitbet", "wager", "ticket", "betslip", "bet-slip", "confirm", "cashier", "deposit", "withdraw",
            "payout", "transfer", "delete", "cancel")
_READ_HINTS = ("home", "main", "menu", "sport", "live", "inplay", "in-play", "score", "odds", "football",
               "basketball", "nfl", "nba", "ncaaf", "frame")


class WCSportsError(RuntimeError):
    pass


class WCSportsAuthError(WCSportsError):
    pass


class WCSportsSafetyError(WCSportsError):
    pass


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise WCSportsSafetyError("Đã chặn link ngoài WCSports.")
    target = f"{parts.path}?{parts.query}".lower()
    if any(word in target for word in _BLOCKED) and urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, "")).lower() not in READ_API_URLS:
        raise WCSportsSafetyError("Đã chặn trang có thể thay đổi cược hoặc tiền.")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _json_shape(value, depth: int = 0):
    """Return keys/types only, never account values, for safe API discovery."""
    if depth >= 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): _json_shape(item, depth + 1) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        return {"type": "list", "count": len(value),
                "item": _json_shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def save_credentials(root: Path, username: str, password: str) -> Path:
    username, password = username.strip(), password.strip()
    if not username or not password or any(ord(char) < 32 for char in username + password):
        raise WCSportsAuthError("Username/password không hợp lệ.")
    path = Path(root) / CREDENTIAL_FILE
    _write_private(path, {"username": username, "password": password})
    return path


def load_credentials(root: Path) -> tuple[str, str]:
    path = Path(root) / CREDENTIAL_FILE
    if not path.is_file():
        raise WCSportsAuthError("Chưa setup WCSports trên máy này.")
    if path.stat().st_mode & 0o077:
        raise WCSportsAuthError("File WCSports không an toàn; chạy chmod 600 .wcsports_credentials.json.")
    try:
        value = json.loads(path.read_text("utf-8"))
        username, password = str(value["username"]), str(value["password"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise WCSportsAuthError("Không đọc được file setup WCSports.") from error
    if not username or not password:
        raise WCSportsAuthError("File setup WCSports còn thiếu username/password.")
    return username, password


class WCSportsClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 13) Chrome/120 Mobile Safari/537.36",
                                     "Accept-Language": "en-US,en;q=0.8"})
        self.home_url: str | None = None
        self.home_html: str | None = None

    def login(self, username: str, password: str) -> None:
        try:
            landing = self.session.get(LANDING_URL, timeout=TIMEOUT)
            landing.raise_for_status()
            response = self.session.post(LOGIN_URL,
                data={"customerid": username, "password": password, "submit": "Login Now"},
                headers={"Referer": LANDING_URL, "Origin": "https://wcsports1.com"},
                timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException as error:
            raise WCSportsAuthError("Không kết nối được trang đăng nhập WCSports.") from error
        try:
            safe = _safe_url(response.url)
        except WCSportsSafetyError as error:
            raise WCSportsAuthError("WCSports chuyển sang domain chưa được cho phép.") from error
        body = response.text.lower()
        if "invalid login" in body or 'name="customerid"' in body or 'name="password"' in body:
            raise WCSportsAuthError("Đăng nhập không thành công; kiểm tra tài khoản trên S21.")
        self.home_url, self.home_html = safe, response.text

    def _get(self, url: str) -> requests.Response:
        safe = _safe_url(url)
        try:
            api_headers = None
            if safe.lower() in READ_API_URLS:
                api_headers = {"Accept": "application/json, text/plain, */*",
                               "Referer": "https://wcsports1.com/v2/index.html",
                               "X-Requested-With": "XMLHttpRequest"}
            response = self.session.get(safe, headers=api_headers, timeout=TIMEOUT, allow_redirects=True)
            _safe_url(response.url)
            if response.status_code >= 400:
                parts = urlsplit(response.url)
                raise WCSportsError(f"HTTP {response.status_code} tại {(parts.hostname or 'unknown')}{parts.path}")
            return response
        except WCSportsSafetyError:
            raise
        except requests.RequestException as error:
            raise WCSportsError(f"Lỗi mạng {type(error).__name__} khi đọc WCSports.") from error

    def collect(self, root: Path, max_pages: int = 30) -> dict:
        if not self.home_url or self.home_html is None:
            raise WCSportsAuthError("Collector chưa đăng nhập.")
        queue = [(self.home_url, self.home_html, 0)]
        seen: set[str] = set()
        visited, headers, records = [], [], []
        while queue and len(seen) < max_pages:
            url, supplied, depth = queue.pop(0)
            safe = _safe_url(url)
            if safe in seen:
                continue
            seen.add(safe)
            if supplied is None:
                response = self._get(safe)
                safe, supplied = response.url, response.text
            path = urlsplit(safe).path or "/"
            visited.append(path)
            page_records, page_headers = parse_live_tables(supplied, path)
            records.extend(page_records)
            headers.extend(page_headers)
            if depth >= 3:
                continue
            parser = _LinkParser(safe)
            parser.feed(supplied)
            for link in parser.links:
                context = f"{link.label} {urlsplit(link.url).path}".lower()
                if not (link.embedded or any(hint in context for hint in _READ_HINTS)):
                    continue
                try:
                    next_url = _safe_url(urljoin(safe, link.url))
                except WCSportsSafetyError:
                    continue
                if next_url not in seen:
                    queue.append((next_url, None, depth + 1))
        api_payloads, api_shapes = {}, {}
        for name, url in (("scoreboard", SCOREBOARD_URL), ("sports_available", SPORTS_AVAILABLE_URL)):
            try:
                response = self._get(url)
                payload = response.json()
                api_payloads[name] = payload
                api_shapes[name] = _json_shape(payload)
            except (requests.RequestException, ValueError, WCSportsError) as error:
                detail = str(error) if isinstance(error, WCSportsError) else type(error).__name__
                api_shapes[name] = {"error": detail[:200]}
        now = datetime.now(timezone.utc).isoformat()
        private = Path(root) / PRIVATE_DIR
        discovery = {"updated_at": now, "visited_paths": sorted(set(visited)), "table_headers": headers,
                     "records_found": len(records), "api_shapes": api_shapes}
        _write_private(private / DISCOVERY_FILE, discovery)
        if api_payloads:
            _write_private(private / API_FILE, {"updated_at": now, "source": "WCSports", "payloads": api_payloads})
        if records:
            _write_private(private / LIVE_FILE, {"updated_at": now, "source": "WCSports", "records": records})
        return {"records": len(records), "api_sources": len(api_payloads), "discovery_path": private / DISCOVERY_FILE,
                "live_path": private / LIVE_FILE}


def setup(root: Path, input_fn: Callable[[str], str] = input,
          getpass_fn: Callable[[str], str] = getpass.getpass,
          client_factory: Callable[[], WCSportsClient] = WCSportsClient) -> int:
    print("Setup chỉ-đọc: không mở bet slip, không đặt cược, không nạp/rút tiền.")
    username = input_fn("WCSports username: ").strip()
    password = getpass_fn("WCSports password (không hiện trên màn hình): ")
    try:
        client = client_factory()
        client.login(username, password)
        path = save_credentials(root, username, password)
        result = client.collect(root)
    except WCSportsError as error:
        print(f"LỖI WCSports: {error}")
        return 8
    print(f"Đã lưu cục bộ: {path.name} (chmod 600, gitignored).")
    print(f"WCSports live: {result['records']} dòng HTML; API: {result['api_sources']}/2; discovery: {result['discovery_path']}")
    return 0


def collect(root: Path, client_factory: Callable[[], WCSportsClient] = WCSportsClient) -> int:
    try:
        username, password = load_credentials(root)
        client = client_factory()
        client.login(username, password)
        result = client.collect(root)
    except WCSportsError as error:
        print(f"LỖI WCSports: {error}")
        return 8
    print(f"WCSports live: {result['records']} dòng HTML; API: {result['api_sources']}/2.")
    return 0
