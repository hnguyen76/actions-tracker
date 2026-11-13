"""A. Expert consensus: when most experts take one side, how does that side do? (spec §7A)"""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import BUCKETS, MIN_EXPERTS, TZ

CG_COLS = ["game_id", "league", "market", "start_time", "status", "home_abbr", "away_abbr", "side", "votes",
           "total_votes", "majority_pct", "bucket", "side_result", "side_odds", "opp_odds", "line_source"]
SUMMARY_COLS = ["league", "market", "bucket"] + SUMMARY_KEYS + ["fade_win_pct", "fade_roi"]
UPCOMING_COLS = CG_COLS + ["hist_win_pct", "hist_n"]
_FLIP = {"win": "loss", "loss": "win", "push": "push"}


def pregame_picks(picks: pd.DataFrame) -> pd.DataFrame:
    """Only information available by kickoff may contribute to a pregame consensus.

    Missing timestamps are retained so old imports remain usable; explicitly late picks are excluded.
    """
    if picks.empty or "created_at" not in picks or "start_time" not in picks:
        return picks
    created = pd.to_datetime(picks["created_at"], utc=True, errors="coerce")
    starts = pd.to_datetime(picks["start_time"], utc=True, errors="coerce")
    return picks[created.isna() | starts.isna() | (created <= starts)].copy()


def bucket_of(pct: float) -> str:
    for lo, hi, name in BUCKETS:
        if lo <= pct < hi:
            return name
    return BUCKETS[-1][2]


def consensus_games(picks: pd.DataFrame) -> pd.DataFrame:
    if picks.empty:
        return pd.DataFrame(columns=CG_COLS)
    picks = pregame_picks(picks)
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
            "opp_odds": rep["opp_close_odds"], "line_source": rep["line_source"],
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


BOARD_COLS = ["game_id", "league", "market", "start_time", "away_abbr", "home_abbr", "a_side", "a_votes", "a_line",
              "b_side", "b_votes", "b_line", "total_votes", "status"]
_PAIR = {"total": ("over", "under")}


def upcoming_board(picks: pd.DataFrame, now: str) -> pd.DataFrame:
    """Every upcoming game x market that has picks, including 50/50 splits and markets with fewer than
    MIN_EXPERTS experts, so no game silently disappears from the dashboard.
    status: "majority" (a consensus play), "split" (tie) or "few" (under MIN_EXPERTS experts)."""
    if picks.empty:
        return pd.DataFrame(columns=BOARD_COLS)
    picks = pregame_picks(picks)
    up = picks[(picks["status"] != "complete") & (picks["start_time"].astype(str) > now)]
    if up.empty:
        return pd.DataFrame(columns=BOARD_COLS)
    latest = up.sort_values("created_at", kind="stable").drop_duplicates(["game_id", "market", "expert_id"], keep="last")
    rows = []
    for (game_id, market), g in latest.groupby(["game_id", "market"], sort=True):
        a, b = _PAIR.get(market, ("away", "home"))
        rep = g.iloc[-1]
        side_rows = {s: g[g["pick_side"] == s] for s in (a, b)}
        line = {s: (pd.to_numeric(r["line"], errors="coerce").median() if len(r) else None) for s, r in side_rows.items()}
        va, vb = len(side_rows[a]), len(side_rows[b])
        total = va + vb
        status = "few" if total < MIN_EXPERTS else "split" if va == vb else "majority"
        rows.append({"game_id": game_id, "league": rep["league"], "market": market, "start_time": rep["start_time"],
                     "away_abbr": rep["away_abbr"], "home_abbr": rep["home_abbr"],
                     "a_side": a, "a_votes": va, "a_line": None if pd.isna(line[a]) else float(line[a]),
                     "b_side": b, "b_votes": vb, "b_line": None if pd.isna(line[b]) else float(line[b]),
                     "total_votes": total, "status": status})
    out = pd.DataFrame(rows, columns=BOARD_COLS)
    return out.sort_values(["start_time", "game_id", "market"], kind="stable").reset_index(drop=True)


PAST_COLS = ["game_id", "league", "market", "start_time", "et_date", "day_group", "match", "pick", "votes",
             "total_votes", "majority_pct", "bucket", "side_result", "side_odds", "opp_odds",
             "source", "count_basis", "line_source"]


def past_plays(cg: pd.DataFrame) -> pd.DataFrame:
    """Graded consensus plays, newest first, tagged Mon-Fri ("T2-6") or Sat-Sun ("T7-CN") by US/Eastern date."""
    done = cg[cg["side_result"].notna() & (cg["status"] == "complete")].copy()
    if done.empty:
        return pd.DataFrame(columns=PAST_COLS)
    local = pd.to_datetime(done["start_time"], utc=True, errors="coerce").dt.tz_convert(TZ)
    done["et_date"] = local.dt.strftime("%Y-%m-%d")
    done["day_group"] = ["T2-6" if d <= 4 else "T7-CN" for d in local.dt.day_of_week]
    done["source"] = "live"  # picks collected by the button (Action Network) + The Odds API scores/lines
    done["count_basis"] = "distinct_expert"  # each expert counted once per game x market (latest pick)
    done["match"] = done["away_abbr"].astype(str) + "@" + done["home_abbr"].astype(str)
    done["pick"] = [r.home_abbr if r.side == "home" else r.away_abbr if r.side == "away" else str(r.side).title()
                    for r in done.itertuples()]
    done = done.sort_values(["start_time", "majority_pct"], ascending=[False, False], kind="stable")
    return done.reset_index(drop=True)[PAST_COLS]

