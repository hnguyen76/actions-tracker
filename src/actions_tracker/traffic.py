"""Cookieless GoatCounter traffic snapshots and hourly Telegram summaries."""

from __future__ import annotations

import getpass
import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from actions_tracker import alerts

SITE_CODE = "hieumercer"
TOKEN_FILE = ".goatcounter_api_token"
DASHBOARD = "https://hnguyen76.github.io/actions-tracker/"
ET = ZoneInfo("America/New_York")
SCHEMA = ("CREATE TABLE IF NOT EXISTS traffic_snapshots("
          "hour_utc TEXT PRIMARY KEY, captured_at TEXT, visitors INTEGER, events INTEGER, current_hour INTEGER, "
          "health_ms INTEGER, health_status INTEGER, alert TEXT, hourly_json TEXT, pages_json TEXT, "
          "sections_json TEXT, locations_json TEXT)")


class TrafficError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def setup(root: Path) -> int:
    token = getpass.getpass("Dán GoatCounter API token (sẽ không hiện trên màn hình): ").strip()
    if not token:
        print("Chưa nhập API token.")
        return 6
    path = root / TOKEN_FILE
    path.write_text(token, "utf-8")
    os.chmod(path, 0o600)
    print("Đã lưu API token an toàn trên S21. Chạy: bash scripts/auto_update.sh traffic")
    return 0


def _token(root: Path) -> str | None:
    try:
        return (root / TOKEN_FILE).read_text("utf-8").strip() or None
    except OSError:
        return None


def _json(get, url: str, token: str, params: dict) -> dict:
    response = get(url, params=params, headers={"Authorization": f"Bearer {token}",
                                                "Content-Type": "application/json"}, timeout=20)
    if response.status_code != 200:
        endpoint = url.split("/api/v0/", 1)[-1]
        detail = ""
        try:
            error = response.json()
            if isinstance(error, dict):
                detail = str(error.get("error") or error.get("errors") or "").strip()
        except (ValueError, TypeError):
            pass
        suffix = f": {detail}" if detail else ""
        raise TrafficError(f"GoatCounter {endpoint} HTTP {response.status_code}{suffix}",
                           status=int(response.status_code))
    value = response.json()
    if not isinstance(value, dict):
        raise TrafficError("GoatCounter trả dữ liệu không hợp lệ")
    return value


def _hourly(stats: list[dict], day: str) -> list[int]:
    row = next((x for x in stats if str(x.get("day")) == day), {})
    values = row.get("hourly") or []
    return [int(x or 0) for x in values[:24]] + [0] * max(0, 24 - len(values))


def _top(items, *, events: bool | None = None, limit: int = 8) -> list[dict]:
    out = []
    for item in items or []:
        if events is not None and bool(item.get("event")) != events:
            continue
        out.append({"name": str(item.get("title") or item.get("path") or item.get("name") or "–")[:100],
                    "path": str(item.get("path") or ""), "count": int(item.get("count") or 0)})
    return sorted(out, key=lambda x: (-x["count"], x["name"]))[:limit]


