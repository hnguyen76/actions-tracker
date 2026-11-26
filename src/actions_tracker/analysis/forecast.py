"""Forecast for the user's method: how often did the same situation win in the past?

Every play of the method (spread, >= 5 picks; Mon-Fri follow the crowd, Sat-Sun fade it) is described by
league x day group x crowd type (unanimous n/n or mixed) x pick bucket (5-7, 8-9, 10+). The forecast for an
upcoming play is the past win rate of the most specific situation that has at least MIN_N graded plays,
shrunk towards 50% (PRIOR plays worth of 50/50), so a 4-1 cell does not read as 80%.

Honest check: `walk_forward` predicts every week using only earlier weeks and grades those predictions.
History counts the picks shown on the By-Game cards; live counts one vote per expert, so live pick buckets
run lower than history buckets for the same game.
"""

import math

import pandas as pd

from actions_tracker.analysis.stats import american_profit

MIN_N = 20         # a situation needs this many graded plays before it is used on its own
PRIOR = 20         # plays of 50/50 mixed into every rate
BREAK_EVEN = 0.5238
FORECAST_COLS = ["league", "game_id", "start_time", "et_date", "day_group", "match", "crowd", "votes", "total_votes",
                 "crowd_type", "bucket", "method", "pick", "line", "p_win", "ci_low", "ci_high", "basis", "basis_n",
                 "ev_u"]
BACKTEST_COLS = ["league", "p_bucket", "n", "wins", "losses", "win_pct", "avg_p", "units"]
CELL_COLS = ["league", "day_group", "crowd_type", "bucket", "n", "wins", "losses", "raw_pct", "p_win"]
_DG = {"T2-6": "Mon–Fri", "T7-CN": "Sat–Sun"}
_CT = {"unanimous": "đồng thuận", "mixed": "không đồng thuận"}


def bucket_of(total_votes) -> str:
    n = int(total_votes)
    return "10+" if n >= 10 else "8-9" if n >= 8 else "5-7"


def _prep(plays: pd.DataFrame) -> pd.DataFrame:
    df = plays.copy()
    df["crowd_type"] = ["unanimous" if int(v) == int(t) else "mixed" for v, t in zip(df["votes"], df["total_votes"])]
    df["bucket"] = [bucket_of(t) for t in df["total_votes"]]
    return df


def _keys(r) -> list[tuple]:
    """Most specific situation first, then broader ones."""
    return [(r["league"], r["day_group"], r["crowd_type"], r["bucket"]),
            (r["league"], r["day_group"], r["crowd_type"], None),
            (r["league"], r["day_group"], None, None),
            (r["league"], None, None, None)]


def _label(key) -> str:
    league, dg, ct, b = key
    parts = [league.upper()] + ([_DG.get(dg, dg)] if dg else []) + ([_CT.get(ct, ct)] if ct else []) \
        + ([f"{b} picks"] if b else [])
    return " · ".join(parts)


def fit(graded: pd.DataFrame) -> dict:
    """{situation key: [wins, losses]} over graded plays (pushes left out)."""
    counts: dict = {}
    for r in _prep(graded).to_dict("records"):
        if r["result"] not in ("win", "loss"):
            continue
        for key in _keys(r):
            c = counts.setdefault(key, [0, 0])
            c[0 if r["result"] == "win" else 1] += 1
    return counts


