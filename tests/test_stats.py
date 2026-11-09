import math

from actions_tracker.analysis.stats import american_profit, summarize, wilson_ci


def test_american_profit():
    assert american_profit(-110) == 100 / 110
    assert american_profit(150) == 1.5
    assert american_profit(None) == 100 / 110
    assert american_profit(0) == 100 / 110


def test_wilson_ci_known_value():
    lo, hi = wilson_ci(55, 100)
    assert round(lo, 4) == 0.4524 and round(hi, 4) == 0.6439


def test_wilson_ci_empty():
    assert all(math.isnan(x) for x in wilson_ci(0, 0))


def test_summarize_mixed():
    s = summarize(["win", "loss", "push", "win", "pending"], [-110, -110, -110, 200, -110])
    assert (s["n"], s["wins"], s["losses"], s["pushes"]) == (3, 2, 1, 1)
    assert s["win_pct"] == 2 / 3
    assert math.isclose(s["units"], 100 / 110 + 2.0 - 1)
    assert math.isclose(s["roi"], s["units"] / 3)
    assert s["low_sample"] is True


def test_summarize_empty():
    s = summarize([], [])
    assert s["n"] == 0 and math.isnan(s["win_pct"]) and s["units"] == 0
