import json
import stat

import pytest

from actions_tracker import wagerhub


HISTORY_HTML = """
<table>
  <tr><th>Date</th><th>Ticket</th><th>Wager</th><th>Risk</th><th>Win/Loss</th><th>Result</th></tr>
  <tr><td>11/17</td><td>101</td><td>LAL -3.5</td><td>$100.00</td><td>+$90.00</td><td>Win</td></tr>
  <tr><td>11/17</td><td>102</td><td>Under 220.5</td><td>$100.00</td><td>-$100.00</td><td>Loss</td></tr>
  <tr><td>11/17</td><td>103</td><td>CHI +2</td><td>$100.00</td><td>$0.00</td><td>Push</td></tr>
</table>
"""


class Response:
    def __init__(self, url, text, status=200):
        self.url, self.text, self.status_code, self.history = url, text, status, []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise wagerhub.requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url == wagerhub.LANDING_URL:
            return Response(url, '<input type="hidden" name="IdBook" value="15,42">')
        if "Menu.aspx" in url:
            return Response(url, '<a href="/reports/WagerHistory.aspx?session=private">Wager History</a>'
                                 '<a href="/wager/ConfirmWager.aspx?WT=0">Confirm</a>')
        if "WagerHistory.aspx" in url:
            return Response(url, HISTORY_HTML)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data, **kwargs):
        self.calls.append(("POST", url, {"data": data, **kwargs}))
        assert url == wagerhub.LOGIN_URL
        assert data == {"IdBook": "15,42", "account": "owner", "password": "secret", "btn_login": "Login"}
        return Response("https://classic.wagerhub888.com/Home.aspx",
                        '<iframe src="/Menu.aspx"></iframe><a href="/wager/ConfirmWager.aspx">Confirm</a>')


def test_only_same_site_read_pages_are_allowed():
    assert wagerhub._safe_url("https://classic.wagerhub888.com/reports/History.aspx?days=7") \
        == "https://classic.wagerhub888.com/reports/History.aspx?days=7"
    assert wagerhub._safe_url("https://mobile.wagerhub888.com/reports/History.aspx") \
        == "https://mobile.wagerhub888.com/reports/History.aspx"
    for url in [
        "http://classic.wagerhub888.com/reports/History.aspx",
        "https://example.com/history",
        "https://wagerhub888.com.example.com/history",
        "https://classic.wagerhub888.com/wager/ConfirmWager.aspx?WT=0",
        "https://classic.wagerhub888.com/cashier/withdraw.aspx",
        "https://classic.wagerhub888.com/account/transferfund.aspx",
    ]:
        with pytest.raises(wagerhub.WagerHubSafetyError):
            wagerhub._safe_url(url)


def test_history_table_and_summary_are_normalized():
    rows, headers = wagerhub.parse_history_tables(HISTORY_HTML, "/reports/WagerHistory.aspx")
    assert headers == [["Date", "Ticket", "Wager", "Risk", "Win/Loss", "Result"]]
    assert rows[0]["Ticket"] == "101"
    assert rows[0]["_source"] == "/reports/WagerHistory.aspx"
    assert wagerhub.summarize(rows) == {
        "records": 3, "settled": 3, "wins": 1, "losses": 1, "pushes": 1,
        "win_pct": 50.0, "risked": 300.0, "net": -10.0, "roi_pct": -3.3,
    }


def test_live_score_and_odds_tables_are_kept_separately():
    rows, headers = wagerhub.parse_live_tables(
        "<table><tr><th>Match</th><th>Score</th><th>Spread</th><th>Total</th></tr>"
        "<tr><td>DEN @ PIT</td><td>7-3</td><td>DEN -3.5</td><td>36.5</td></tr></table>", "/live")
    assert headers == [["Match", "Score", "Spread", "Total"]]
    assert rows == [{"Match": "DEN @ PIT", "Score": "7-3", "Spread": "DEN -3.5",
                     "Total": "36.5", "_source": "/live"}]


