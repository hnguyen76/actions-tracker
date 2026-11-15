"""Game-time weather for upcoming football games (free sources, no key).

ESPN's scoreboard already says where a game is played and whether the stadium is indoors, plus a short
forecast (temperature, condition). For outdoor games the hourly forecast at kickoff (temperature, chance of
rain, wind, gusts) comes from Open-Meteo, geocoded from the stadium's city/state and cached.
"""

import sqlite3

import pandas as pd
import requests

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
REFRESH_H = 1.0  # a game's forecast is refreshed at most hourly
WEATHER_COLS = ["game_id", "venue", "city", "state", "indoor", "condition", "temp_f", "precip_pct", "wind_mph",
                "gust_mph", "updated_at"]
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}


def parse_venue(event: dict, comp: dict) -> dict:
    v = comp.get("venue") or {}
    w = event.get("weather") or comp.get("weather") or {}
    addr = v.get("address") or {}
    return {"venue": v.get("fullName"), "city": addr.get("city"), "state": addr.get("state"),
            "indoor": bool(v.get("indoor")), "condition": w.get("displayValue"),
            "temp_f": w.get("temperature")}


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS game_weather(
        game_id INTEGER PRIMARY KEY, venue TEXT, city TEXT, state TEXT, indoor INTEGER, condition TEXT,
        temp_f REAL, precip_pct REAL, wind_mph REAL, gust_mph REAL, updated_at TEXT)""")
    conn.execute("CREATE TABLE IF NOT EXISTS geo_cache(city TEXT, state TEXT, lat REAL, lon REAL, PRIMARY KEY(city, state))")


def _geocode(conn, city, state, get):
    row = conn.execute("SELECT lat, lon FROM geo_cache WHERE city=? AND state=?", (city, state)).fetchone()
    if row:
        return (row[0], row[1]) if row[0] is not None else None
    r = get(GEO, params={"name": city, "count": 10, "country": "US"}, timeout=30)
    hits = (r.json() or {}).get("results", []) if r.status_code == 200 else []
    want = STATES.get(str(state or "").upper(), state)
    hit = next((h for h in hits if h.get("admin1") == want), hits[0] if hits and not state else None)
    lat, lon = (hit["latitude"], hit["longitude"]) if hit else (None, None)
    conn.execute("INSERT OR REPLACE INTO geo_cache VALUES (?,?,?,?)", (city, state, lat, lon))
    return (lat, lon) if hit else None


def _forecast(lat, lon, kickoff: str, get):
    r = get(FORECAST, timeout=30, params={
        "latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": 7,
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph"})
    if r.status_code != 200:
        return None
    h = (r.json() or {}).get("hourly") or {}
    times = h.get("time") or []
    target = pd.Timestamp(kickoff).tz_convert("UTC").floor("h").strftime("%Y-%m-%dT%H:%M")
    if target not in times:
        return None
    i = times.index(target)
    pick = lambda k: (h.get(k) or [None] * len(times))[i]  # noqa: E731
    return {"temp_f": pick("temperature_2m"), "precip_pct": pick("precipitation_probability"),
            "wind_mph": pick("wind_speed_10m"), "gust_mph": pick("wind_gusts_10m")}


def store_weather(conn: sqlite3.Connection, games: dict, now: str, get=requests.get) -> int:
    """games: {game_id: {"start_time", "venue": parse_venue(...)}} for upcoming games. Returns games updated."""
    _schema(conn)
    done = 0
    for gid, g in games.items():
        v = g.get("venue") or {}
        if not v.get("venue"):
            continue
        last = conn.execute("SELECT updated_at FROM game_weather WHERE game_id=?", (gid,)).fetchone()
        if last and pd.Timestamp(now) - pd.Timestamp(last[0]) < pd.Timedelta(hours=REFRESH_H):
            continue
        row = {"temp_f": v.get("temp_f"), "precip_pct": None, "wind_mph": None, "gust_mph": None}
        if not v.get("indoor") and v.get("city"):
            try:
                where = _geocode(conn, v["city"], v.get("state"), get)
                fc = _forecast(*where, g["start_time"], get) if where else None
                if fc:
                    row.update({k: x for k, x in fc.items() if x is not None})
            except (requests.RequestException, ValueError, KeyError):
                pass  # keep ESPN's short forecast
        conn.execute("INSERT OR REPLACE INTO game_weather VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (gid, v.get("venue"), v.get("city"), v.get("state"), int(bool(v.get("indoor"))),
                      v.get("condition"), row["temp_f"], row["precip_pct"], row["wind_mph"], row["gust_mph"], now))
        done += 1
    conn.commit()
    return done


def weather_table(conn: sqlite3.Connection, now: str) -> pd.DataFrame:
    _schema(conn)
    since = (pd.Timestamp(now) - pd.Timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = conn.execute("SELECT w.* FROM game_weather w JOIN games g ON g.id = w.game_id WHERE g.start_time >= ?",
                        (since,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows], columns=WEATHER_COLS)
