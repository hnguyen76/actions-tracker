"""One decision per upcoming play, so the dashboard can say plainly what to do on game day.

Only what has been tested decides: a rule play is bet only once its rule passed the forward test
(Rule_Summary.decision == "pass"); while a rule is still collecting, its plays are "paper" (log, no money).
Expert consensus on its own is never a bet: following it went 48.6% over the season and fading it 51.4%,
both below the 52.4% break-even, and choosing groups by their past record did not help out of sample.
"""

import pandas as pd

from actions_tracker.config import TZ

DECISION_COLS = ["et_date", "start_time", "league", "game_id", "match", "market", "action", "pick", "stake_u",
                 "reason", "evidence", "rule_ids"]
STAKE = {"pass": 1.0}  # units per play once a rule passed; every other state stakes nothing
ACTION = {"pass": "bet", "collecting": "paper", "watch": "paper", "fail": "skip"}
ORDER = {"bet": 0, "mine": 1, "paper": 2, "conflict": 3, "skip": 4}
MINE = "Cách của bạn"
CONSENSUS_REASON = "Chỉ có consensus của expert — dữ liệu hiện tại chưa chứng minh lợi thế để đặt tiền"
_MARKET = {"spread": "Spread", "total": "Total", "ml": "Moneyline"}


def _line(market, line) -> str:
    if market == "ml" or line is None or pd.isna(line):
        return ""
    text = f"+{line:g}" if market == "spread" and line > 0 else f"{line:g}"
    return " " + text.replace(".", ",")  # Vietnamese decimal comma, as on the rest of the dashboard


def _et_date(start: str) -> str:
    return pd.Timestamp(start).tz_convert(TZ).strftime("%Y-%m-%d")


def _mine_reason(m) -> str:
    how = "theo" if m.method == "follow" else "ngược"
    return f"{MINE}: {how} đám đông {m.crowd} {int(m.votes)}/{int(m.total_votes)}"


def decisions(rule_plays: pd.DataFrame, rule_summary: pd.DataFrame, upcoming: pd.DataFrame, now: str,
              my_method: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    mine = {}
    if my_method is not None and not my_method.empty:
        up = my_method[(my_method["status"] != "graded") & (my_method["start_time"].astype(str) > now)]
        mine = {(int(m.game_id), "spread"): m for m in up.itertuples()}
    covered = set()
    status = dict(zip(rule_summary["rule_id"], rule_summary["decision"])) if not rule_summary.empty else {}
    record = {r.rule_id: r for r in rule_summary.itertuples()} if not rule_summary.empty else {}
    pending = rule_plays[(rule_plays["status"] == "pending") & (rule_plays["start_time"].astype(str) > now)] \
        if not rule_plays.empty else rule_plays
    for (game_id, market), g in (pending.groupby(["game_id", "market"], sort=False) if len(pending) else []):
        first = g.iloc[0]
        covered.add((game_id, market))
        names = " + ".join(dict.fromkeys(g["rule_name"]))
        evidence = []
        for rid in dict.fromkeys(g["rule_id"]):
            r = record.get(rid)
            if r is None:
                continue
            fwd = f"{r.wins}-{r.losses}-{r.pushes}" if r.n + r.pushes else "chưa có"
            evidence.append(f"nhìn lại {r.hist_record} · ghi trước {fwd} ({r.n}/{r.target_n})")
        base = {"et_date": _et_date(first["start_time"]), "start_time": first["start_time"], "league": first["league"],
                "game_id": int(game_id), "match": first["match"], "market": market,
                "evidence": "; ".join(evidence), "rule_ids": ",".join(dict.fromkeys(g["rule_id"]))}
        if g["bet_side"].nunique() > 1:
            picks = " / ".join(f"{p}{_line(market, l)}" for p, l in zip(g["pick"], g["line"]))
            rows.append(base | {"action": "conflict", "pick": picks, "stake_u": 0.0,
                                "reason": f"Hai quy tắc chọn hai bên ngược nhau ({names})"})
            continue
        states = [status.get(rid, "collecting") for rid in g["rule_id"]]
        action = min((ACTION.get(s, "paper") for s in states), key=ORDER.get)
        basis = "; ".join(dict.fromkeys(b for b in g["basis"] if b))
        reason = f"{names}: {basis}" if basis else names
        m = mine.pop((int(game_id), market), None)
        if m is not None:  # the user's method backs the same game: say so (and whether it agrees)
            same = m.bet_side == first["bet_side"]
            reason = f"{_mine_reason(m)} — {'cùng bên' if same else 'NGƯỢC bên'} với quy tắc · " + reason
        rows.append(base | {"action": action, "pick": f"{first['pick']}{_line(market, first['line'])}",
                            "stake_u": max(STAKE.get(s, 0.0) for s in states), "reason": reason})
    for (game_id, market), m in mine.items():
        covered.add((game_id, market))
        rows.append({"et_date": m.et_date, "start_time": m.start_time, "league": m.league, "game_id": int(game_id),
                     "match": m.match, "market": market, "action": "mine",
                     "pick": f"{m.pick}{_line(market, m.line)}", "stake_u": 0.0, "reason": _mine_reason(m),
                     "evidence": "", "rule_ids": "my_method"})
    if not upcoming.empty:
        for r in upcoming[upcoming["start_time"].astype(str) > now].itertuples():
            if (r.game_id, r.market) in covered:
                continue
            side = r.home_abbr if r.side == "home" else r.away_abbr if r.side == "away" else str(r.side).title()
            rows.append({"et_date": _et_date(r.start_time), "start_time": r.start_time, "league": r.league,
                         "game_id": int(r.game_id), "match": f"{r.away_abbr}@{r.home_abbr}", "market": r.market,
                         "action": "skip", "pick": f"Đa số chọn {side} ({r.votes}/{r.total_votes})",
                         "stake_u": 0.0, "reason": CONSENSUS_REASON, "evidence": "", "rule_ids": ""})
    out = pd.DataFrame(rows, columns=DECISION_COLS)
    if out.empty:
        return out
    out["_o"] = out["action"].map(ORDER)
    return out.sort_values(["et_date", "_o", "start_time"], kind="stable").drop(columns="_o").reset_index(drop=True)
