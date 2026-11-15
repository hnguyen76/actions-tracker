"""Expert-picks report for one league and one or more US/Eastern dates, from the Actions tracker DB.

Usage (run with the repo's venv so `actions_tracker` imports):
  python .claude/skills/bettingskill/scripts/day_report.py --league nfl --date 2026-11-08
  ... --date 2026-11-07 --date 2026-11-08          # several days (a weekend)
  ... --csv out_dir                                 # also write picks + consensus CSVs

Prints: games with scores, overall record, by market, favorite/underdog, home/away, over/under,
every consensus play (>= 3 experts) with result, consensus split at 75%, top/bottom experts.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]  # <repo>/.claude/skills/bettingskill/scripts/
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

from actions_tracker import db  # noqa: E402
from actions_tracker.analysis.consensus import consensus_games  # noqa: E402
from actions_tracker.analysis.stats import summarize  # noqa: E402
from actions_tracker.grading import load_graded_picks  # noqa: E402


def line(label: str, sub: pd.DataFrame, col: str = "expert_result", odds: str = "odds") -> str:
    s = summarize(list(sub[col]), list(sub[odds]))
    if not s["n"]:
        return f"  {label:<34} n=  0"
    flag = "  (it mau)" if s["low_sample"] else ""
    return (f"  {label:<34} n={s['n']:>3}  {s['wins']}-{s['losses']}-{s['pushes']}  "
            f"win {s['win_pct'] * 100:5.1f}%  ROI {s['roi'] * 100:+6.1f}%{flag}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["nfl", "ncaaf", "nba", "mlb", "nhl", "ncaab"])
    ap.add_argument("--date", action="append", required=True, help="US/Eastern date YYYY-MM-DD (repeatable)")
    ap.add_argument("--db", default=str(REPO / "data" / "actions.db"))
    ap.add_argument("--csv", help="folder to write picks/consensus CSVs")
    a = ap.parse_args()

    conn = db.connect(a.db)
    p = load_graded_picks(conn)
    if p.empty:
        print("DB has no picks yet — run the Desktop button / `python -m actions_tracker run` first.")
        return
    p["et"] = pd.to_datetime(p["start_time"], utc=True).dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    w = p[(p.league == a.league) & p.et.isin(a.date)].copy()
    games = w.drop_duplicates("game_id").sort_values("start_time")
    print(f"=== {a.league.upper()} {', '.join(a.date)} - {len(games)} games with picks, "
          f"{len(w)} picks, {w.expert_id.nunique()} experts, graded {w.expert_result.notna().sum()}, "
          f"closing lines on {w.close_line.notna().sum()} picks ===")
    for _, g in games.iterrows():
        score = f"{int(g.away_score)}-{int(g.home_score)}" if g.status == "complete" else "chua co ti so"
        print(f"  {g.away_abbr}@{g.home_abbr}  {score}")

    print("\nRECORD (each pick graded at the expert's own line, 1u, missing odds = -110)")
    print(line("Tat ca", w))
    for m in ("spread", "total", "ml"):
        print(line(f"Keo {m}", w[w.market == m]))
    for col, labels in (("fav_dog", ("favorite", "underdog")), ("home_away", ("home", "away")),
                        ("over_under", ("over", "under"))):
        for k in labels:
            print(line(k, w[w[col] == k]))

    cg = consensus_games(w)
    print(f"\nCONSENSUS (>= 3 experts; graded at closing line, else median expert line) - {len(cg)} plays")
    for _, r in cg.sort_values(["majority_pct", "start_time"], ascending=[False, True]).iterrows():
        pick = {"home": r.home_abbr, "away": r.away_abbr}.get(r.side, r.side)
        print(f"  {r.away_abbr}@{r.home_abbr} {r.market:<6} {pick:<5} {r.votes}/{r.total_votes} "
              f"({r.majority_pct:.0f}%) -> {r.side_result}")
    if len(cg):
        print(line("Theo consensus (all)", cg, "side_result", "side_odds"))
        print(line("Consensus < 75%", cg[cg.majority_pct < 75], "side_result", "side_odds"))
        print(line("Consensus >= 75%", cg[cg.majority_pct >= 75], "side_result", "side_odds"))
        sp = cg[(cg.market == "spread") & (cg.majority_pct >= 75)]
        print(line("Consensus spread >= 75%", sp, "side_result", "side_odds"))

    rows = []
    for (eid, name), sub in w.groupby(["expert_id", "expert_name"]):
        s = summarize(list(sub.expert_result), list(sub.odds))
        if s["n"] >= 3:
            rows.append((s["units"], name, s["n"], s["wins"], s["losses"]))
    rows.sort(reverse=True)
    print("\nEXPERTS (>= 3 graded picks), units at 1u/pick")
    for u, name, n, wi, lo in rows[:5]:
        print(f"  top  {name:<28} {wi}-{lo}  {u:+.1f}u")
    for u, name, n, wi, lo in rows[-5:]:
        print(f"  bot  {name:<28} {wi}-{lo}  {u:+.1f}u")

    if a.csv:
        out = Path(a.csv)
        out.mkdir(parents=True, exist_ok=True)
        tag = f"{a.league}_{'_'.join(a.date)}"
        w.to_csv(out / f"{tag}_picks.csv", index=False)
        cg.to_csv(out / f"{tag}_consensus.csv", index=False)
        print(f"\nCSV: {out / (tag + '_picks.csv')}, {out / (tag + '_consensus.csv')}")


if __name__ == "__main__":
    main()
