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
    pass


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
        raise TrafficError(f"GoatCounter HTTP {response.status_code}")
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
    locations = _json(get, api + "/stats/locations", token, params | {"limit": 100})
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
    if current >= 20 and current >= max(20, baseline * 5):
        warnings.append(f"traffic tăng bất thường {current} lượt/giờ (mức thường {baseline:g})")
    if health_status != 200:
        warnings.append(f"site HTTP {health_status or 'lỗi'}")
    elif health_ms >= 8000:
        warnings.append(f"site phản hồi chậm {health_ms / 1000:.1f}s")
    pages = _top(hits.get("hits"), events=False)
    sections = _top(hits.get("hits"), events=True)
    places = _top(locations.get("stats"))
    alert = " · ".join(warnings)
    conn.execute(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO traffic_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
        hour.isoformat(), moment.isoformat(), int(total.get("total") or 0), int(total.get("total_events") or 0),
        current, health_ms, health_status, alert, json.dumps(hourly), json.dumps(pages, ensure_ascii=False),
        json.dumps(sections, ensure_ascii=False), json.dumps(places, ensure_ascii=False)))
    conn.commit()
    token_tg, chat = alerts.load_telegram(root)
    if token_tg and chat:
        top = sections[0]["name"] if sections else (pages[0]["name"] if pages else "chưa có")
        local = moment.astimezone(ET)
        text = (f"📊 TRAFFIC {local:%H:%M ET}\n"
                f"👥 Hôm nay: {int(total.get('total') or 0)} · giờ này: {current}\n"
                f"🔥 Xem nhiều: {top}\n"
                f"🌎 {', '.join(f'{x['name']} {x['count']}' for x in places[:3]) or 'chưa có vị trí'}\n"
                f"🛡 Site: HTTP {health_status or 'lỗi'} · {health_ms}ms")
        if alert:
            text += f"\n🚨 CẢNH BÁO: {alert}"
        alerts.send_telegram(token_tg, chat, text, post=post)
    return {"visitors": int(total.get("total") or 0), "current_hour": current, "alert": alert}


def tables(conn) -> dict[str, pd.DataFrame]:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='traffic_snapshots'").fetchone()
    if not exists:
        empty = pd.DataFrame()
        return {"Traffic_History": empty, "Traffic_Hourly": empty, "Traffic_Pages": empty,
                "Traffic_Sections": empty, "Traffic_Locations": empty}
    rows = [dict(x) for x in conn.execute("SELECT * FROM traffic_snapshots ORDER BY hour_utc DESC LIMIT 72")]
    if not rows:
        empty = pd.DataFrame()
        return {"Traffic_History": empty, "Traffic_Hourly": empty, "Traffic_Pages": empty,
                "Traffic_Sections": empty, "Traffic_Locations": empty}
    latest = rows[0]
    def unpack(key):
        return pd.DataFrame(json.loads(latest[key] or "[]"))
    history = pd.DataFrame([{k: r[k] for k in ("hour_utc", "captured_at", "visitors", "events", "current_hour",
                                                        "health_ms", "health_status", "alert")} for r in rows])
    hourly = pd.DataFrame([{"hour": f"{i:02d}:00", "count": n} for i, n in enumerate(json.loads(latest["hourly_json"]))])
    return {"Traffic_History": history, "Traffic_Hourly": hourly, "Traffic_Pages": unpack("pages_json"),
            "Traffic_Sections": unpack("sections_json"), "Traffic_Locations": unpack("locations_json")}
