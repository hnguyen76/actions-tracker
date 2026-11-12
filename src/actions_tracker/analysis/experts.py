"""B. Per-expert record, side-picking habits and leaderboard (spec §7B)."""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import MIN_SAMPLE

ID_COLS = ["expert_id", "expert_name"]
SUMMARY_COLS = ID_COLS + ["league", "market", "window"] + SUMMARY_KEYS
HABIT_COLS = ID_COLS + ["league", "label_type", "label", "share"] + SUMMARY_KEYS
LEADERBOARD_COLS = ["rank"] + SUMMARY_COLS
CLV_COLS = ID_COLS + ["league", "market", "n", "avg_clv", "beat", "same", "worse", "beat_pct"]
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


def _clv(market: str, side: str, line: float, close: float) -> float:
    """Points of line value the expert got versus the closing line on the same side (positive = better)."""
    if market == "total":
        return close - line if side == "over" else line - close
    return line - close  # spread: a bigger number is always better for the side that takes it


def expert_clv(picks: pd.DataFrame, now: str) -> pd.DataFrame:
    """Closing line value per expert: spread/total picks of games that have started and have a closing line."""
    if picks.empty:
        return pd.DataFrame(columns=CLV_COLS)
    started = _ts(picks["start_time"]) <= pd.Timestamp(now)
    line, close = pd.to_numeric(picks["line"], errors="coerce"), pd.to_numeric(picks["close_line"], errors="coerce")
    df = picks[started & picks["market"].isin(["spread", "total"]) & line.notna() & close.notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=CLV_COLS)
    df["clv"] = [_clv(m, sd, float(a), float(b)) for m, sd, a, b in zip(df["market"], df["pick_side"], df["line"], df["close_line"])]
    rows = []
    for key, g in with_all(df, ["league", "market"]).groupby(ID_COLS + ["league", "market"], sort=True):
        n = len(g)
        beat, same = int((g["clv"] > 0).sum()), int((g["clv"] == 0).sum())
        rows.append(dict(zip(ID_COLS + ["league", "market"], key)) | {
            "n": n, "avg_clv": float(g["clv"].mean()), "beat": beat, "same": same, "worse": n - beat - same,
            "beat_pct": beat / n})
    return pd.DataFrame(rows, columns=CLV_COLS)
