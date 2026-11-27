import json
import stat

import pytest

from actions_tracker import sbobet


LIVE_HTML = ("<table><tr><th>Match</th><th>Score</th><th>Handicap</th><th>Total</th></tr>"
             "<tr><td>Arsenal @ Chelsea</td><td>1-0</td><td>Chelsea +0.5</td><td>2.5</td></tr></table>")


class Response:
    def __init__(self, url, text, status=200):
        self.url, self.text, self.status_code = url, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sbobet.requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self):
        self.headers, self.cookies, self.calls = {}, {}, []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url == sbobet.BETTING_URL:
            return Response(url, '<a href="/sports/live">Live Soccer</a><a href="/cashier">Cashier</a>')
        if url.endswith("/sports/live"):
            return Response(url, LIVE_HTML)
        raise AssertionError(url)


def test_only_same_site_read_pages_are_allowed():
    assert sbobet._safe_url("https://www.sbobet.com/sports/live") == "https://www.sbobet.com/sports/live"
    for url in ("http://www.sbobet.com/sports/live", "https://example.com/sports/live",
                "https://www.sbobet.com/betslip/submit", "https://www.sbobet.com/cashier"):
        with pytest.raises(sbobet.SbobetSafetyError):
            sbobet._safe_url(url)


def test_authenticated_collect_is_get_only_and_private(tmp_path):
    session = Session()
    client = sbobet.SbobetClient(session)
    client.authenticate({"SESSION": "abc"})
    result = client.collect(tmp_path)
    assert result["records"] == 1
    assert {method for method, _ in session.calls} == {"GET"}
    assert not any("cashier" in url for _, url in session.calls)
    live = json.loads((tmp_path / "data/private/sbobet_live.json").read_text("utf-8"))
    assert live["records"][0]["Score"] == "1-0"
    assert stat.S_IMODE((tmp_path / "data/private/sbobet_live.json").stat().st_mode) == 0o600


def test_session_cookie_is_private(tmp_path):
    path = sbobet.save_session(tmp_path, "SESSION=abc; locale=en")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sbobet.load_session(tmp_path) == {"SESSION": "abc", "locale": "en"}
    path.chmod(0o644)
    with pytest.raises(sbobet.SbobetAuthError, match="chmod 600"):
        sbobet.load_session(tmp_path)


def test_login_page_is_rejected():
    session = Session()
    session.get = lambda *args, **kwargs: Response(sbobet.BETTING_URL, '<input name="password">')
    with pytest.raises(sbobet.SbobetAuthError, match="hết hạn"):
        sbobet.SbobetClient(session).authenticate({"SESSION": "expired"})
