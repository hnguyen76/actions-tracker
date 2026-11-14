"""The user's own spread method, shown on its own above the frozen rules.

Spread, NFL and NCAAF, at least MIN_PICKS experts with one side ahead: on Monday-Friday (US/Eastern) bet the
crowd's side, on Saturday-Sunday bet against it. Live data counts one vote per expert (latest pick before
kickoff); the season look-back uses the pick counts on the By-Game cards. Display only: NCAAF is also logged
as the frozen rule `ncaaf_spread_daygroup`; for NFL this view is the only place it is tracked.
"""

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, summarize
from actions_tracker.config import TZ

MIN_PICKS = 5
LEAGUES = ("nfl", "ncaaf")
PLAY_COLS = ["game_id", "league", "start_time", "et_date", "day_group", "match", "crowd", "votes", "total_votes",
             "method", "bet_side", "pick", "line", "odds", "status", "result"]
SUMMARY_COLS = (["league", "day_group", "method", "hist_wins", "hist_losses", "hist_pushes", "hist_win_pct", "hist_n"]
                + SUMMARY_KEYS + ["pending"])
_FLIP = {"win": "loss", "loss": "win", "push": "push"}
_OTHER = {"home": "away", "away": "home"}


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _bet_line(picks: pd.DataFrame, game_id, bet_side: str):
    """Closing line of the side we bet when there is one, else the experts' median line for it."""
    rows = picks[(picks["game_id"] == game_id) & (picks["market"] == "spread")] if not picks.empty else picks
    if rows.empty:
        return None
    own = rows[rows["pick_side"] == bet_side]
    for col in ("close_line",):
        if col in rows and own[col].notna().any():
            return _num(own[col].dropna().iloc[0])
    if own["line"].notna().any():
        return _num(pd.to_numeric(own["line"], errors="coerce").median())
    other = rows[rows["pick_side"] == _OTHER[bet_side]]
    if "close_line" in rows and other["close_line"].notna().any():
        return -_num(other["close_line"].dropna().iloc[0])
    med = _num(pd.to_numeric(other["line"], errors="coerce").median()) if len(other) else None
    return None if med is None else -med


def my_method_plays(cg: pd.DataFrame, picks: pd.DataFrame) -> pd.DataFrame:
    if cg.empty:
        return pd.DataFrame(columns=PLAY_COLS)
    sel = cg[(cg["market"] == "spread") & cg["league"].isin(LEAGUES)
             & (pd.to_numeric(cg["total_votes"]) >= MIN_PICKS)]
    rows = []
    for r in sel.itertuples():
        local = pd.Timestamp(r.start_time).tz_convert(TZ)
        weekday = local.day_of_week <= 4
        bet = r.side if weekday else _OTHER[r.side]
        team = lambda s: r.home_abbr if s == "home" else r.away_abbr  # noqa: E731
        res = r.side_result if isinstance(r.side_result, str) else None
        result = res if weekday or res is None else _FLIP.get(res, res)
        rows.append({
            "game_id": int(r.game_id), "league": r.league, "start_time": r.start_time,
            "et_date": local.strftime("%Y-%m-%d"), "day_group": "T2-6" if weekday else "T7-CN",
            "match": f"{r.away_abbr}@{r.home_abbr}", "crowd": team(r.side), "votes": int(r.votes),
            "total_votes": int(r.total_votes), "method": "follow" if weekday else "fade", "bet_side": bet,
            "pick": team(bet), "line": _bet_line(picks, r.game_id, bet),
            "odds": r.side_odds if weekday else r.opp_odds,
            "status": "graded" if result else "pending", "result": result,
        })
    out = pd.DataFrame(rows, columns=PLAY_COLS)
    return out.sort_values("start_time", ascending=False, kind="stable").reset_index(drop=True).astype(object)


def _hist(sides: pd.DataFrame, league: str, day_group: str) -> tuple[int, int, int]:
    if sides.empty:
        return 0, 0, 0
    s = sides[(sides["market"] == "spread") & (sides["picks"] > sides["opp_picks"])
              & (sides["picks"] + sides["opp_picks"] >= MIN_PICKS) & sides["result"].notna()]
    if league != "ALL":
        s = s[s["league"] == league]
    else:
        s = s[s["league"].isin(LEAGUES)]
    w = l = p = 0
    for dg, res in zip(s["day_group"], s["result"]):
        if day_group != "ALL" and dg != day_group:
            continue
        res = res if dg == "T2-6" else _FLIP.get(res, res)
        w, l, p = w + (res == "win"), l + (res == "loss"), p + (res == "push")
    return w, l, p


def my_method_summary(plays: pd.DataFrame, sides: pd.DataFrame) -> pd.DataFrame:
    """League x day group (each with an ALL row): season look-back and the live record."""
    rows = []
    for league in (*LEAGUES, "ALL"):
        for dg in ("T2-6", "T7-CN", "ALL"):
            mine = plays if plays.empty else plays[((plays["league"] == league) | (league == "ALL"))
                                                   & ((plays["day_group"] == dg) | (dg == "ALL"))]
            graded = mine[mine["status"] == "graded"] if len(mine) else mine
            s = summarize(list(graded["result"]) if len(graded) else [], list(graded["odds"]) if len(graded) else [])
            hw, hl, hp = _hist(sides, league, dg)
            rows.append({"league": league, "day_group": dg,
                         "method": {"T2-6": "follow", "T7-CN": "fade"}.get(dg, "both"),
                         "hist_wins": hw, "hist_losses": hl, "hist_pushes": hp,
                         "hist_win_pct": hw / (hw + hl) if hw + hl else None, "hist_n": hw + hl, **s,
                         "pending": int((mine["status"] == "pending").sum()) if len(mine) else 0})
    return pd.DataFrame(rows, columns=SUMMARY_COLS)
