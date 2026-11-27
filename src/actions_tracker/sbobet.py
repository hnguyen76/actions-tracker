"""Read-only SBOBET live soccer collector using an owner-authenticated session cookie."""

from __future__ import annotations

import getpass
import json
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from actions_tracker.wagerhub import _LinkParser, _write_private, parse_live_tables

BETTING_URL = "https://www.sbobet.com/betting.aspx"
SESSION_FILE = ".sbobet_session.json"
PRIVATE_DIR = Path("data/private")
DISCOVERY_FILE = "sbobet_discovery.json"
LIVE_FILE = "sbobet_live.json"
ALLOWED_HOSTS = {"sbobet.com", "www.sbobet.com"}
TIMEOUT = 25
_BLOCKED = ("placebet", "submitbet", "confirm", "betslip", "cashier", "deposit", "withdraw",
            "payout", "transfer", "delete", "cancel")
_READ_HINTS = ("betting", "sport", "live", "inplay", "in-play", "score", "odds", "soccer", "football", "frame")


class SbobetError(RuntimeError):
    pass


class SbobetAuthError(SbobetError):
    pass


class SbobetSafetyError(SbobetError):
    pass


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise SbobetSafetyError("Đã chặn link ngoài SBOBET.")
    target = f"{parts.path}?{parts.query}".lower()
    if any(word in target for word in _BLOCKED):
        raise SbobetSafetyError("Đã chặn trang có thể thay đổi cược hoặc tiền.")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _parse_cookie_header(value: str) -> dict[str, str]:
    jar = SimpleCookie()
    try:
        jar.load(value.strip())
    except Exception as error:  # noqa: BLE001
        raise SbobetAuthError("Cookie SBOBET không hợp lệ.") from error
    cookies = {key: morsel.value for key, morsel in jar.items() if key and morsel.value}
    if not cookies:
        raise SbobetAuthError("Cookie SBOBET đang trống.")
    return cookies


def save_session(root: Path, cookie_header: str) -> Path:
    cookies = _parse_cookie_header(cookie_header)
    path = Path(root) / SESSION_FILE
    _write_private(path, {"cookies": cookies})
    return path


def load_session(root: Path) -> dict[str, str]:
    path = Path(root) / SESSION_FILE
    if not path.is_file():
        raise SbobetAuthError("Chưa setup phiên SBOBET trên máy này.")
    if path.stat().st_mode & 0o077:
        raise SbobetAuthError("File SBOBET không an toàn; chạy chmod 600 .sbobet_session.json.")
    try:
        cookies = json.loads(path.read_text("utf-8"))["cookies"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SbobetAuthError("Không đọc được phiên SBOBET.") from error
    if not isinstance(cookies, dict) or not cookies:
        raise SbobetAuthError("Phiên SBOBET đang trống.")
    return {str(key): str(value) for key, value in cookies.items()}


class SbobetClient:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 13) Chrome/120 Mobile Safari/537.36",
                                     "Accept-Language": "en-US,en;q=0.8"})
        self.home_url: str | None = None
        self.home_html: str | None = None

    def authenticate(self, cookies: dict[str, str]) -> None:
        self.session.cookies.update(cookies)
        try:
            response = self.session.get(BETTING_URL, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            safe = _safe_url(response.url)
        except (requests.RequestException, SbobetSafetyError) as error:
            raise SbobetAuthError("Không mở được trang betting SBOBET.") from error
        body = response.text.lower()
        if any(marker in body for marker in ('name="password"', "captcha", "please login", "sign in")):
            raise SbobetAuthError("Phiên SBOBET đã hết hạn hoặc cần CAPTCHA; đăng nhập lại rồi cập nhật cookie.")
        self.home_url, self.home_html = safe, response.text

    def _get(self, url: str) -> requests.Response:
        safe = _safe_url(url)
        try:
            response = self.session.get(safe, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            _safe_url(response.url)
            return response
        except SbobetSafetyError:
            raise
        except requests.RequestException as error:
            raise SbobetError("Không đọc được trang SBOBET.") from error

    def collect(self, root: Path, max_pages: int = 30) -> dict:
        if not self.home_url or self.home_html is None:
            raise SbobetAuthError("Collector chưa xác thực.")
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
                except SbobetSafetyError:
                    continue
                if next_url not in seen:
                    queue.append((next_url, None, depth + 1))
        now = datetime.now(timezone.utc).isoformat()
        private = Path(root) / PRIVATE_DIR
        discovery = {"updated_at": now, "visited_paths": sorted(set(visited)), "table_headers": headers,
                     "records_found": len(records)}
        _write_private(private / DISCOVERY_FILE, discovery)
        if records:
            _write_private(private / LIVE_FILE, {"updated_at": now, "source": "SBOBET", "records": records})
        return {"records": len(records), "discovery_path": private / DISCOVERY_FILE,
                "live_path": private / LIVE_FILE}


def setup(root: Path, getpass_fn: Callable[[str], str] = getpass.getpass,
          client_factory: Callable[[], SbobetClient] = SbobetClient) -> int:
    print("Setup chỉ-đọc SBOBET: dùng phiên đã đăng nhập; không mở bet slip hoặc đặt cược.")
    cookie = getpass_fn("Dán Cookie header SBOBET (không hiện trên màn hình): ")
    try:
        cookies = _parse_cookie_header(cookie)
        client = client_factory()
        client.authenticate(cookies)
        path = save_session(root, cookie)
        result = client.collect(root)
    except SbobetError as error:
        print(f"LỖI SBOBET: {error}")
        return 8
    print(f"Đã lưu cục bộ: {path.name} (chmod 600, gitignored).")
    print(f"SBOBET live: {result['records']} dòng; discovery: {result['discovery_path']}")
    return 0


def collect(root: Path, client_factory: Callable[[], SbobetClient] = SbobetClient) -> int:
    try:
        cookies = load_session(root)
        client = client_factory()
        client.authenticate(cookies)
        result = client.collect(root)
    except SbobetError as error:
        print(f"LỖI SBOBET: {error}")
        return 8
    print(f"SBOBET live: {result['records']} dòng.")
    return 0
