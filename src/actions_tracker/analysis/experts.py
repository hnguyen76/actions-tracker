"""B. Per-expert record, side-picking habits and leaderboard (spec §7B)."""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import MIN_SAMPLE

ID_COLS = ["expert_id", "expert_name"]
SUMMARY_COLS = ID_COLS + ["league", "market", "window"] + SUMMARY_KEYS
HABIT_COLS = ID_COLS + ["league", "label_type", "label", "share"] + SUMMARY_KEYS
LEADERBOARD_COLS = ["rank"] + SUMMARY_COLS
LABEL_TYPES = ["fav_dog", "home_away", "over_under"]
_GRADED = {"win", "loss", "push"}


def _ts(s) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def expert_summary(picks: pd.DataFrame, now: str) -> pd.DataFrame:
    if picks.empty:
        return pd.DataFrame(columns=SUMMARY_COLS)
    cutoff = pd.Timestamp(now) - pd.Timedelta(days=30)
    rows = []
    for key, g in with_all(picks, ["league", "market"]).groupby(ID_COLS + ["league", "market"], sort=True):
        g = g.assign(_start=_ts(g["start_time"])).sort_values("_start", kind="stable")
        graded = g[g["expert_result"].isin(_GRADED)]
        windows = {
            "all": g,
            "last_30_days": g[g["_start"] >= cutoff],
            "last_30_picks": graded.tail(30),
        }
        for window, w in windows.items():
            stats = summarize(list(w["expert_result"]), list(w["odds"]))
            rows.append(dict(zip(ID_COLS + ["league", "market"], key)) | {"window": window} | stats)
    return pd.DataFrame(rows, columns=SUMMARY_COLS)


def expert_habits(picks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label_type in LABEL_TYPES:
        labelled = picks[picks[label_type].notna()]
        if labelled.empty:
            continue
        for key, g in with_all(labelled, ["league"]).groupby(ID_COLS + ["league"], sort=True):
            total = len(g)
            for label, lg in g.groupby(label_type, sort=True):
                stats = summarize(list(lg["expert_result"]), list(lg["odds"]))
                rows.append(dict(zip(ID_COLS + ["league"], key))
                            | {"label_type": label_type, "label": label, "share": len(lg) / total} | stats)
    return pd.DataFrame(rows, columns=HABIT_COLS)


def leaderboard(summary: pd.DataFrame) -> pd.DataFrame:
    lb = summary[(summary["window"] == "all") & (summary["league"] == "ALL") & (summary["market"] == "ALL")
                 & (summary["n"].astype(float) >= MIN_SAMPLE)]
    lb = lb.sort_values("roi", ascending=False, kind="stable").reset_index(drop=True)
    lb.insert(0, "rank", range(1, len(lb) + 1))
    return lb[LEADERBOARD_COLS]
