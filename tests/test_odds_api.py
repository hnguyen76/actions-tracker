import json
import pathlib

import pytest

from actions_tracker.odds_api import OddsApi, OddsApiError, load_key, parse_lines, parse_scores

F = pathlib.Path(__file__).parent / "fixtures"


def _load(league, kind):
    return json.loads((F / f"odds_{league}_{kind}.json").read_text("utf-8"))


@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_parse_scores_real(league):
    raw = _load(league, "scores")
    rows = parse_scores(raw)
    assert len(rows) == len(raw)
    done = [r for r in rows if r["completed"]]
    assert len(done) == sum(1 for e in raw if e["completed"])
    assert all(isinstance(r["home_score"], int) and isinstance(r["away_score"], int) for r in done)
    assert all(r["commence_time"].endswith(".000Z") for r in rows)


def test_parse_scores_maps_home_and_away():
    ev = [{"id": "e1", "commence_time": "2026-11-08T14:35:00Z", "completed": True, "home_team": "Atlanta Falcons",
           "away_team": "Cincinnati Bengals",
           "scores": [{"name": "Atlanta Falcons", "score": "17"}, {"name": "Cincinnati Bengals", "score": "34"}]}]
    r = parse_scores(ev)[0]
    assert (r["event_id"], r["home_score"], r["away_score"], r["commence_time"]) == ("e1", 17, 34, "2026-11-08T14:35:00.000Z")


def test_parse_scores_incomplete_has_no_score():
    ev = [{"id": "e2", "commence_time": "2026-11-10T01:15:00Z", "completed": False, "home_team": "A", "away_team": "B",
           "scores": None}]
    r = parse_scores(ev)[0]
    assert r["completed"] is False and r["home_score"] is None


def test_parse_lines_median_across_books():
    def book(sp_home, price_home, total, ml_home):
        return {"key": "b", "markets": [
            {"key": "spreads", "outcomes": [{"name": "Home", "price": price_home, "point": sp_home},
                                            {"name": "Away", "price": -110, "point": -sp_home}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": total},
                                           {"name": "Under", "price": -110, "point": total}]},
            {"key": "h2h", "outcomes": [{"name": "Home", "price": ml_home}, {"name": "Away", "price": 130}]}]}
    ev = [{"id": "e", "commence_time": "2026-11-10T01:15:00Z", "home_team": "Home", "away_team": "Away",
           "bookmakers": [book(-3, -110, 44.5, -150), book(-3.5, -105, 45.5, -160), book(-2.5, -120, 45, -140)]}]
    lines = {(l["market"], l["side"]): l for l in parse_lines(ev)}
    assert (lines[("spread", "home")]["line"], lines[("spread", "home")]["odds"]) == (-3.0, -110)
    assert lines[("spread", "away")]["line"] == 3.0
    assert lines[("total", "over")]["line"] == 45.0
    assert (lines[("ml", "home")]["line"], lines[("ml", "home")]["odds"]) == (None, -150)
    assert len(lines) == 6


def test_parse_lines_real_nfl_has_six_sides_per_event():
    raw = _load("nfl", "odds")
    rows = parse_lines(raw)
    per_event = {}
    for r in rows:
        per_event.setdefault(r["event_id"], set()).add((r["market"], r["side"]))
    priced = [e for e in raw if e["bookmakers"]]
    assert len(per_event) == len(priced)
    assert all(len(v) == 6 for v in per_event.values())


class _Resp:
    def __init__(self, code, data=None, remaining="480"):
        self.status_code, self._data, self.headers = code, data, {"x-requests-remaining": remaining}
        self.text = json.dumps(data)

    def json(self):
        return self._data


class _Sess:
    def __init__(self, seq):
        self.seq, self.calls, self.params = list(seq), 0, []

    def get(self, url, params=None, **kw):
        self.calls += 1
        self.params.append((url, params))
        return self.seq.pop(0)


def test_client_reads_remaining_and_params():
    s = _Sess([_Resp(200, [], "471")])
    api = OddsApi("k", session=s, sleep=lambda x: None)
    assert api.scores("ncaaf") == [] and api.remaining == 471
    url, params = s.params[0]
    assert "americanfootball_ncaaf/scores" in url and params["daysFrom"] == 3 and params["apiKey"] == "k"


def test_client_401_fails_fast():
    s = _Sess([_Resp(401, {"message": "bad key"})])
    with pytest.raises(OddsApiError):
        OddsApi("k", session=s, sleep=lambda x: None).odds("nfl")
    assert s.calls == 1


def test_load_key_env_first(tmp_path, monkeypatch):
    (tmp_path / ".odds_api_key").write_text(" filekey \n")
    monkeypatch.setenv("ODDS_API_KEY", "envkey")
    assert load_key(tmp_path) == "envkey"
    monkeypatch.delenv("ODDS_API_KEY")
    assert load_key(tmp_path) == "filekey"
    assert load_key(tmp_path / "nowhere") is None
