"""Started-but-ungraded plays with the live score and whether each pick covers right now."""

import pandas as pd

from actions_tracker.analysis.in_play import IN_PLAY_COLS, in_play


def test_in_play_lists_live_and_ungraded_finals_with_cover_status():
    scores = pd.DataFrame([
        dict(game_id=1, away_score=7, home_score=7, state="live", detail="5:11 - 1st", graded=False),
        dict(game_id=2, away_score=13, home_score=27, state="final", detail="Final", graded=False),
        dict(game_id=3, away_score=49, home_score=7, state="final", detail="Hết trận", graded=True),  # graded -> out
    ])
    mm = pd.DataFrame([
        dict(game_id=1, league="ncaaf", start_time="t1", match="TEX@LSU", status="pending", pick="TEX", line=5.0,
             bet_side="away", crowd="LSU", votes=8, total_votes=10),
        dict(game_id=3, league="ncaaf", start_time="t0", match="WF@SMU", status="pending", pick="WF", line=1.0,
             bet_side="away", crowd="SMU", votes=10, total_votes=10),
    ])
    rp = pd.DataFrame([
        dict(game_id=2, league="ncaaf", start_time="t2", match="USC@IU", status="pending", rule_name="R", market="total",
             pick="Under", line=50.5, bet_side="under"),
        dict(game_id=2, league="ncaaf", start_time="t2", match="USC@IU", status="pending", rule_name="R4",
             market="spread", pick="IU", line=-9.5, bet_side="home"),
    ])
    out = in_play(scores, mm, rp)
    assert list(out.columns) == IN_PLAY_COLS and set(out.game_id) == {1, 2}
    by = {(r.game_id, r.market): r for r in out.itertuples()}
    assert (by[(1, "spread")].now, by[(1, "spread")].crowd) == ("win", "LSU 8/10")      # TEX +5 at 7-7
    assert by[(2, "total")].now == "win" and by[(2, "spread")].now == "win"           # 40 < 50.5; IU by 14 > 9.5
    assert out.iloc[0].state == "live"                                                  # live games first
