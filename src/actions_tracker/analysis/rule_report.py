"""Forward-test record of the frozen rules: every logged play, graded at the closing line when there is one."""

import sqlite3

import pandas as pd

from actions_tracker.analysis.stats import SUMMARY_KEYS, american_profit, summarize
from actions_tracker.config import RULE_CI_FLOOR, RULE_FAIL, RULE_PASS, RULE_TARGET_N, TZ
from actions_tracker.grading import grade_side
from actions_tracker.rules import RULES

PLAY_COLS = ["rule_id", "rule_name", "league", "game_id", "start_time", "et_date", "day_group", "match", "market",
             "bet_side", "pick", "entry_line", "entry_odds", "line", "odds", "line_source", "basis", "first_logged_at", "logged_at",
             "status", "result", "units"]
SUMMARY_COLS = (["rule_id", "name", "how", "league", "market", "hist_record", "hist_win_pct", "hist_n"]
                + SUMMARY_KEYS + ["pending", "target_n", "decision"])
_SQL = """
SELECT r.*, g.league, g.start_time, g.status AS game_status, g.home_abbr, g.away_abbr, g.home_score, g.away_score,
       cl.line AS close_line, cl.odds AS close_odds
FROM rule_plays r
JOIN games g ON g.id = r.game_id
LEFT JOIN closing_lines cl ON cl.game_id = r.game_id AND cl.market = r.market AND cl.side = r.bet_side
ORDER BY g.start_time DESC, r.game_id, r.rule_id
"""


def rule_plays(conn: sqlite3.Connection) -> pd.DataFrame:
    names = {r["id"]: r["name"] for r in RULES}
    rows = []
    for r in map(dict, conn.execute(_SQL).fetchall()):
        if r["market"] != "ml" and r["close_line"] is not None:
            line, source = r["close_line"], "odds_api_close"
        else:
            line, source = r["line"], ("action_network_logged" if r["line"] is not None else None)
        odds = r["close_odds"] if r["close_odds"] is not None else r["odds"]
        result = None
        if (r["game_status"] == "complete" and r["home_score"] is not None and r["away_score"] is not None
                and (r["market"] == "ml" or line is not None)):
            result = grade_side(r["market"], r["bet_side"], line, r["home_score"], r["away_score"])
        local = pd.Timestamp(r["start_time"]).tz_convert(TZ)
        side = r["bet_side"]
        rows.append({
            "rule_id": r["rule_id"], "rule_name": names.get(r["rule_id"], r["rule_id"]), "league": r["league"],
            "game_id": r["game_id"], "start_time": r["start_time"], "et_date": local.strftime("%Y-%m-%d"),
            "day_group": "T2-6" if local.day_of_week <= 4 else "T7-CN",
            "match": f"{r['away_abbr']}@{r['home_abbr']}", "market": r["market"], "bet_side": side,
            "pick": r["home_abbr"] if side == "home" else r["away_abbr"] if side == "away" else side.title(),
            "entry_line": r["line"], "entry_odds": r["odds"],
            "line": line, "odds": odds, "line_source": source, "basis": r["basis"],
            "first_logged_at": r["first_logged_at"], "logged_at": r["logged_at"],
            "status": "graded" if result else "pending", "result": result,
            "units": None if result is None else american_profit(odds) if result == "win" else -1.0
            if result == "loss" else 0.0,
        })
    return pd.DataFrame(rows, columns=PLAY_COLS).astype(object)


def rule_summary(plays: pd.DataFrame) -> pd.DataFrame:
    """One row per rule (also when it has no plays yet) with its hindsight record and its forward record."""
    rows = []
    for rule in RULES:
        mine = plays[plays["rule_id"] == rule["id"]]
        graded = mine[mine["status"] == "graded"]
        s = summarize(list(graded["result"]), list(graded["odds"]))
        hist_n = rule["hist_wins"] + rule["hist_losses"]
        if s["n"] < RULE_TARGET_N:
            decision = "collecting"
        else:
            decision = ("pass" if s["win_pct"] >= RULE_PASS and s["ci_low"] > RULE_CI_FLOOR
                        else "fail" if s["win_pct"] < RULE_FAIL else "watch")
        rows.append({
            "rule_id": rule["id"], "name": rule["name"], "how": rule["how"], "league": rule["league"],
            "market": rule["market"], "hist_record": f"{rule['hist_wins']}-{rule['hist_losses']}",
            "hist_win_pct": rule["hist_wins"] / hist_n, "hist_n": hist_n, **s,
            "pending": int((mine["status"] == "pending").sum()), "target_n": RULE_TARGET_N, "decision": decision,
        })
    return pd.DataFrame(rows, columns=SUMMARY_COLS)
