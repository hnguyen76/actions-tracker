"""Game-time weather: ESPN venue + short forecast, Open-Meteo hourly numbers at kickoff for outdoor games."""

from actions_tracker import db, weather

NOW = "2026-11-15T12:00:00.000Z"
KICK = "2026-11-15T18:00:00.000Z"


class _R:
    def __init__(self, data, code=200):
        self._d, self.status_code = data, code

    def json(self):
        return self._d


def _get(url, params=None, **k):
    if "geocoding" in url:
        return _R({"results": [{"name": "Cleveland", "admin1": "Tennessee", "latitude": 35.1, "longitude": -84.8},
                               {"name": "Cleveland", "admin1": "Ohio", "latitude": 41.5, "longitude": -81.7}]})
    assert params["latitude"] == 41.5                      # the Ohio Cleveland, matched by state
    return _R({"hourly": {"time": ["2026-11-15T17:00", "2026-11-15T18:00"], "temperature_2m": [45, 46],
                          "precipitation_probability": [3, 4], "wind_speed_10m": [12, 14], "wind_gusts_10m": [20, 24]}})


def test_parse_venue_and_store_outdoor_and_indoor(tmp_path):
    ev = {"weather": {"displayValue": "Cloudy", "temperature": 47}}
    comp = {"venue": {"fullName": "Huntington Bank Field", "address": {"city": "Cleveland", "state": "OH"}, "indoor": False}}
    v = weather.parse_venue(ev, comp)
    assert v == {"venue": "Huntington Bank Field", "city": "Cleveland", "state": "OH", "indoor": False,
                 "condition": "Cloudy", "temp_f": 47}
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [dict(id=1, league="nfl", start_time=KICK, home_abbr="CLE", away_abbr="HOU"),
                        dict(id=2, league="nfl", start_time=KICK, home_abbr="DET", away_abbr="NE")], "t")
    dome = dict(v, venue="Ford Field", city="Detroit", state="MI", indoor=True, temp_f=None, condition=None)
    assert weather.store_weather(c, {1: {"start_time": KICK, "venue": v}, 2: {"start_time": KICK, "venue": dome}},
                                 NOW, get=_get) == 2
    t = weather.weather_table(c, NOW).set_index("game_id")
    assert (t.loc[1, "temp_f"], t.loc[1, "precip_pct"], t.loc[1, "wind_mph"], t.loc[1, "gust_mph"]) == (46, 4, 14, 24)
    assert t.loc[2, "indoor"] == 1 and t.loc[2, "wind_mph"] is None or t.loc[2, "indoor"] == 1
    # refreshed at most hourly
    assert weather.store_weather(c, {1: {"start_time": KICK, "venue": v}}, "2026-11-15T12:30:00.000Z", get=_get) == 0