def _wilson(p_hat: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    d = 1 + z * z / n
    c = p_hat + z * z / (2 * n)
    h = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def predict(r: dict, counts: dict) -> dict:
    for key in _keys(r):
        w, l = counts.get(key, [0, 0])
        if w + l >= MIN_N or key[1] is None:
            n = w + l
            p = (w + PRIOR / 2) / (n + PRIOR)
            lo, hi = _wilson(w / n if n else 0.5, n)
            return {"p_win": p, "ci_low": lo, "ci_high": hi, "basis": _label(key), "basis_n": n}
    return {"p_win": 0.5, "ci_low": 0.0, "ci_high": 1.0, "basis": "chưa có dữ liệu", "basis_n": 0}


def _ev(p: float, odds) -> float:
    return p * american_profit(odds) - (1 - p)


def forecast_upcoming(season: pd.DataFrame, now: str) -> pd.DataFrame:
    """Upcoming plays of the method with their forecast, best first. Trained on every graded play so far."""
    if season.empty:
        return pd.DataFrame(columns=FORECAST_COLS)
    graded = season[season["result"].isin(["win", "loss", "push"])]
    counts = fit(graded) if len(graded) else {}
    up = season[season["result"].isna() & (season["start_time"].astype(str) > now)]
    rows = []
    for r in _prep(up).to_dict("records") if len(up) else []:
        f = predict(r, counts)
        rows.append({**{k: r.get(k) for k in FORECAST_COLS if k in r}, **f, "ev_u": _ev(f["p_win"], r.get("odds"))})
    out = pd.DataFrame(rows, columns=FORECAST_COLS)
    return out.sort_values(["p_win", "start_time"], ascending=[False, True]).reset_index(drop=True)


def cells(season: pd.DataFrame) -> pd.DataFrame:
    """The most specific situations and their past record (what the forecast is built from)."""
    graded = season[season["result"].isin(["win", "loss"])] if len(season) else season
    rows = []
    for key, (w, l) in sorted(fit(graded).items(), key=lambda kv: str(kv[0])) if len(graded) else []:
        if key[3] is None:
            continue
        rows.append({"league": key[0], "day_group": key[1], "crowd_type": key[2], "bucket": key[3], "n": w + l,
                     "wins": w, "losses": l, "raw_pct": w / (w + l) if w + l else None,
                     "p_win": (w + PRIOR / 2) / (w + l + PRIOR)})
    return pd.DataFrame(rows, columns=CELL_COLS)


def walk_forward(season: pd.DataFrame, first_week: int = 3) -> pd.DataFrame:
    """Predict week w from weeks < w only, then grade: how did plays forecast above / below break-even do?"""
    rows = []
    if season.empty:
        return pd.DataFrame(columns=BACKTEST_COLS)
    df = _prep(season[season["result"].isin(["win", "loss"]) & season["week"].notna()])
    preds = []
    for league, g in df.groupby("league"):
        for week in sorted({int(w) for w in g["week"]}):
            if week < first_week:
                continue
            counts = fit(g[g["week"].astype(int) < week])
            for r in g[g["week"].astype(int) == week].to_dict("records"):
                preds.append({"league": league, "p": predict(r, counts)["p_win"], "result": r["result"],
                              "odds": r.get("odds")})
    pdf = pd.DataFrame(preds)
    if pdf.empty:
        return pd.DataFrame(columns=BACKTEST_COLS)
    edges = [(0, 0.5, "< 50%"), (0.5, BREAK_EVEN, "50–52,4%"), (BREAK_EVEN, 0.56, "52,4–56%"), (0.56, 1.01, "≥ 56%")]
    for league in [*sorted(pdf["league"].unique()), "ALL"]:
        mine = pdf if league == "ALL" else pdf[pdf["league"] == league]
        for lo, hi, label in edges + [(BREAK_EVEN, 1.01, "Trên hòa vốn (đặt)")]:
            b = mine[(mine["p"] >= lo) & (mine["p"] < hi)]
            w, l = int((b["result"] == "win").sum()), int((b["result"] == "loss").sum())
            units = sum(american_profit(o) if res == "win" else -1.0 for res, o in zip(b["result"], b["odds"]))
            rows.append({"league": league, "p_bucket": label, "n": w + l, "wins": w, "losses": l,
                         "win_pct": w / (w + l) if w + l else None,
                         "avg_p": float(b["p"].mean()) if len(b) else None, "units": units})
    return pd.DataFrame(rows, columns=BACKTEST_COLS)
