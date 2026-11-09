"""Weekly win-rate trend for expert consensus and the top-10 experts."""

import pandas as pd

from actions_tracker.analysis.stats import summarize
from actions_tracker.config import TZ

TREND_COLS = ["week_start", "series", "n", "wins", "win_pct"]


def week_start(start_times: pd.Series) -> pd.Series:
    """Monday (America/New_York) of the week each kickoff falls in, as YYYY-MM-DD."""
    local = pd.to_datetime(start_times, utc=True, errors="coerce").dt.tz_convert(TZ)
    monday = local.dt.normalize() - pd.to_timedelta(local.dt.day_of_week, unit="D")
    return monday.dt.strftime("%Y-%m-%d")


def _series(name: str, df: pd.DataFrame, result_col: str) -> list[dict]:
    df = df[df[result_col].notna()]
    if df.empty:
        return []
    rows = []
    for week, g in df.assign(week_start=week_start(df["start_time"])).groupby("week_start", sort=True):
        s = summarize(list(g[result_col]), [None] * len(g))
        rows.append({"week_start": week, "series": name, "n": s["n"], "wins": s["wins"], "win_pct": s["win_pct"]})
    return rows


def weekly_trend(cg: pd.DataFrame, picks: pd.DataFrame, lb: pd.DataFrame) -> pd.DataFrame:
    top10 = set(lb.loc[pd.to_numeric(lb["rank"]) <= 10, "expert_id"]) if not lb.empty else set()
    rows = (
        _series("consensus_60plus", cg[cg["bucket"] != "50-60"], "side_result")
        + _series("top10_experts", picks[picks["expert_id"].isin(top10)], "expert_result")
    )
    return pd.DataFrame(rows, columns=TREND_COLS)
