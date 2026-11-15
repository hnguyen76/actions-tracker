"""Signals for the side being bet on the decision card: 🟢 helps, 🔴 hurts, ⚪ for information.

1. line movement (opening vs current DraftKings line via ESPN)      4. rest days / bye / short week
2. NFL key numbers 3 and 7                                         5. quarterback injury status
3. form of the experts on the same side (30-day units at pick)     6. same-situation season rate (forecast)
7. public tickets vs money (Action Network public page)
These are descriptive aids, not tested rules.
"""

import pandas as pd

SIGNAL_COLS = ["game_id", "market", "side", "order", "tone", "text"]
_OTHER = {"home": "away", "away": "home", "over": "under", "under": "over"}


def _fmt(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    return (f"+{x:g}" if x > 0 else f"{x:g}").replace(".", ",")


def _num(x) -> str:
    return f"{x:g}".replace(".", ",")


def _key_number(line) -> tuple[str, str] | None:
    if line is None or pd.isna(line):
        return None
    a = abs(float(line))
    if a in (3.0, 7.0):
        return "⚪", f"Đúng số then chốt {a:g} — dễ hòa (push)"
    if line > 0 and a in (3.5, 7.5):
        return "🟢", f"Nhận {_fmt(line)}: qua được số then chốt {a - 0.5:g}"
    if line > 0 and a in (2.5, 6.5):
        return "🔴", f"Nhận {_fmt(line)}: thiếu nửa điểm so với số then chốt {a + 0.5:g}"
    if line < 0 and a in (2.5, 6.5):
        return "🟢", f"Chấp {_fmt(line)}: dưới số then chốt {a + 0.5:g}"
    if line < 0 and a in (3.5, 7.5):
        return "🔴", f"Chấp {_fmt(line)}: phải thắng qua số then chốt {a - 0.5:g}"
    return None


def signals(decisions: pd.DataFrame, games: pd.DataFrame, current: pd.DataFrame, opening: pd.DataFrame,
            context: pd.DataFrame, public: pd.DataFrame, expert_sides: pd.DataFrame,
            forecast: pd.DataFrame) -> pd.DataFrame:
    if decisions is None or decisions.empty:
        return pd.DataFrame(columns=SIGNAL_COLS)
    g_by = {int(r.id): r for r in games.itertuples()} if len(games) else {}
    cur = {(int(r.game_id), r.market, r.side): r.line for r in current.itertuples()} if len(current) else {}
    opn = {(int(r.game_id), r.market, r.side): r.line for r in opening.itertuples()} if len(opening) else {}
    ctx = {int(r.game_id): r for r in context.itertuples()} if len(context) else {}
    pub = {(int(r.game_id), r.market, r.side): r for r in public.itertuples()} if len(public) else {}
    fc = {int(r.game_id): r for r in forecast.itertuples()} if forecast is not None and len(forecast) else {}
    rows = []
    for d in decisions.drop_duplicates(["game_id", "market"]).itertuples():
        gid, market, side = int(d.game_id), d.market, getattr(d, "bet_side", None)
        if market not in ("spread", "total") or side not in _OTHER:
            continue
        game = g_by.get(gid)
        out = []
        # 1. line movement
        o, c = opn.get((gid, market, side)), cur.get((gid, market, side))
        if o is not None and c is not None and not pd.isna(o) and not pd.isna(c) and abs(c - o) >= 0.5:
            toward = (c < o) if market == "spread" else (c > o if side == "over" else c < o)
            out.append(("🟢" if toward else "🔴",
                        f"Line {'chạy về phía bạn' if toward else 'chạy ngược bạn'}: mở {_fmt(o) if market == 'spread' else _num(o)}"
                        f" → nay {_fmt(c) if market == 'spread' else _num(c)}"))
        # 2. key numbers (NFL spread)
        if market == "spread" and game is not None and game.league == "nfl":
            k = _key_number(c)
            if k:
                out.append(k)
        # 4-5. rest and quarterbacks (team sides only)
        x = ctx.get(gid)
        if market == "spread" and x is not None:
            mine, theirs = getattr(x, f"{side}_rest_days"), getattr(x, f"{_OTHER[side]}_rest_days")
            if mine is not None and theirs is not None and not pd.isna(mine) and not pd.isna(theirs):
                if mine >= 12 and theirs < 12:
                    out.append(("🟢", f"Đội bạn sau tuần nghỉ ({mine:.0f} ngày, đối thủ {theirs:.0f})"))
                elif theirs >= 12 and mine < 12:
                    out.append(("🔴", f"Đối thủ sau tuần nghỉ ({theirs:.0f} ngày, đội bạn {mine:.0f})"))
                elif mine - theirs >= 3:
                    out.append(("🟢", f"Đội bạn nghỉ nhiều hơn: {mine:.0f} so với {theirs:.0f} ngày"))
                elif theirs - mine >= 3:
                    out.append(("🔴", f"Đội bạn nghỉ ít hơn: {mine:.0f} so với {theirs:.0f} ngày"))
            for who, tone_out in ((side, "🔴"), (_OTHER[side], "🟢")):
                qb = getattr(x, f"{who}_qb")
                if qb and not pd.isna(qb):
                    sure = any(s in qb for s in ("(Out)", "(Doubtful)"))
                    label = "QB đội bạn" if who == side else "QB đối thủ"
                    out.append((tone_out if sure else "⚪", f"{label}: {qb}"))
        # 3. experts on the same side
        es = expert_sides[(expert_sides["game_id"] == gid) & (expert_sides["market"] == market)] if len(expert_sides) else expert_sides
        if len(es):
            mine_e = es[es["side"] == side]
            hot = int((mine_e["units_30"] >= 3).sum())
            cold = int((mine_e["units_30"] <= -3).sum())
            if len(mine_e):
                out.append(("⚪", f"Expert cùng bên bạn: {len(mine_e)} người · {hot} đang lời, {cold} đang lỗ (30 ngày)"))
        # 6. same situation over the season (user's method plays only)
        f = fc.get(gid)
        if market == "spread" and f is not None:
            out.append(("⚪", f"Tình huống tương tự cả mùa: {f.p_win * 100:.0f}% ({int(f.basis_n)} kèo) — chưa kiểm chứng"))
        # 7. public tickets vs money
        p = pub.get((gid, market, side))
        if p is not None and not pd.isna(p.tickets_pct) and not pd.isna(p.money_pct):
            gap = p.money_pct - p.tickets_pct
            tone = "🟢" if gap >= 10 else "🔴" if gap <= -10 else "⚪"
            what = "tiền lớn nghiêng về bạn" if gap >= 10 else "tiền lớn ở bên kia" if gap <= -10 else "public"
            out.append((tone, f"{what[0].upper() + what[1:]}: vé {p.tickets_pct:g}% · tiền {p.money_pct:g}%"))
        rows += [{"game_id": gid, "market": market, "side": side, "order": i, "tone": t, "text": s}
                 for i, (t, s) in enumerate(out)]
    return pd.DataFrame(rows, columns=SIGNAL_COLS)


def expert_sides(picks: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Latest pre-game pick per expert x game x market with the expert's 30-day units when the pick was made."""
    cols = ["game_id", "market", "side", "units_30"]
    if picks.empty:
        return pd.DataFrame(columns=cols)
    p = picks.copy()
    if "start_time" in p and "created_at" in p:
        p = p[p["created_at"].astype(str) < p["start_time"].astype(str)]
    p = p.sort_values("created_at", kind="stable").drop_duplicates(["game_id", "market", "expert_id"], keep="last")
    units = dict(zip(forms["pick_id"], forms["units_30"])) if len(forms) else {}
    key = "pick_id" if "pick_id" in p.columns else "id"
    p["units_30"] = [units.get(i) for i in p[key]]
    p["units_30"] = pd.to_numeric(p["units_30"], errors="coerce")
    return p.rename(columns={"pick_side": "side"})[cols]
