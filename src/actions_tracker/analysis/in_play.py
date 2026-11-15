"""Plays whose game has started but is not graded yet: the live (or final ESPN) score next to each pick,
and whether the pick is covering right now. Sources: the user's method and the rules under test."""

import pandas as pd

IN_PLAY_COLS = ["game_id", "league", "start_time", "match", "away_score", "home_score", "state", "detail",
                "source", "market", "pick", "line", "bet_side", "crowd", "now"]


def _now(market: str, side: str, line, away: int, home: int) -> str | None:
    """'win' / 'loss' / 'push' if the game ended right now; None when the line is missing."""
    if line is None or pd.isna(line):
        return None
    if market == "spread":
        own, other = (home, away) if side == "home" else (away, home)
        m = own + float(line) - other
    elif market == "total":
        m = (away + home - float(line)) * (1 if side == "over" else -1)
    else:
        return None
    return "win" if m > 0 else "loss" if m < 0 else "push"


def in_play(scores: pd.DataFrame, my_method: pd.DataFrame, rule_plays: pd.DataFrame) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame(columns=IN_PLAY_COLS)
    live = scores[(scores["state"] == "live") | ((scores["state"] == "final") & ~scores["graded"].astype(bool))]
    by_game = {int(r.game_id): r for r in live.itertuples()}
    rows = []

    def add(r, source, market, pick, line, side, crowd=None):
        s = by_game.get(int(r.game_id))
        if s is None or pd.isna(s.away_score):
            return
        a, h = int(s.away_score), int(s.home_score)
        rows.append({"game_id": int(r.game_id), "league": r.league, "start_time": r.start_time, "match": r.match,
                     "away_score": a, "home_score": h, "state": s.state, "detail": s.detail, "source": source,
                     "market": market, "pick": pick, "line": None if line is None or pd.isna(line) else float(line),
                     "bet_side": side, "crowd": crowd, "now": _now(market, side, line, a, h)})

    for r in my_method.itertuples() if len(my_method) else []:
        if r.status != "graded":
            add(r, "Cách của bạn", "spread", r.pick, r.line, r.bet_side, f"{r.crowd} {r.votes}/{r.total_votes}")
    for r in rule_plays.itertuples() if len(rule_plays) else []:
        if r.status != "graded":
            add(r, r.rule_name, r.market, r.pick, r.line, r.bet_side)
    out = pd.DataFrame(rows, columns=IN_PLAY_COLS)
    return out.sort_values(["state", "start_time", "game_id"], ascending=[False, True, True], kind="stable") \
        .reset_index(drop=True)
