import json
import stat

import pytest

from actions_tracker import wcsports


LIVE_HTML = ("<table><tr><th>Match</th><th>Score</th><th>Handicap</th><th>Total</th></tr>"
             "<tr><td>KC @ DEN</td><td>10-7</td><td>DEN +3.5</td><td>44.5</td></tr></table>")


class Response:
    def __init__(self, url, text, status=200):
        self.url, self.text, self.status_code = url, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise wcsports.requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self):
        self.headers, self.calls = {}, []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if url == wcsports.LANDING_URL:
            return Response(url, '<form><input name="customerid"><input name="password"></form>')
        if url.endswith("/sports/live"):
            return Response(url, LIVE_HTML)
        raise AssertionError(url)

    def post(self, url, data, **kwargs):
        self.calls.append(("POST", url))
        assert data["customerid"] == "owner" and data["password"] == "secret"
        return Response("https://wcsports1.com/home",
                        '<a href="/sports/live">Live Scores</a><a href="/cashier/withdraw">Cashier</a>'
                        '<a href="/betslip/submit">Bet Slip</a>')


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
    assert [method for method, _ in session.calls].count("POST") == 1
    assert not any("cashier" in url or "betslip" in url for _, url in session.calls)
    live = json.loads((tmp_path / "data/private/wcsports_live.json").read_text("utf-8"))
    assert live["records"][0]["Score"] == "10-7"
    assert stat.S_IMODE((tmp_path / "data/private/wcsports_live.json").stat().st_mode) == 0o600


def test_credentials_are_private(tmp_path):
    path = wcsports.save_credentials(tmp_path, "owner", "secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert wcsports.load_credentials(tmp_path) == ("owner", "secret")
    path.chmod(0o644)
    with pytest.raises(wcsports.WCSportsAuthError, match="chmod 600"):
        wcsports.load_credentials(tmp_path)
