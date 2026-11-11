"""Season history (weeks 1..N) from data/history/<league>_sides.csv, kept apart from the live consensus.

The two are different statistics and must never be merged:
- live (Past_Plays): each expert counted once per game x market, graded at The Odds API closing line;
- history (this module): raw pick counts from the By-Game week cards (one expert can count more than once),
  graded at Action Network's scoreboard closing line — a one-off historical exception to the data-source plan.
"""

from pathlib import Path

import pandas as pd

from actions_tracker.analysis.consensus import bucket_of
from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import MIN_EXPERTS

SOURCE = "history_bygame_cards"
COUNT_BASIS = "pick_count"
LINE_SOURCE = "action_network_scoreboard"
PLAY_COLS = ["league", "week", "game_id", "et_date", "day_group", "match", "market", "side", "pick", "line",
             "votes", "total_votes", "majority_pct", "bucket", "side_result", "side_odds", "opp_odds",
             "tickets_pct", "money_pct", "source", "count_basis", "line_source"]
GROUP_COLS = ["league", "day_group", "market", "bucket"]
SUMMARY_COLS = GROUP_COLS + SUMMARY_KEYS + ["fade_win_pct", "fade_roi"]
WEEKLY_COLS = ["league", "week", "day_group"] + SUMMARY_KEYS
_FLIP = {"win": "loss", "loss": "win", "push": "push"}


def load_history(history_dir: Path | None) -> pd.DataFrame:
    if history_dir is None or not Path(history_dir).is_dir():
        return pd.DataFrame()
    parts = [pd.read_csv(f) for f in sorted(Path(history_dir).glob("*_sides.csv"))]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def history_plays(sides: pd.DataFrame) -> pd.DataFrame:
    """Majority side of every game x market with at least MIN_EXPERTS picks and no tie."""
    if sides.empty:
        return pd.DataFrame(columns=PLAY_COLS)
    df = sides[(sides["picks"] + sides["opp_picks"] >= MIN_EXPERTS) & (sides["picks"] > sides["opp_picks"])
               & sides["result"].notna()].copy()
    if df.empty:
        return pd.DataFrame(columns=PLAY_COLS)
    df["votes"] = df["picks"].astype(int)
    df["total_votes"] = (df["picks"] + df["opp_picks"]).astype(int)
    df["majority_pct"] = 100.0 * df["votes"] / df["total_votes"]
    df["bucket"] = [bucket_of(p) for p in df["majority_pct"]]
    df["match"] = df["away"].astype(str) + "@" + df["home"].astype(str)
    df["pick"] = [r.home if r.side == "home" else r.away if r.side == "away" else str(r.side).title()
                  for r in df.itertuples()]
    df["side_result"] = df["result"]
    df["side_odds"] = df["odds"]
    df["source"], df["count_basis"], df["line_source"] = SOURCE, COUNT_BASIS, LINE_SOURCE
    df = df.sort_values(["et_date", "league", "match", "market"], ascending=[False, True, True, True], kind="stable")
    return df.reset_index(drop=True)[PLAY_COLS]


def history_summary(plays: pd.DataFrame) -> pd.DataFrame:
    if plays.empty:
        return pd.DataFrame(columns=SUMMARY_COLS)
    rows = []
    for key, g in with_all(plays, GROUP_COLS).groupby(GROUP_COLS, sort=True):
        follow = summarize(list(g["side_result"]), list(g["side_odds"]))
        fade = summarize([_FLIP.get(r, r) for r in g["side_result"]], list(g["opp_odds"]))
        rows.append(dict(zip(GROUP_COLS, key)) | follow | {"fade_win_pct": fade["win_pct"], "fade_roi": fade["roi"]})
    return pd.DataFrame(rows, columns=SUMMARY_COLS)


def history_weekly(plays: pd.DataFrame) -> pd.DataFrame:
    """Follow-the-majority record per league x week (NFL and NCAAF number their weeks separately)."""
    if plays.empty:
        return pd.DataFrame(columns=WEEKLY_COLS)
    rows = []
    for key, g in with_all(plays, ["day_group"]).groupby(["league", "week", "day_group"], sort=True):
        rows.append(dict(zip(["league", "week", "day_group"], key))
                    | summarize(list(g["side_result"]), list(g["side_odds"])))
    return pd.DataFrame(rows, columns=WEEKLY_COLS)
