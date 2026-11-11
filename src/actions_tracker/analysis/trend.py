"""Weekly win-rate trend for expert consensus and the top-10 experts.

The top 10 of each week is ranked only on picks that kicked off before that week (no look-ahead):
an expert needs MIN_SAMPLE graded picks by then, ranked by ROI."""

import pandas as pd

from actions_tracker.analysis.stats import summarize
from actions_tracker.config import MIN_SAMPLE, TZ

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


def _rolling_top10(picks: pd.DataFrame) -> pd.DataFrame:
    graded = picks[picks["expert_result"].isin(["win", "loss", "push"])]
    if graded.empty:
        return graded
    graded = graded.assign(week_start=week_start(graded["start_time"]))
    keep = []
    for week in sorted(graded["week_start"].dropna().unique()):
        before = graded[graded["week_start"] < week]
        ranked = []
        for expert_id, g in before.groupby("expert_id"):
            s = summarize(list(g["expert_result"]), list(g["odds"]))
            if s["n"] >= MIN_SAMPLE:
                ranked.append((s["roi"], expert_id))
        top = {e for _, e in sorted(ranked, key=lambda t: -t[0])[:10]}
        keep.append(graded[(graded["week_start"] == week) & graded["expert_id"].isin(top)])
    return pd.concat(keep) if keep else graded.iloc[0:0]


def weekly_trend(cg: pd.DataFrame, picks: pd.DataFrame) -> pd.DataFrame:
    rows = (
        _series("consensus_60plus", cg[cg["bucket"] != "50-60"], "side_result")
        + _series("top10_experts", _rolling_top10(picks), "expert_result")
    )
    return pd.DataFrame(rows, columns=TREND_COLS)
