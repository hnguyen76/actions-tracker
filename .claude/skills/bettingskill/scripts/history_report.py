"""Season-to-date report from data/history/<league>_sides.csv (built by the repo's scripts/build_history.py).

Each row = one game x market x side with `picks` = number of expert picks on that side (By-Game page counts;
one expert can be counted more than once), graded at Action Network's consensus closing line.

Usage: python -I .claude/skills/bettingskill/scripts/history_report.py nfl [ncaaf ...] [--json out.json]
"""

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[4]  # <repo>/.claude/skills/bettingskill/scripts/
sys.path.insert(0, str(REPO / "src"))
from actions_tracker.analysis.stats import summarize  # noqa: E402

BUCKET_EDGES = [(50, 60), (60, 75), (75, 90), (90, 100.01)]


def rec(results, odds) -> dict:
    s = summarize(list(results), list(odds))
    return {k: s[k] for k in ("n", "wins", "losses", "pushes", "win_pct", "roi")}


def weighted(df: pd.DataFrame) -> dict:
    """Every expert pick counted: a side with 5 picks counts 5 times."""
    rep = df.loc[df.index.repeat(df.picks.clip(lower=0))]
    return rec(rep.result, rep.odds)


def consensus(df: pd.DataFrame) -> pd.DataFrame:
    c = df[(df.picks + df.opp_picks >= 3) & (df.picks > df.opp_picks)].copy()
    c["pct"] = 100 * c.picks / (c.picks + c.opp_picks)
    return c


def fmt(r: dict) -> str:
    if not r["n"]:
        return "n=0"
    return f"{r['wins']}-{r['losses']}-{r['pushes']} (n={r['n']}, {r['win_pct'] * 100:.1f}%, ROI {r['roi'] * 100:+.1f}%)"


def report(league: str) -> dict:
    df = pd.read_csv(REPO / "data" / "history" / f"{league}_sides.csv")
    out: dict = {"league": league, "weeks": sorted(df.week.unique().tolist()), "games": int(df.game_id.nunique())}
    for part, sub in (("ALL", df), ("T2-6", df[df.day_group == "T2-6"]), ("T7-CN", df[df.day_group == "T7-CN"])):
        sm, tm = sub[sub.market.isin(["spread", "ml"])], sub[sub.market == "total"]
        c = consensus(sub)
        cs = c[c.market == "spread"]
        block = {
            "games": int(sub.game_id.nunique()),
            "picks_all": weighted(sub),
            "picks_spread": weighted(sub[sub.market == "spread"]),
            "picks_total": weighted(tm),
            "picks_ml": weighted(sub[sub.market == "ml"]),
            "picks_favorite": weighted(sm[sm.fav_dog == "favorite"]),
            "picks_underdog": weighted(sm[sm.fav_dog == "underdog"]),
            "picks_home": weighted(sm[sm.side == "home"]),
            "picks_away": weighted(sm[sm.side == "away"]),
            "picks_over": weighted(tm[tm.side == "over"]),
            "picks_under": weighted(tm[tm.side == "under"]),
            "cons_all": rec(c.result, c.odds),
            "cons_buckets": {f"{lo}-{int(min(hi, 100))}": rec(c[(c.pct >= lo) & (c.pct < hi)].result,
                                                              c[(c.pct >= lo) & (c.pct < hi)].odds)
                             for lo, hi in BUCKET_EDGES},
            "cons_spread": rec(cs.result, cs.odds),
            "cons_spread_75": rec(cs[cs.pct >= 75].result, cs[cs.pct >= 75].odds),
            "fade_spread_75": rec(cs[cs.pct >= 75].result.map({"win": "loss", "loss": "win", "push": "push"}),
                                  cs[cs.pct >= 75].opp_odds),
            "cons_spread_home": rec(cs[cs.side == "home"].result, cs[cs.side == "home"].odds),
            "cons_spread_away": rec(cs[cs.side == "away"].result, cs[cs.side == "away"].odds),
            "cons_spread_fav": rec(cs[cs.fav_dog == "favorite"].result, cs[cs.fav_dog == "favorite"].odds),
            "cons_spread_dog": rec(cs[cs.fav_dog == "underdog"].result, cs[cs.fav_dog == "underdog"].odds),
            "cons_under": rec(c[c.side == "under"].result, c[c.side == "under"].odds),
            "cons_over": rec(c[c.side == "over"].result, c[c.side == "over"].odds),
            "market_home_spread": rec(sub[(sub.market == "spread") & (sub.side == "home")].result,
                                      sub[(sub.market == "spread") & (sub.side == "home")].odds),
            "market_fav_spread": rec(sub[(sub.market == "spread") & (sub.fav_dog == "favorite")].result,
                                     sub[(sub.market == "spread") & (sub.fav_dog == "favorite")].odds),
            "market_over": rec(tm[tm.side == "over"].result, tm[tm.side == "over"].odds),
            "public_spread": rec(sub[(sub.market == "spread") & (sub.tickets_pct > 50)].result,
                                 sub[(sub.market == "spread") & (sub.tickets_pct > 50)].odds),
            "public_spread_heavy_fade": rec(sub[(sub.market == "spread") & (sub.tickets_pct <= 35)].result,
                                            sub[(sub.market == "spread") & (sub.tickets_pct <= 35)].odds),
            "public_total": rec(tm[tm.tickets_pct > 50].result, tm[tm.tickets_pct > 50].odds),
        }
        out[part] = block
    weekly = []
    for wk, sub in df.groupby("week"):
        c = consensus(sub)
        weekly.append({"week": int(wk), "games": int(sub.game_id.nunique()), "picks": weighted(sub),
                       "cons": rec(c.result, c.odds),
                       "cons_spread_75": rec(c[(c.market == "spread") & (c.pct >= 75)].result,
                                             c[(c.market == "spread") & (c.pct >= 75)].odds)})
    out["weekly"] = weekly
    return out


def main() -> None:
    args = sys.argv[1:]
    out_json = None
    if "--json" in args:
        i = args.index("--json")
        out_json = args[i + 1]
        args = args[:i] + args[i + 2:]
    reports = [report(lg) for lg in args]
    for r in reports:
        print(f"\n===== {r['league'].upper()} weeks {r['weeks'][0]}-{r['weeks'][-1]}, {r['games']} games =====")
        for part in ("ALL", "T2-6", "T7-CN"):
            b = r[part]
            print(f"[{part}] games={b['games']}")
            for k, v in b.items():
                if k == "games":
                    continue
                if k == "cons_buckets":
                    print("   cons buckets:", " | ".join(f"{kk}: {fmt(vv)}" for kk, vv in v.items()))
                else:
                    print(f"   {k:<26} {fmt(v)}")
        print("[weekly]")
        for w in r["weekly"]:
            print(f"   week {w['week']:>2}: games {w['games']:>3} | picks {fmt(w['picks'])} | cons {fmt(w['cons'])}"
                  f" | spread>=75 {fmt(w['cons_spread_75'])}")
    if out_json:
        Path(out_json).write_text(json.dumps(reports, indent=1), "utf-8")


if __name__ == "__main__":
    main()
