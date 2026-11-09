import pytest
import requests

from actions_tracker.fetch import FetchError, Fetcher


class R:
    def __init__(self, code, text="ok"):
        self.status_code, self.text = code, text

    def json(self):
        return {"games": []}


class S:
    def __init__(self, seq):
        self.seq, self.calls = list(seq), 0

    def get(self, url, **kw):
        self.calls += 1
        x = self.seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


def test_retries_then_succeeds():
    slept = []
    s = S([R(503), requests.ConnectionError(), R(200, "hi")])
    assert Fetcher(s, sleep=slept.append).get_text("u") == "hi"
    assert s.calls == 3 and slept[:2] == [2, 4]


def test_403_fails_fast():
    s = S([R(403)])
    with pytest.raises(FetchError):
        Fetcher(s, sleep=lambda x: None).get_text("u")
    assert s.calls == 1


def test_gives_up_after_retries():
    s = S([R(429)] * 4)
    with pytest.raises(FetchError):
        Fetcher(s, sleep=lambda x: None).get_text("u")
    assert s.calls == 4


def test_polite_delay_between_requests():
    slept = []
    f = Fetcher(S([R(200), R(200)]), sleep=slept.append, delay=(2, 2))
    f.get_text("a")
    assert slept == []
    f.get_json("b")
    assert slept == [2]
