import json

from actions_tracker import db, traffic


class Response:
    def __init__(self, body=None, status=200):
        self.body, self.status_code = body or {}, status

    def json(self):
        return self.body


def test_collects_cookieless_stats_and_builds_dashboard_tables(tmp_path, monkeypatch):
    (tmp_path / traffic.TOKEN_FILE).write_text("secret", "utf-8")
    hourly = [0] * 24
    hourly[17] = 7
    def get(url, **kwargs):
        if url == traffic.DASHBOARD:
            return Response()
        if url.endswith("/stats/total"):
            return Response({"total": 12, "total_events": 8, "stats": [{"day": "2026-11-26", "hourly": hourly}]})
        if url.endswith("/stats/hits"):
            return Response({"hits": [{"title": "Actions", "path": "/", "count": 4, "event": False},
                                        {"title": "Kèo", "path": "tab-upcoming", "count": 8, "event": True}]})
        if url.endswith("/stats/locations"):
            return Response({"stats": [{"name": "United States", "count": 10}]})
        raise AssertionError(url)
    monkeypatch.setattr(traffic.alerts, "load_telegram", lambda root: (None, None))
    conn = db.connect(tmp_path / "actions.db")
    result = traffic.collect(conn, tmp_path, "2026-11-26T17:20:00+00:00", get=get)
    assert result == {"visitors": 12, "current_hour": 7, "alert": ""}
    tables = traffic.tables(conn)
    assert tables["Traffic_Sections"].iloc[0].to_dict() == {"name": "Kèo", "path": "tab-upcoming", "count": 8}
    assert tables["Traffic_Locations"].iloc[0]["name"] == "United States"
    assert json.loads(conn.execute("SELECT hourly_json FROM traffic_snapshots").fetchone()[0])[17] == 7


def test_traffic_spike_is_labeled_as_anomaly(tmp_path, monkeypatch):
    (tmp_path / traffic.TOKEN_FILE).write_text("secret", "utf-8")
    hourly = [1] * 24
    hourly[17] = 25
    def get(url, **kwargs):
        if url == traffic.DASHBOARD:
            return Response()
        if url.endswith("/stats/total"):
            return Response({"total": 40, "total_events": 0, "stats": [{"day": "2026-11-26", "hourly": hourly}]})
        return Response({"hits": []} if url.endswith("/stats/hits") else {"stats": []})
    monkeypatch.setattr(traffic.alerts, "load_telegram", lambda root: (None, None))
    conn = db.connect(tmp_path / "actions.db")
    assert "tăng bất thường" in traffic.collect(conn, tmp_path, "2026-11-26T17:20:00+00:00", get=get)["alert"]


def test_location_404_does_not_discard_core_traffic(tmp_path, monkeypatch):
    (tmp_path / traffic.TOKEN_FILE).write_text("secret", "utf-8")
    hourly = [0] * 24
    hourly[17] = 3

    def get(url, **kwargs):
        if url == traffic.DASHBOARD:
            return Response()
        if url.endswith("/stats/total"):
            return Response({"total": 5, "total_events": 2,
                             "stats": [{"day": "2026-11-26", "hourly": hourly}]})
        if url.endswith("/stats/hits"):
            return Response({"hits": [{"title": "Kèo", "path": "tab-upcoming", "count": 2, "event": True}]})
        if url.endswith("/stats/locations"):
            return Response({"error": "not available"}, status=404)
        raise AssertionError(url)

    monkeypatch.setattr(traffic.alerts, "load_telegram", lambda root: (None, None))
    conn = db.connect(tmp_path / "actions.db")
    assert traffic.collect(conn, tmp_path, "2026-11-26T17:20:00+00:00", get=get)["visitors"] == 5
    tables = traffic.tables(conn)
    assert tables["Traffic_Locations"].empty
    assert tables["Traffic_Sections"].iloc[0]["name"] == "Kèo"


def test_goatcounter_error_names_the_failed_endpoint():
    def get(url, **kwargs):
        return Response({"error": "bad range"}, status=404)

    try:
        traffic._json(get, "https://example.goatcounter.com/api/v0/stats/total", "secret", {})
    except traffic.TrafficError as exc:
        assert exc.status == 404
        assert str(exc) == "GoatCounter stats/total HTTP 404: bad range"
    else:
        raise AssertionError("expected TrafficError")
