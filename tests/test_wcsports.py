import json
import stat

import pytest

from actions_tracker import wcsports


LIVE_HTML = ("<table><tr><th>Match</th><th>Score</th><th>Handicap</th><th>Total</th></tr>"
             "<tr><td>KC @ DEN</td><td>10-7</td><td>DEN +3.5</td><td>44.5</td></tr></table>")


class Response:
    def __init__(self, url, text, status=200, history=None, headers=None):
        self.url, self.text, self.status_code = url, text, status
        self.history, self.headers = history or [], headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise wcsports.requests.HTTPError(str(self.status_code))

    def json(self):
        return json.loads(self.text)


class Session:
    def __init__(self):
        self.headers, self.cookies, self.calls, self.api_headers = {}, [], [], []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url == wcsports.LANDING_URL:
            return Response(url, '<form><input name="customerid"><input name="password"></form>')
        if url.endswith("/sports/live"):
            return Response(url, LIVE_HTML)
        if url == wcsports.SCOREBOARD_URL:
            self.api_headers.append(kwargs.get("headers"))
            return Response(url, '{"games":[{"id":1,"score":"10-7"}]}')
        if url == wcsports.SPORTS_AVAILABLE_URL:
            self.api_headers.append(kwargs.get("headers"))
            return Response(url, '[{"sport":"Football","leagueCount":2}]')
        raise AssertionError(url)

    def post(self, url, data=None, json=None, **kwargs):
        self.calls.append(("POST", url))
        if url == wcsports.LOGIN_URL:
            assert data["customerid"] == "owner" and data["password"] == "secret"
            redirect = Response(url, "", 302,
                                headers={"Location": "https://wcsports1.com/v2/?token=one-time-handoff-token"})
            return Response("https://wcsports1.com/v2/index.html",
                            '<a href="/sports/live">Live Scores</a><a href="/cashier/withdraw">Cashier</a>'
                            '<a href="/betslip/submit">Bet Slip</a>', history=[redirect])
        if url == wcsports.TOKEN_LOGIN_URL:
            assert json == {"token": "one-time-handoff-token", "version": "1.3.47"}
            return Response(url, '{"accessToken":"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lciJ9.signature1234567890"}')
        raise AssertionError(url)


def test_only_same_site_read_pages_are_allowed():
    assert wcsports._safe_url("https://wcsports1.com/sports/live") == "https://wcsports1.com/sports/live"
    for url in ("http://wcsports1.com/sports/live", "https://example.com/sports/live",
                "https://wcsports1.com/betslip/submit", "https://wcsports1.com/cashier/withdraw"):
        with pytest.raises(wcsports.WCSportsSafetyError):
            wcsports._safe_url(url)


def test_login_and_collect_are_read_only_and_private(tmp_path):
    session = Session()
    client = wcsports.WCSportsClient(session)
    client.login("owner", "secret")
    result = client.collect(tmp_path)
    assert result["records"] == 1
    assert result["api_sources"] == 2
    assert session.headers["Authorization"].startswith("Bearer eyJ")
    assert [method for method, _ in session.calls].count("POST") == 2
    assert not any("cashier" in url or "betslip" in url for _, url in session.calls)
    live = json.loads((tmp_path / "data/private/wcsports_live.json").read_text("utf-8"))
    assert live["records"][0]["Score"] == "10-7"
    assert stat.S_IMODE((tmp_path / "data/private/wcsports_live.json").stat().st_mode) == 0o600
    api = json.loads((tmp_path / "data/private/wcsports_api.json").read_text("utf-8"))
    assert api["payloads"]["scoreboard"]["games"][0]["score"] == "10-7"
    discovery = json.loads((tmp_path / "data/private/wcsports_discovery.json").read_text("utf-8"))
    assert discovery["api_shapes"]["sports_available"]["count"] == 1
    assert stat.S_IMODE((tmp_path / "data/private/wcsports_api.json").stat().st_mode) == 0o600


def test_credentials_are_private(tmp_path):
    path = wcsports.save_credentials(tmp_path, "owner", "secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert wcsports.load_credentials(tmp_path) == ("owner", "secret")
    path.chmod(0o644)
    with pytest.raises(wcsports.WCSportsAuthError, match="chmod 600"):
        wcsports.load_credentials(tmp_path)
