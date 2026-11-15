import json
import re

import numpy as np
import pandas as pd

from actions_tracker.build_site import build_site


def _data(html):
    return json.loads(re.search(r"const DATA = (.*?);\n", html, re.S).group(1))


def test_embeds_json_and_copies_xlsx(tmp_path):
    x = tmp_path / "r.xlsx"
    x.write_bytes(b"x")
    t = {"Upcoming": pd.DataFrame([{"game_id": np.int64(1), "majority_pct": float("nan"), "heavy": np.bool_(True),
                                    "note": "</script>"}])}
    out = build_site(t, [{"league": "nfl", "last_success_at": "t"}], tmp_path / "site", x, "2026-11-09T00:00:00Z")
    html = out.read_text("utf-8")
    d = _data(html)
    row = d["tables"]["Upcoming"][0]
    assert row["majority_pct"] is None and row["game_id"] == 1 and row["heavy"] is True
    assert d["generated_at"] == "2026-11-09T00:00:00Z" and d["league_status"][0]["league"] == "nfl"
    assert "</script>" not in html.split("const DATA = ")[1].split(";\n")[0]
    assert (tmp_path / "site" / "actions_report.xlsx").exists()
    assert 'name="robots" content="noindex"' in html and "chart.umd.min.js" in html


def test_empty_tables_render(tmp_path):
    out = build_site({}, [], tmp_path / "s", None, "t")
    html = out.read_text("utf-8")
    assert "Chưa có dữ liệu" in html
    assert _data(html)["tables"] == {}


def test_live_score_assets_are_published_with_dashboard(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    for asset in ("live-scores.js", "scoreboard.js", "scoreboard.css"):
        assert asset in html
        assert (out.parent / asset).is_file()


def test_mobile_game_cards_start_collapsed_and_are_keyboard_accessible(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'Object.assign(rowAttrs, { role: "button", tabindex: "0", "aria-expanded": "false" })' in html
    assert 'row.setAttribute("aria-expanded", String(row.classList.contains("open")))' in html
    assert 'if (e.key !== "Enter" && e.key !== " ") return' in html
    assert 'open: true' not in html
