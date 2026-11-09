"""Polite HTTP access to Action Network: browser UA, delay between requests, retry with backoff."""

import random
import time
from collections.abc import Callable

import requests

from actions_tracker.config import PICKS_URL, SCOREBOARD_URL

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
BACKOFF = (2, 4, 8)
TIMEOUT = 30


class FetchError(Exception):
    """A request failed for good (4xx, or still failing after all retries)."""


class Fetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        delay: tuple[float, float] = (2, 4),
    ):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.delay = delay
        self._requests = 0

    def _get(self, url: str):
        if self._requests:
            self.sleep(random.uniform(*self.delay))
        self._requests += 1
        last = ""
        for attempt in range(len(BACKOFF) + 1):
            if attempt:
                self.sleep(BACKOFF[attempt - 1])
            try:
                resp = self.session.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            except requests.RequestException as e:  # connection, timeout, chunked-encoding, ...
                last = f"{type(e).__name__}: {e}"
                continue
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                continue
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        raise FetchError(f"{url}: gave up after {len(BACKOFF) + 1} attempts ({last})")

    def get_text(self, url: str) -> str:
        return self._get(url).text

    def get_json(self, url: str) -> dict:
        try:
            return self._get(url).json()
        except ValueError as e:
            raise FetchError(f"{url}: response is not JSON") from e


def fetch_picks(fetcher: Fetcher, league: str) -> str:
    return fetcher.get_text(PICKS_URL.format(league=league))


def fetch_scoreboard(fetcher: Fetcher, league: str, query: str = "") -> dict:
    """Default scoreboard (today / this week), or a past one with query like 'date=20261108' or 'week=10'."""
    url = SCOREBOARD_URL.format(league=league) + (f"&{query}" if query else "")
    return fetcher.get_json(url)
