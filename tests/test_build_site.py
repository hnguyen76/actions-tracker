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
    for asset in ("live-scores.js", "scoreboard.js", "scoreboard.css", "dashboard.css"):
        assert asset in html
        assert (out.parent / asset).is_file()


def test_thanksgiving_logo_play_is_infrequent_decorative_and_motion_safe(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'class="logo-play"' in html and 'class="brand-static"' in html
    assert ".season-thanksgiving .logo-play" in css and "24s ease-in-out infinite" in css
    assert 'class="logo-fall"' in html and css.count("animation: logo-leaf-") == 5
    assert 'class="logo-snow"' in html and css.count("animation: logo-snow-") == 6
    assert "logo-wind" not in html and "logo-wind" not in css
    assert "@keyframes logo-air-gust" in css and "animation: logo-air-gust" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".season-thanksgiving .logo-play, .season-thanksgiving .logo-fall, .season-thanksgiving .logo-snow { display: none; }" in css


def test_winter_logo_story_catches_trips_and_lands_the_ball_on_a_tree(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'class="holiday-story"' in html and "season-winter-story" in html
    for character in ("holiday-turkey-runner", "holiday-snowman", "holiday-tree", "holiday-football"):
        assert f'class="{character}"' in html
    for motion in ("holiday-turkey-trip", "holiday-ball-flight", "holiday-snowman-hit", "holiday-tree-bump"):
        assert f"@keyframes {motion}" in css
    assert "24s cubic-bezier" in css
    assert ".season-winter-story .holiday-story { display: none; }" in css


def test_decision_pick_count_highlights_have_three_flashing_levels(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'n > 14 ? "heat-purple" : n > 10 ? "heat-green" : n >= HOT_PICKS ? "heat-yellow"' in html
    for name in ("heat-yellow", "heat-green", "heat-purple"):
        assert name in css
    assert "@keyframes decision-heat-cell" in css and "@keyframes decision-heat-card" in css


def test_mobile_game_cards_start_collapsed_and_are_keyboard_accessible(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'Object.assign(rowAttrs, { role: "button", tabindex: "0", "aria-expanded": "false" })' in html
    assert 'row.setAttribute("aria-expanded", String(row.classList.contains("open")))' in html
    assert 'if (e.key !== "Enter" && e.key !== " ") return' in html
    assert 'open: true' not in html


def test_mobile_nav_uses_one_active_background(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert '.bottombar button[aria-current="page"] svg { background: transparent;' in css
    assert '.bottombar button[aria-current="page"] { color: var(--accent); background:' in css
    assert '-webkit-tap-highlight-color: transparent' in css
    assert 'svg { background: var(--accent-wash)' not in css


def test_decision_days_are_icon_only_but_accessible(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    assert 'class="decide-title-icon"' in html and 'class: "day-calendar"' in html
    assert '"aria-label": label, title: label' in html
    assert 'svgEl("text", { x: "20", y: "29" }, day)' in html
    assert 'isWeekend = weekday === 0 || weekday === 6' in html
    assert 'class: `day-chip${isWeekend ? " weekend" : ""}`' in html
    assert '.day-chip.weekend' in html and 'color: var(--warning)' in html
    assert 'class: "day-chip", "aria-pressed": String(d === state.day), text: dayLabel(d)' not in html
    assert 'document.getElementById("decide-title").textContent' not in html


def test_site_version_changes_with_the_template_or_a_static_file():
    from actions_tracker.build_site import site_version
    base = site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"2")])
    assert base == site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"2")])
    assert len(base) == 10
    assert site_version("<html>B</html>", [("a.js", b"1"), ("b.css", b"2")]) != base   # a design change in the page itself
    assert site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"3")]) != base   # a change in a static file
