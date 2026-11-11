"""Expert form at pick time: parsed from the picks pages, stored once before kickoff, analysed by bucket."""

import pathlib

import pandas as pd
import pytest

from actions_tracker import db
from actions_tracker.analysis.form import FORM_COLS, NOW_COLS, expert_form, expert_form_now
from actions_tracker.parse import extract_next_data, parse_bygame_page, parse_picks_page
from tests.helpers import make_picks

F = pathlib.Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("league", ["nfl", "ncaaf", "nba"])
def test_picks_page_form_matches_profile(league):
    html = (F / f"{league}_picks.html").read_text("utf-8")
    profiles = extract_next_data(html)["props"]["pageProps"]["initialExpertsResponse"]["response"]["profiles"]
    by_id = {p["id"]: p for p in profiles}
    page = parse_picks_page(html, league)
    assert {f["pick_id"] for f in page.forms} == {p["id"] for p in page.picks}
    f = page.forms[0]
    pr = by_id[f["expert_id"]]
    assert f["league"] == league
    assert f["units_30"] == pytest.approx(pr["record"]["units_net"])
    assert (f["wins_30"], f["losses_30"]) == (pr["record"]["win"], pr["record"]["loss"])
    assert (f["streak_type"], f["streak_value"]) == (pr["win_streak"]["type"], pr["win_streak"]["value"])


def test_bygame_page_has_forms():
    page = parse_bygame_page((F / "nfl_bygame.html").read_text("utf-8"), "nfl")
    assert {f["pick_id"] for f in page.forms} == {p["id"] for p in page.picks}
    assert any(f["units_30"] is not None for f in page.forms)


def test_missing_form_fields_are_none():
    page = parse_picks_page((F / "mini_picks.html").read_text("utf-8"), "nfl")
    assert page.forms and all(f["units_30"] is None and f["streak_type"] is None for f in page.forms)


G = dict(id=100, league="nfl", start_time="2026-11-10T01:00:00.000Z")
FORM = dict(pick_id=11, expert_id=1, league="nfl", streak_type="hot", streak_value=3, units_30=5.0,
            wins_30=10, losses_30=6, pushes_30=0)


def test_form_stored_once_and_only_before_kickoff(tmp_path):
    c = db.connect(tmp_path / "a.db")
    db.upsert_games(c, [G], "t")
    db.upsert_picks(c, [dict(id=11, expert_id=1, game_id=100), dict(id=12, expert_id=1, game_id=100)], "t")
    db.insert_pick_forms(c, [FORM], "2026-11-09T20:00:00.000Z")
    db.insert_pick_forms(c, [FORM | {"units_30": 9.0}], "2026-11-09T22:00:00.000Z")  # first sighting wins
    db.insert_pick_forms(c, [FORM | {"pick_id": 12}], "2026-11-10T02:00:00.000Z")  # after kickoff: skipped
    db.insert_pick_forms(c, [FORM | {"pick_id": 99}], "2026-11-09T20:00:00.000Z")  # unknown pick: skipped
    rows = [tuple(r) for r in c.execute("select pick_id, units_30, captured_at from pick_form")]
    assert rows == [(11, 5.0, "2026-11-09T20:00:00.000Z")]


def _picks(rows):
    return make_picks([dict(pick_id=i, expert_id=1, game_id=i, market="spread", pick_side="home", **r)
                       for i, r in enumerate(rows)])


def _forms(units, streaks):
    return pd.DataFrame([dict(pick_id=i, expert_id=1, league="nfl", captured_at="2026-11-01T00:00:00.000Z",
                              units_30=u, streak_type=s[0], streak_value=s[1], wins_30=1, losses_30=1, pushes_30=0)
                         for i, (u, s) in enumerate(zip(units, streaks))])


def test_form_buckets_and_day_groups():
    sat, mon = "2026-11-07T20:00:00.000Z", "2026-11-10T01:00:00.000Z"  # Sat 15:00 ET, Mon 20:00 ET
    picks = _picks([dict(expert_result="win", start_time=sat), dict(expert_result="loss", start_time=sat),
                    dict(expert_result="loss", start_time=mon), dict(expert_result="win", start_time=mon),
                    dict(expert_result=None, start_time=mon)])
    forms = _forms([8.0, 4.0, -6.0, 0.5, 9.0], [("hot", 4), ("hot", 1), ("cold", 3), ("cold", 1), ("hot", 5)])
    t = expert_form(picks, forms).set_index(["league", "market", "day_group", "dim", "bucket"])
    hot = t.loc[("ALL", "ALL", "ALL", "units_30", "hot")]
    assert (hot.n, hot.wins) == (2, 1)  # +8u win, +4u loss; the ungraded +9u pick is ignored
    assert t.loc[("ALL", "ALL", "ALL", "units_30", "cold")].losses == 1
    assert t.loc[("ALL", "ALL", "ALL", "units_30", "neutral")].wins == 1
    assert t.loc[("nfl", "spread", "T7-CN", "units_30", "hot")].n == 2
    assert t.loc[("ALL", "ALL", "T2-6", "streak", "cold_long")].losses == 1
    assert t.loc[("ALL", "ALL", "T7-CN", "streak", "hot_long")].wins == 1
    assert list(expert_form(picks, forms).columns) == FORM_COLS


def test_form_now_latest_per_expert_league():
    forms = _forms([1.0, 2.0], [("hot", 1), ("hot", 2)])
    forms.loc[1, "captured_at"] = "2026-11-02T00:00:00.000Z"
    now = expert_form_now(forms)
    assert list(now.columns) == NOW_COLS and len(now) == 1 and now.iloc[0].units_30 == 2.0


def test_form_empty():
    assert expert_form(make_picks([]), pd.DataFrame()).empty
    assert expert_form_now(pd.DataFrame()).empty
