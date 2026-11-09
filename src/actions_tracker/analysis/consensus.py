"""A. Expert consensus: when most experts take one side, how does that side do? (spec §7A)"""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import BUCKETS, MIN_EXPERTS

CG_COLS = ["game_id", "league", "market", "start_time", "status", "home_abbr", "away_abbr", "side", "votes",
           "total_votes", "majority_pct", "bucket", "side_result", "side_odds", "opp_odds", "tickets_pct",
           "money_pct"]
SUMMARY_COLS = ["league", "market", "bucket"] + SUMMARY_KEYS + ["fade_win_pct", "fade_roi"]
UPCOMING_COLS = CG_COLS + ["hist_win_pct", "hist_n"]
_FLIP = {"win": "loss", "loss": "win", "push": "push"}


def bucket_of(pct: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= pct < hi:
            return name
    return BUCKETS[-1][2]


def consensus_games(picks: pd.DataFrame) -> pd.DataFrame:
    if picks.empty:
        return pd.DataFrame(columns=CG_COLS)
    latest = (picks.sort_values("created_at", kind="stable")
              .drop_duplicates(["game_id", "market", "expert_id"], keep="last"))
    rows = []
    for (game_id, market), g in latest.groupby(["game_id", "market"], sort=True):
        counts = g["pick_side"].value_counts()
        total = int(counts.sum())
        if total < MIN_EXPERTS or (len(counts) > 1 and counts.iloc[0] == counts.iloc[1]):
            continue
        side = counts.index[0]
        rep = g[g["pick_side"] == side].iloc[-1]
        pct = 100.0 * counts.iloc[0] / total
        rows.append({
            "game_id": game_id, "league": rep["league"], "market": market, "start_time": rep["start_time"],
            "status": rep["status"], "home_abbr": rep["home_abbr"], "away_abbr": rep["away_abbr"],
            "side": side, "votes": int(counts.iloc[0]), "total_votes": total, "majority_pct": pct,
            "bucket": bucket_of(pct), "side_result": rep["side_result"], "side_odds": rep["close_odds"],
            "opp_odds": rep["opp_close_odds"], "tickets_pct": rep["tickets_pct"], "money_pct": rep["money_pct"],
        })
    return pd.DataFrame(rows, columns=CG_COLS).astype(object)


def consensus_summary(cg: pd.DataFrame) -> pd.DataFrame:
    graded = cg[cg["side_result"].notna()]
    if graded.empty:
        return pd.DataFrame(columns=SUMMARY_COLS)
    rows = []
    for (league, market, bucket), g in with_all(graded, ["league", "market"]).groupby(
            ["league", "market", "bucket"], sort=True):
        follow = summarize(list(g["side_result"]), list(g["side_odds"]))
        fade = summarize([_FLIP.get(r, r) for r in g["side_result"]], list(g["opp_odds"]))
        rows.append({"league": league, "market": market, "bucket": bucket, **follow,
                     "fade_win_pct": fade["win_pct"], "fade_roi": fade["roi"]})
    return pd.DataFrame(rows, columns=SUMMARY_COLS)


def upcoming(cg: pd.DataFrame, summary: pd.DataFrame, now: str) -> pd.DataFrame:
    if cg.empty:
        return pd.DataFrame(columns=UPCOMING_COLS)
    up = cg[(cg["status"] != "complete") & (cg["start_time"].astype(str) > now)].copy()
    hist = summary[["league", "market", "bucket", "win_pct", "n"]].rename(
        columns={"win_pct": "hist_win_pct", "n": "hist_n"})
    up = up.merge(hist, on=["league", "market", "bucket"], how="left")
    return up.sort_values("start_time", kind="stable").reset_index(drop=True)[UPCOMING_COLS]
