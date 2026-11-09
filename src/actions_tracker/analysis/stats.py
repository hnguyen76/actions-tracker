"""Win %, ROI and confidence intervals shared by every analysis table."""

import math
from collections.abc import Sequence

from actions_tracker.config import DEFAULT_ODDS, MIN_SAMPLE


def american_profit(odds: int | None) -> float:
    """Profit of a 1-unit winning bet at American odds; missing odds count as -110."""
    if odds is None or odds == 0 or (isinstance(odds, float) and math.isnan(odds)):
        odds = DEFAULT_ODDS
    return odds / 100 if odds > 0 else 100 / abs(odds)


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def summarize(results: Sequence[str], odds: Sequence[int | None]) -> dict:
    wins = losses = pushes = 0
    units = 0.0
    for result, o in zip(results, odds):
        if result == "win":
            wins += 1
            units += american_profit(o)
        elif result == "loss":
            losses += 1
            units -= 1
        elif result == "push":
            pushes += 1
    n = wins + losses
    lo, hi = wilson_ci(wins, n)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_pct": wins / n if n else math.nan,
        "ci_low": lo,
        "ci_high": hi,
        "units": units,
        "roi": units / n if n else math.nan,
        "low_sample": n < MIN_SAMPLE,
    }
