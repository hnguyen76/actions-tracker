"""C. Expert consensus versus the betting public (spec §7C)."""

import pandas as pd

from actions_tracker.analysis.consensus import CG_COLS
from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize, with_all
from actions_tracker.config import HEAVY_PUBLIC, MONEY_TICKET_GAP
from actions_tracker.grading import opposite

PG_COLS = CG_COLS + ["public_side", "relation", "heavy"]
SUMMARY_COLS = ["league", "market", "relation", "heavy"] + SUMMARY_KEYS
MVT_COLS = ["league", "market"] + SUMMARY_KEYS


def public_games(cg: pd.DataFrame) -> pd.DataFrame:
    if cg.empty:
        return pd.DataFrame(columns=PG_COLS)
    tickets = pd.to_numeric(cg["tickets_pct"], errors="coerce")
    pg = cg[tickets.notna() & (tickets != 50)].copy()
    t = pd.to_numeric(pg["tickets_pct"])
    pg["public_side"] = [s if tp > 50 else opposite(s) for s, tp in zip(pg["side"], t)]
    pg["relation"] = ["agree" if ps == s else "contrarian" for ps, s in zip(pg["public_side"], pg["side"])]
    pg["heavy"] = [max(tp, 100 - tp) >= HEAVY_PUBLIC for tp in t]
    return pg.reset_index(drop=True)[PG_COLS]


def public_summary(pg: pd.DataFrame) -> pd.DataFrame:
    graded = pg[pg["side_result"].notna()]
    if graded.empty:
        return pd.DataFrame(columns=SUMMARY_COLS)
    rows = []
    for key, g in with_all(graded, ["league", "market"]).groupby(["league", "market", "relation", "heavy"], sort=True):
        rows.append(dict(zip(["league", "market", "relation", "heavy"], key))
                    | summarize(list(g["side_result"]), list(g["side_odds"])))
    return pd.DataFrame(rows, columns=SUMMARY_COLS)


def money_vs_tickets(picks: pd.DataFrame) -> pd.DataFrame:
    if picks.empty:
        return pd.DataFrame(columns=MVT_COLS)
    sides = picks.drop_duplicates(["game_id", "market", "pick_side"])
    gap = pd.to_numeric(sides["money_pct"], errors="coerce") - pd.to_numeric(sides["tickets_pct"], errors="coerce")
    sides = sides[(gap >= MONEY_TICKET_GAP) & sides["side_result"].notna()]
    if sides.empty:
        return pd.DataFrame(columns=MVT_COLS)
    rows = []
    for key, g in with_all(sides, ["league", "market"]).groupby(["league", "market"], sort=True):
        rows.append(dict(zip(["league", "market"], key))
                    | summarize(list(g["side_result"]), list(g["close_odds"])))
    return pd.DataFrame(rows, columns=MVT_COLS)
