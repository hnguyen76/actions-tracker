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
    assert 'name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex"' in html
    assert 'name="googlebot" content="noindex, nofollow, noarchive, nosnippet, noimageindex"' in html
    assert 'name="referrer" content="no-referrer"' in html and "Content-Security-Policy" in html
    assert "chart.umd.min.js" in html and 'integrity="sha384-' in html
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html
    assert 'data-goatcounter="https://hieumercer.goatcounter.com/count"' in html
    assert (tmp_path / "site" / "robots.txt").read_text("utf-8") == "User-agent: *\nDisallow: /\n"


def test_empty_tables_render(tmp_path):
    out = build_site({}, [], tmp_path / "s", None, "t")
    html = out.read_text("utf-8")
    assert "Chưa có dữ liệu" in html
    assert _data(html)["tables"] == {}


def test_live_score_assets_are_published_with_dashboard(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    for asset in ("live-scores.js", "second-half.js", "scoreboard.js", "scoreboard.css", "dashboard.css"):
        assert asset in html
        assert (out.parent / asset).is_file()


def test_second_half_tab_sits_after_upcoming_and_uses_espn_odds(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert html.index('data-tab="upcoming"') < html.index('data-tab="second-half"') < html.index('data-tab="rules"')
    assert html.index('data-go="upcoming"') < html.index('data-go="second-half"') < html.index('data-go="past"')
    assert 'data-go="inplay"' not in html
    assert 'id="second-half-list"' in html
    assert 'id="second-half-day-summary"' in html and 'id="second-half-all-summary"' in html
    assert 'id="second-half-chart"' in html and 'Win% cộng dồn' in html
    assert 'T("Second_Half_Plays")' in html and 'T("Second_Half_Summary")' in html
    assert 'T("Second_Half")' in html and 'game.live_odds' in html
    assert 'ActionsSecondHalf.firstHalfScore(game, snapshot)' in html and '1H ${num(half[0])}' in html
    assert 'ActionsSecondHalf.decide(ActionsSecondHalf.withLockedLines(game, snapshot))' in html
    assert 'ActionsSecondHalf.winChance(p,' in html and 'T("Second_Half_Plays").filter' in html
    assert 'const allTracked = currentTab() === "second-half"' in html


def test_playoff_tab_has_espn_standings_and_transparent_models(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'data-tab="playoff"' in html and 'data-go="playoff"' in html
    assert 'T("NFL_Playoff")' in html and 'T("NCAAF_Playoff")' in html
    assert 'T("NCAAF_Standings")' in html and 'id="playoff-ncaaf-conf"' in html
    assert '5.000 lần mô phỏng' in html and 'không phải ESPN' in html
    assert '.playoff-chance' in css and '.playoff-in' in css and '.playoff-bubble' in css
    assert 'T("Pregame_Playoff")' in html and 'playoffContextCell' in html
    assert 'detailBlock("Playoff"' in html and 'Playoff trước trận' in html


def test_upcoming_has_espn_line_history_and_plus_to_minus_table(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'id="spread-flip-card"' in html and 'id="spread-flip-table"' in html
    assert 'T("Line_Movement")' in html and 'T("Spread_Flips")' in html
    assert 'T("Trend_Radar")' in html and 'T("Pick_Ratio_Matrix")' in html
    assert 'T("Method_Equity")' in html and 'T("Spread_Flip_Results")' in html
    assert 'id="trend-radar"' in html and 'id="ratio-matrix"' in html
    assert 'id="equity-chart"' in html and 'id="spread-flip-results"' in html
    assert 'Lịch sử line ESPN' in html and 'lineMovementDetail' in html
    assert 'line|${r.game_id}|${r.market}' in html


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


def test_today_selected_pick_ratios_are_white_and_other_heat_levels_remain(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'new Set(["2/3", "3/4", "4/5", "6/7"])' in html
    assert 'todayWhitePickRatio(r) ? "heat-white"' in html
    assert 'if (todayWhitePickRatio(r)) return "heat-white"' in html
    assert 'n > 14 ? "heat-purple" : n > 10 ? "heat-green" : n >= HOT_PICKS ? "heat-yellow"' in html
    for name in ("heat-white", "heat-yellow", "heat-green", "heat-purple"):
        assert name in css
    assert "@keyframes decision-heat-cell" in css and "@keyframes decision-heat-card" in css


def test_weekday_three_pick_trend_is_highlighted_and_labeled(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'new Set(["3/3", "3/4"])' in html
    assert 'weekdayThreePickTrend(r) ? "heat-three"' in html
    assert 'text: "🔥 3 PICKS"' in html
    assert 'Trend weekday 3/3–3/4 · theo majority expert' in html
    assert '.heat-three { --decision-heat: #38bdf8; }' in css
    assert '.three-pick-trend' in css


def test_spread_flip_rule_has_a_visible_decision_badge(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'includes("spread_flip_follow")' in html
    assert 'text: "⇄ +→−"' in html
    assert 'return "spread-flip-rule-row"' in html
    assert ".line-flip-rule" in css and ".crow.spread-flip-rule-row" in css


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


def test_past_tab_promotes_weekend_analysis_only_on_et_weekends(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'id="past-weekday-card"' in html and 'id="past-weekend-card"' in html
    assert 'weekday: "short", timeZone: "America/New_York"' in html
    assert 'panel.prepend(isEtWeekend() ? weekendCard : weekdayCard)' in html


def test_global_live_summary_shows_every_live_game_and_each_bet_status(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'id="live-summary" aria-label="Tóm tắt các kèo đang live"' in html
    assert 'const live = rows.filter((r) => r.state === "live")' in html
    assert 'class: `live-summary-game ${tone}`' in html
    assert 'class: `live-summary-bet ${p.now || "push"}`' in html
    assert 'renderLiveSummary(allRows)' in html
    assert 'renderLiveSummary(liveInPlayRows())' in html
    assert 'if (preserveViewport && Math.abs(heightDelta) > 0.5)' in html


def test_site_version_changes_with_the_template_or_a_static_file():
    from actions_tracker.build_site import site_version
    base = site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"2")])
    assert base == site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"2")])
    assert len(base) == 10
    assert site_version("<html>B</html>", [("a.js", b"1"), ("b.css", b"2")]) != base   # a design change in the page itself
    assert site_version("<html>A</html>", [("a.js", b"1"), ("b.css", b"3")]) != base   # a change in a static file


def test_rebuild_removes_static_files_that_were_deleted_from_the_code(tmp_path):
    # the phone keeps one site/ folder and publishes everything in it: a removed asset (ask.js) must not linger
    site = tmp_path / "site"
    site.mkdir()
    for name in ("ask.js", "anthropic-sdk.js", "anthropic-sdk.LICENSE.txt", "old.css"):
        (site / name).write_text("stale", "utf-8")
    (site / "actions_report.xlsx").write_bytes(b"xlsx from an earlier full run")
    (site / "CNAME").write_text("example.org", "utf-8")
    build_site({}, [], site, None, "t")
    names = {p.name for p in site.iterdir()}
    assert not names & {"ask.js", "anthropic-sdk.js", "anthropic-sdk.LICENSE.txt", "old.css"}
    assert {"index.html", "scoreboard.js", "second-half.js", "dashboard.css", "actions_report.xlsx", "CNAME"} <= names


def test_every_colour_the_charts_read_is_defined(tmp_path):
    # css("--bad") was undefined, so Chart.js drew the 2H "Thua" bars black
    import re
    from importlib import resources
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    styles = html + resources.files("actions_tracker").joinpath("templates/static/dashboard.css").read_text("utf-8")
    used = set(re.findall(r'css\("(--[\w-]+)"\)', html))
    defined = set(re.findall(r"(--[\w-]+)\s*:", styles))
    assert used and not used - defined, sorted(used - defined)


def test_playoff_and_traffic_sit_before_soccer_and_soccer_ships_its_helpers(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    assert (html.index('data-tab="past"') < html.index('data-tab="playoff"')
            < html.index('data-tab="traffic"') < html.index('data-tab="soccer"')
            < html.index('data-tab="season-chart"'))
    assert 'id="tab-soccer"' in html and 'T("Soccer_Board")' in html and "soccer.js?v=" in html
    assert 'id="soccer-daily"' in html and 'T("Soccer_Results")' in html and 'T("Soccer_Daily")' in html
    assert (tmp_path / "site" / "soccer.js").exists()


def test_expert_comment_urls_are_safe_clickable_links(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert "function linkifiedText(value)" in html
    assert '["https:", "http:"].includes(url.protocol)' in html
    assert 'target: "_blank", rel: "noopener noreferrer"' in html
    assert "linkifiedText(x.expert_note)" in html


def test_holiday_logo_switches_on_eastern_dates_and_respects_reduced_motion(tmp_path):
    out = build_site({}, [], tmp_path / "site", None, "t")
    html = out.read_text("utf-8")
    css = (out.parent / "dashboard.css").read_text("utf-8")
    assert 'timeZone: "America/New_York"' in html
    assert 'fields.day === thanksgiving + 1' in html and 'return "season-black-friday"' in html
    assert 'return "season-christmas"' in html and "setInterval(applyHoliday, 5000)" in html
    assert 'class="black-friday-mark"' in html and 'class="christmas-lap"' in html
    assert "animation: christmas-screen-lap 20s linear infinite" in css
    assert ".season-christmas .christmas-lap { display: none; animation: none; }" in css


def test_city_analytics_never_publishes_raw_ip_and_tracks_distinct_periods(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'fetch("https://ipwho.is/"' in html
    assert "geo.ip" not in html and "geo-city-" in html
    assert "unique-visitor-${day}" in html and "active-hour-${key}" in html
    assert "Analytics không cookie · chỉ lưu city gần đúng · không lưu IP" in html
    assert 'id="traffic-daily"' in html and 'id="traffic-weekly"' in html and 'id="traffic-monthly"' in html


def test_expert_form_leads_with_plain_language_summary(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert "Phong độ expert có giúp pick kế tiếp thắng không?" in html
    assert 'id="form-summary"' in html
    assert "Mốc cần vượt là 52,4% để hòa vốn" in html
    assert "Tín hiệu lịch sử rõ" in html and "Có lợi, nhưng chưa chắc" in html
    assert "Xem biểu đồ và số liệu chi tiết" in html


def test_consensus_leads_with_plain_language_actions(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'data-tab="consensus" aria-selected="false">Đám đông<' in html
    assert "Đám đông có đáng theo không?" in html
    assert 'id="consensus-verdict"' in html and 'id="consensus-guide"' in html
    assert "THEO BÊN ĐÔNG" in html and "ĐÁNH NGƯỢC" in html and "TRÁNH" in html
    assert "Xem số liệu chi tiết" in html


def test_refresh_restores_the_active_tab_and_live_mode(tmp_path):
    html = build_site({}, [], tmp_path / "site", None, "t").read_text("utf-8")
    assert 'localStorage.setItem("actions-active-tab", tab)' in html
    assert 'localStorage.getItem("actions-active-tab")' in html
    assert 'localStorage.setItem("actions-nav-mode", mode)' in html
    assert 'mode === "inplay" ? "upcoming" : tab' in html
    assert "mobileNav(); restoreNavigation();" in html