def collect(conn, root: Path, now: str, get=requests.get, post=requests.post) -> dict:
    token = _token(root)
    if not token:
        raise TrafficError(f"chưa có {TOKEN_FILE}; chạy `python -m actions_tracker traffic-setup`")
    moment = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc)
    hour = moment.replace(minute=0, second=0, microsecond=0)
    start = hour.astimezone(ET).replace(hour=0).astimezone(timezone.utc)
    end = hour + timedelta(hours=1)
    params = {"start": start.isoformat(), "end": end.isoformat()}
    api = f"https://{SITE_CODE}.goatcounter.com/api/v0"
    total = _json(get, api + "/stats/total", token, params)
    hits = _json(get, api + "/stats/hits", token, params | {"limit": 100})
    try:
        locations = _json(get, api + "/stats/locations", token, params | {"limit": 100})
    except TrafficError as exc:
        # Location analytics may be unavailable/disabled on a GoatCounter site. It must not prevent
        # total, hourly and per-page traffic from being saved and published.
        if exc.status not in {403, 404}:
            raise
        locations = {"stats": []}
    day_utc = hour.strftime("%Y-%m-%d")
    hourly = _hourly(total.get("stats") or [], day_utc)
    current = hourly[hour.hour]
    prior = hourly[:hour.hour]
    baseline = statistics.median(prior) if prior else 0
    started = time.monotonic()
    try:
        health = get(DASHBOARD, timeout=15, headers={"Cache-Control": "no-cache"})
        health_status = int(health.status_code)
    except requests.RequestException:
        health_status = 0
    health_ms = round((time.monotonic() - started) * 1000)
    warnings = []
    if health_status != 200:
        warnings.append(f"site HTTP {health_status or 'lỗi'}")
    elif health_ms >= 8000:
        warnings.append(f"site phản hồi chậm {health_ms / 1000:.1f}s")
    hit_rows = hits.get("hits") or []
    city_rows = [x for x in hit_rows if str(x.get("path") or "").startswith("geo-city-")]
    unique_rows = [x for x in hit_rows if str(x.get("path") or "").startswith("unique-visitor-")]
    active_rows = [x for x in hit_rows if str(x.get("path") or "").startswith("active-hour-")]
    local = moment.astimezone(ET)
    local_day = local.strftime("%Y-%m-%d")
    unique_today = [int(x.get("count") or 0) for x in unique_rows
                    if str(x.get("path") or "") == f"unique-visitor-{local_day}"]
    active_hourly = [0] * 24
    for item in active_rows:
        path = str(item.get("path") or "")
        prefix = f"active-hour-{local_day}-"
        if not path.startswith(prefix):
            continue
        try:
            index = int(path[len(prefix):])
        except ValueError:
            continue
        if 0 <= index < 24:
            active_hourly[index] = max(active_hourly[index], int(item.get("count") or 0))
    if any(active_hourly):
        hourly = active_hourly
        current = hourly[local.hour]
        prior = hourly[:local.hour]
        baseline = statistics.median(prior) if prior else 0
    if current >= 20 and current >= max(20, baseline * 5):
        warnings.append(f"traffic tăng bất thường {current} người/giờ (mức thường {baseline:g})")
    pages = _top(hit_rows, events=False)
    internal_rows = city_rows + unique_rows + active_rows
    sections = _top([x for x in hit_rows if x not in internal_rows], events=True)
    # Browser-side city events contain only an approximate city label; no IP is sent to this app or stored.
    places = _top(city_rows, events=True) or _top(locations.get("stats"))
    alert = " · ".join(warnings)
    pageviews = max(0, int(total.get("total") or 0) - int(total.get("total_events") or 0))
    unique_visitors = max(unique_today, default=pageviews)
    conn.execute(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO traffic_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
        hour.isoformat(), moment.isoformat(), unique_visitors, int(total.get("total_events") or 0),
        current, health_ms, health_status, alert, json.dumps(hourly), json.dumps(pages, ensure_ascii=False),
        json.dumps(sections, ensure_ascii=False), json.dumps(places, ensure_ascii=False)))
    conn.commit()
    token_tg, chat = alerts.load_telegram(root)
    if token_tg and chat:
        top = sections[0]["name"] if sections else (pages[0]["name"] if pages else "chưa có")
        text = (f"📊 TRAFFIC {local:%H:%M ET}\n"
                f"👥 Unique hôm nay: {unique_visitors} · active trong giờ: {current}\n"
                f"🔥 Xem nhiều: {top}\n"
                f"🌎 {', '.join(f'{x['name']} {x['count']}' for x in places[:3]) or 'chưa có vị trí'}\n"
                f"🛡 Site: HTTP {health_status or 'lỗi'} · {health_ms}ms")
        if alert:
            text += f"\n🚨 CẢNH BÁO: {alert}"
        alerts.send_telegram(token_tg, chat, text, post=post)
    return {"visitors": unique_visitors, "current_hour": current, "alert": alert}


def tables(conn) -> dict[str, pd.DataFrame]:
    empty_tables = {"Traffic_History": pd.DataFrame(), "Traffic_Hourly": pd.DataFrame(),
                    "Traffic_Pages": pd.DataFrame(), "Traffic_Sections": pd.DataFrame(),
                    "Traffic_Locations": pd.DataFrame(), "Traffic_Daily": pd.DataFrame(),
                    "Traffic_Weekly": pd.DataFrame(), "Traffic_Monthly": pd.DataFrame()}
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='traffic_snapshots'").fetchone()
    if not exists:
        return empty_tables
    rows = [dict(x) for x in conn.execute("SELECT * FROM traffic_snapshots ORDER BY hour_utc DESC")]
    if not rows:
        return empty_tables
    latest = rows[0]
    def unpack(key):
        return pd.DataFrame(json.loads(latest[key] or "[]"))
    history = pd.DataFrame([{k: r[k] for k in ("hour_utc", "captured_at", "visitors", "events", "current_hour",
                                                        "health_ms", "health_status", "alert")} for r in rows[:72]])
    hourly = pd.DataFrame([{"hour": f"{i:02d}:00", "count": n} for i, n in enumerate(json.loads(latest["hourly_json"]))])
    by_day: dict[str, int] = {}
    for row in rows:
        try:
            date = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00")).astimezone(ET).date()
        except (TypeError, ValueError):
            continue
        key = date.isoformat()
        by_day[key] = max(by_day.get(key, 0), int(row["visitors"] or 0))
    daily_rows = [{"period": day, "visitors": count} for day, count in sorted(by_day.items(), reverse=True)]
    by_week: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for day, count in by_day.items():
        date = datetime.strptime(day, "%Y-%m-%d").date()
        week = (date - timedelta(days=date.weekday())).isoformat()
        month = date.strftime("%Y-%m")
        by_week[week] = by_week.get(week, 0) + count
        by_month[month] = by_month.get(month, 0) + count
    weekly = [{"period": key, "visitors": value} for key, value in sorted(by_week.items(), reverse=True)]
    monthly = [{"period": key, "visitors": value} for key, value in sorted(by_month.items(), reverse=True)]
    return {"Traffic_History": history, "Traffic_Hourly": hourly, "Traffic_Pages": unpack("pages_json"),
            "Traffic_Sections": unpack("sections_json"), "Traffic_Locations": unpack("locations_json"),
            "Traffic_Daily": pd.DataFrame(daily_rows), "Traffic_Weekly": pd.DataFrame(weekly),
            "Traffic_Monthly": pd.DataFrame(monthly)}
