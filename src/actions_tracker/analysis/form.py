"""Does an expert's form when a pick is made (hot or cold) say anything about that pick's result?

Form is Action Network's own view of the expert at the time the pick was first seen, before kickoff:
units won in the league over the last 30 days and the current win/loss streak.
"""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import FORM_STREAK_LONG, FORM_UNITS, TZ

GROUP_COLS = ["league", "market", "day_group"]
FORM_COLS = GROUP_COLS + ["dim", "bucket"] + SUMMARY_KEYS
NOW_COLS = ["expert_id", "league", "captured_at", "streak_type", "streak_value", "units_30", "wins_30", "losses_30",
            "pushes_30"]
UNITS_ORDER = ["hot", "neutral", "cold"]
STREAK_ORDER = ["hot_long", "hot", "cold", "cold_long"]
_GRADED = {"win", "loss", "push"}


def _units_bucket(u) -> str | None:
    if u is None or pd.isna(u):
        return None
    return "hot" if u >= FORM_UNITS else "cold" if u <= -FORM_UNITS else "neutral"


def _streak_bucket(kind, value) -> str | None:
    if kind not in ("hot", "cold") or value is None or pd.isna(value):
        return None
    return f"{kind}_long" if value >= FORM_STREAK_LONG else kind


def expert_form(picks: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    if picks.empty or forms.empty:
        return pd.DataFrame(columns=FORM_COLS)
    graded = picks[picks["expert_result"].isin(_GRADED)]
    df = graded.merge(forms[["pick_id", "units_30", "streak_type", "streak_value"]], on="pick_id", how="inner")
    if df.empty:
        return pd.DataFrame(columns=FORM_COLS)
    local = pd.to_datetime(df["start_time"], utc=True, errors="coerce").dt.tz_convert(TZ)
    df["day_group"] = ["T2-6" if d <= 4 else "T7-CN" for d in local.dt.day_of_week]
    df["units_b"] = [_units_bucket(u) for u in df["units_30"]]
    df["streak_b"] = [_streak_bucket(k, v) for k, v in zip(df["streak_type"], df["streak_value"])]
    rows = []
    stacked = with_all(df, GROUP_COLS)
    for dim, col, order in (("units_30", "units_b", UNITS_ORDER), ("streak", "streak_b", STREAK_ORDER)):
        part = stacked[stacked[col].notna()]
        for key, g in part.groupby(GROUP_COLS, sort=True):
            for bucket in order:
                b = g[g[col] == bucket]
                if b.empty:
                    continue
                rows.append(dict(zip(GROUP_COLS, key)) | {"dim": dim, "bucket": bucket}
                            | summarize(list(b["expert_result"]), list(b["odds"])))
    return pd.DataFrame(rows, columns=FORM_COLS)


def expert_form_now(forms: pd.DataFrame) -> pd.DataFrame:
    """Latest form seen for each expert in each league (for the Experts tab)."""
    if forms.empty:
        return pd.DataFrame(columns=NOW_COLS)
    latest = forms.sort_values("captured_at", kind="stable").groupby(["expert_id", "league"], sort=True).tail(1)
    return latest[NOW_COLS].reset_index(drop=True)