def test_total_payout_is_not_mistaken_for_net_profit():
    rows, _ = wagerhub.parse_history_tables(
        "<table><tr><th>Ticket</th><th>Risk</th><th>Payout</th><th>Status</th></tr>"
        "<tr><td>1</td><td>$100</td><td>$190</td><td>Win</td></tr></table>")
    summary = wagerhub.summarize(rows)
    assert summary["wins"] == 1
    assert summary["risked"] == 100.0
    assert summary["net"] is None
    assert summary["roi_pct"] is None


def test_money_totals_are_hidden_when_any_settled_row_lacks_amounts():
    rows = [
        {"Ticket": "1", "Status": "Win", "Risk": "$100", "Net": "+$90"},
        {"Ticket": "2", "Status": "Loss", "Risk": "", "Net": ""},
    ]
    summary = wagerhub.summarize(rows)
    assert (summary["wins"], summary["losses"], summary["win_pct"]) == (1, 1, 50.0)
    assert summary["risked"] is None
    assert summary["net"] is None
    assert summary["roi_pct"] is None


def test_push_only_summary_has_no_division_or_format_error():
    summary = wagerhub.summarize([{"Status": "Push", "Risk": "$100", "Net": "$0"}])
    assert summary["win_pct"] is None
    assert "win n/a" in wagerhub._summary_line(summary)


def test_login_discovers_history_but_never_requests_confirm_page(tmp_path):
    session = Session()
    client = wagerhub.WagerHubClient(session)
    client.login("owner", "secret")
    result = client.collect(tmp_path)
    assert result["summary"]["wins"] == 1
    assert result["summary"]["losses"] == 1
    assert result["summary"]["pushes"] == 1
    requested = [url for method, url, kwargs in session.calls]
    assert not any("ConfirmWager" in url for url in requested)
    assert [method for method, url, kwargs in session.calls].count("POST") == 1
    assert all(method == "GET" or url == wagerhub.LOGIN_URL for method, url, kwargs in session.calls)
    discovery = json.loads((tmp_path / "data/private/wagerhub_discovery.json").read_text("utf-8"))
    assert "/reports/WagerHistory.aspx" in discovery["visited_paths"]
    assert "private" not in json.dumps(discovery)
    history = json.loads((tmp_path / "data/private/wagerhub_history.json").read_text("utf-8"))
    assert history["summary"]["roi_pct"] == -3.3
    assert stat.S_IMODE((tmp_path / "data/private/wagerhub_history.json").stat().st_mode) == 0o600


def test_credentials_are_private_and_rejected_if_permissions_are_broad(tmp_path):
    path = wagerhub.save_credentials(tmp_path, "owner", "secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert wagerhub.load_credentials(tmp_path) == ("owner", "secret")
    path.chmod(0o644)
    with pytest.raises(wagerhub.WagerHubAuthError, match="chmod 600"):
        wagerhub.load_credentials(tmp_path)


def test_failed_setup_never_saves_credentials_or_prints_password(tmp_path, capsys):
    class BadClient:
        def login(self, username, password):
            raise wagerhub.WagerHubAuthError("Đăng nhập không thành công.")

    code = wagerhub.setup(tmp_path, input_fn=lambda prompt: "owner", getpass_fn=lambda prompt: "super-secret",
                          client_factory=BadClient)
    assert code == 7
    assert not (tmp_path / wagerhub.CREDENTIAL_FILE).exists()
    assert "super-secret" not in capsys.readouterr().out


def test_login_page_or_session_end_is_not_accepted():
    class BadSession(Session):
        def post(self, url, data, **kwargs):
            return Response("https://classic.wagerhub888.com/SessionEnd.aspx",
                            '<input name="account"><input type="password" name="password">')

    with pytest.raises(wagerhub.WagerHubAuthError, match="không thành công"):
        wagerhub.WagerHubClient(BadSession()).login("owner", "secret")


def test_cli_dispatches_setup_and_collect_from_the_repo_root(tmp_path, monkeypatch):
    from actions_tracker.cli import main
    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wagerhub, "setup", lambda root: called.append(("setup", root)) or 0)
    monkeypatch.setattr(wagerhub, "collect", lambda root: called.append(("collect", root)) or 0)
    assert main(["wagerhub-setup"]) == 0
    assert main(["wagerhub-collect"]) == 0
    assert called == [("setup", tmp_path), ("collect", tmp_path)]
