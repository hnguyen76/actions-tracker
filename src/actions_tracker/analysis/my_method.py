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


# --- the whole season: history (By-Game cards, weeks 1..) + live games not in the history files -------------
SEASON_COLS = ["league", "week", "game_id", "start_time", "et_date", "day_group", "match", "score", "crowd", "votes",
               "total_votes", "method", "pick", "line", "fav_dog", "odds", "result", "source"]
SEASON_SUMMARY_COLS = ["league", "week", "day_group"] + SUMMARY_KEYS


def season_plays(sides: pd.DataFrame, live: pd.DataFrame, games: dict) -> pd.DataFrame:
    """games: {game_id: {"week": .., "away_score": .., "home_score": ..}} from the database, for live rows."""
    rows = []
    seen = set()
    if not sides.empty:
        s = sides[(sides["market"] == "spread") & sides["league"].isin(LEAGUES) & (sides["picks"] > sides["opp_picks"])
                  & (sides["picks"] + sides["opp_picks"] >= MIN_PICKS)]
        for r in s.itertuples():
            weekday = r.day_group == "T2-6"
            crowd = r.home if r.side == "home" else r.away
            pick = crowd if weekday else (r.away if r.side == "home" else r.home)
            line = _num(r.line)
            res = r.result if isinstance(r.result, str) else None
            seen.add(int(r.game_id))
            rows.append({
                "league": r.league, "week": int(r.week), "game_id": int(r.game_id), "start_time": None,
                "et_date": r.et_date, "day_group": r.day_group, "match": f"{r.away}@{r.home}",
                "score": f"{int(r.away_score)}-{int(r.home_score)}" if pd.notna(r.away_score) else None,
                "crowd": crowd, "votes": int(r.picks), "total_votes": int(r.picks + r.opp_picks),
                "method": "follow" if weekday else "fade", "pick": pick,
                "line": line if weekday or line is None else -line,
                "odds": r.odds if weekday else r.opp_odds,
                "result": res if weekday or res is None else _FLIP.get(res, res), "source": "history"})
    if not live.empty:
        for r in live.itertuples():
            if int(r.game_id) in seen:
                continue
            g = games.get(int(r.game_id), {})
            score = f"{int(g['away_score'])}-{int(g['home_score'])}"                 if g.get("away_score") is not None and g.get("home_score") is not None else None
            rows.append({
                "league": r.league, "week": g.get("week"), "game_id": int(r.game_id),
                "start_time": r.start_time, "et_date": r.et_date, "day_group": r.day_group, "match": r.match,
                "score": score, "crowd": r.crowd, "votes": int(r.votes), "total_votes": int(r.total_votes),
                "method": r.method, "pick": r.pick, "line": r.line, "odds": r.odds,
                "result": r.result if isinstance(r.result, str) else None, "source": "live"})
    for row in rows:  # the side we bet: favourite (minus line), underdog (plus line) or pick'em
        ln = row["line"]
        row["fav_dog"] = None if ln is None or pd.isna(ln) else "favorite" if ln < 0 else "underdog" if ln > 0 else "pk"
    out = pd.DataFrame(rows, columns=SEASON_COLS)
    return out.sort_values(["league", "et_date", "game_id"], ascending=[True, False, True], kind="stable") \
        .reset_index(drop=True).astype(object)


def season_summary(plays: pd.DataFrame) -> pd.DataFrame:
    """Per league: ALL weeks and every week, each split T2-6 / T7-CN / ALL."""
    rows = []
    for league in LEAGUES:
        mine = plays[plays["league"] == league] if len(plays) else plays
        weeks = sorted({int(w) for w in mine["week"] if w is not None and not pd.isna(w)}) if len(mine) else []
        for week in ["ALL", *weeks]:
            wk = mine if week == "ALL" else mine[mine["week"] == week]
            for dg in ("T2-6", "T7-CN", "ALL"):
                g = wk if dg == "ALL" else wk[wk["day_group"] == dg]
                g = g[g["result"].notna()] if len(g) else g
                rows.append({"league": league, "week": week, "day_group": dg,
                             **summarize(list(g["result"]) if len(g) else [], list(g["odds"]) if len(g) else [])})
    return pd.DataFrame(rows, columns=SEASON_SUMMARY_COLS)


SENSITIVITY_THRESHOLDS = (5, 8, 9, 10)
SENSITIVITY_COLS = ["league", "min_picks", "crowd_type", "day_group"] + SUMMARY_KEYS


def season_sensitivity(plays: pd.DataFrame) -> pd.DataFrame:
    """The same method with a higher pick threshold (>= 5 / 8 / 9 / 10 picks on the market), also split by
    crowd type: unanimous (every pick on one side, 5/5) vs mixed (someone took the other side, 8/9)."""
    rows = []
    for league in LEAGUES:
        mine = plays[(plays["league"] == league) & plays["result"].notna()] if len(plays) else plays
        for k in SENSITIVITY_THRESHOLDS:
            sel = mine[pd.to_numeric(mine["total_votes"]) >= k] if len(mine) else mine
            unan = (pd.to_numeric(sel["votes"]) == pd.to_numeric(sel["total_votes"])) if len(sel) else None
            for crowd in ("ALL", "unanimous", "mixed"):
                c = sel if crowd == "ALL" or not len(sel) else (sel[unan] if crowd == "unanimous" else sel[~unan])
                for dg in ("T2-6", "T7-CN", "ALL"):
                    g = c if dg == "ALL" else (c[c["day_group"] == dg] if len(c) else c)
                    rows.append({"league": league, "min_picks": k, "crowd_type": crowd, "day_group": dg,
                                 **summarize(list(g["result"]) if len(g) else [], list(g["odds"]) if len(g) else [])})
    return pd.DataFrame(rows, columns=SENSITIVITY_COLS)


FAVDOG_COLS = ["league", "fav_dog", "day_group"] + SUMMARY_KEYS


def season_favdog(plays: pd.DataFrame) -> pd.DataFrame:
    """The method split by the side we bet: favourite vs underdog (pick'em and unknown lines left out)."""
    rows = []
    for league in LEAGUES:
        mine = plays[(plays["league"] == league) & plays["result"].notna()] if len(plays) else plays
        for fd in ("favorite", "underdog"):
            sel = mine[mine["fav_dog"] == fd] if len(mine) else mine
            for dg in ("T2-6", "T7-CN", "ALL"):
                g = sel if dg == "ALL" else (sel[sel["day_group"] == dg] if len(sel) else sel)
                rows.append({"league": league, "fav_dog": fd, "day_group": dg,
                             **summarize(list(g["result"]) if len(g) else [], list(g["odds"]) if len(g) else [])})
    return pd.DataFrame(rows, columns=FAVDOG_COLS)
