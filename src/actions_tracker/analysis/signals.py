"""Signals for the side being bet on the decision card: 🟢 helps, 🔴 hurts, ⚪ for information.

1. line movement (opening vs current DraftKings line via ESPN)      4. rest days / bye / short week
2. NFL key numbers 3 and 7                                         5. key-player injury status
3. form of the experts on the same side (30-day units at pick)     6. same-situation season rate (forecast)
7. public tickets vs money (Action Network public page)             8. same-share plays graded this ET week
9. same-share season history, kept separate from the live record       10. current playoff picture
The cover forecast (6) is listed first, and only when it is for the side being bet.
These are descriptive aids, not tested rules.
"""

import json

import pandas as pd

from actions_tracker.analysis.consensus import bucket_of
from actions_tracker.analysis.my_method import MIN_PICKS
from actions_tracker.config import FORM_UNITS, TZ

SIGNAL_COLS = ["game_id", "market", "side", "order", "tone", "text", "highlight"]
_OTHER = {"home": "away", "away": "home", "over": "under", "under": "over"}


def include_live_decisions(decisions: pd.DataFrame, in_play: pd.DataFrame) -> pd.DataFrame:
    """Keep calculating pregame signals after a selected play moves from upcoming to live."""
    base = decisions.copy() if decisions is not None else pd.DataFrame()
    if in_play is None or in_play.empty or not {"game_id", "market", "bet_side"}.issubset(in_play.columns):
        return base
    live = in_play.copy()
    if "source" in live.columns:
        live = live[live["source"] == "Cách của bạn"]
    live = live[["game_id", "market", "bet_side"]].drop_duplicates(["game_id", "market"])
    return pd.concat([base, live], ignore_index=True, sort=False).drop_duplicates(
        ["game_id", "market"], keep="first"
    )


def _fmt(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    return (f"+{x:g}" if x > 0 else f"{x:g}").replace(".", ",")


def _num(x) -> str:
    return f"{x:g}".replace(".", ",")


def _fc_side(f) -> str | None:
    """home / away for the team a forecast row bets ("PIT@CIN", pick "CIN" -> home)."""
    away, _, home = str(f.match).partition("@")
    return "home" if f.pick == home else "away" if f.pick == away else None


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


def _key_injuries(value) -> list[str]:
    if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
        return []
    try:
        data = json.loads(value) if isinstance(value, str) else value
        return [str(x) for x in data if x]
    except (TypeError, ValueError):
        return []


def _weekly_pick_record(play, method_plays: pd.DataFrame) -> tuple[str, str] | None:
    """Record before this play in its ET week and consensus-share bucket.

    The record is descriptive only: it never changes the selected side.
    """
    day_group = getattr(play, "day_group", None)
    if play is None or method_plays is None or method_plays.empty or day_group not in ("T2-6", "T7-CN"):
        return None
    votes = pd.to_numeric(getattr(play, "votes", None), errors="coerce")
    total = pd.to_numeric(getattr(play, "total_votes", None), errors="coerce")
    day = pd.to_datetime(getattr(play, "et_date", None), errors="coerce")
    if pd.isna(votes) or pd.isna(total) or total <= 0 or pd.isna(day):
        return None
    week_start = (day - pd.Timedelta(days=day.dayofweek)).strftime("%Y-%m-%d")
    bucket = bucket_of(100.0 * float(votes) / float(total))
    graded = method_plays[
        (method_plays["day_group"] == day_group)
        & method_plays["result"].isin(["win", "loss", "push"])
        & (method_plays["et_date"].astype(str) >= week_start)
        & (method_plays["et_date"].astype(str) <= str(play.et_date))
        & (method_plays["start_time"].astype(str) < str(play.start_time))
    ].copy()
    if graded.empty:
        return None
    shares = 100.0 * pd.to_numeric(graded["votes"], errors="coerce") / pd.to_numeric(
        graded["total_votes"], errors="coerce")
    graded = graded[[bucket_of(x) == bucket if pd.notna(x) else False for x in shares]]
    if graded.empty:
        return None
    wins = int((graded["result"] == "win").sum())
    losses = int((graded["result"] == "loss").sum())
    pushes = int((graded["result"] == "push").sum())
    tone = "🟢" if wins > losses else "🔴" if losses > wins else "⚪"
    push_text = f" · {pushes} hòa" if pushes else ""
    label = bucket.replace("-", "–")
    period = "Tuần này Mon–Fri" if day_group == "T2-6" else "Cuối tuần này Sat–Sun"
    return tone, (f"{period} · pick tương đương {label}%: {len(graded)} trận"
                  f" · {wins} thắng · {losses} thua{push_text}")


def _history_pick_record(play, history_plays: pd.DataFrame) -> tuple[str, str] | None:
    """Season record for this share bucket, never mixed with the live expert count.

    Weekdays follow the majority across the markets available in the NFL/NCAAF
    history.  Weekends use the user's method: spread only and fade the majority.
    """
    day_group = getattr(play, "day_group", None)
    if play is None or history_plays is None or history_plays.empty or day_group not in ("T2-6", "T7-CN"):
        return None
    if day_group == "T7-CN" and getattr(play, "market", None) != "spread":
        return None
    votes = pd.to_numeric(getattr(play, "votes", None), errors="coerce")
    total = pd.to_numeric(getattr(play, "total_votes", None), errors="coerce")
    if pd.isna(votes) or pd.isna(total) or total <= 0:
        return None
    bucket = bucket_of(100.0 * float(votes) / float(total))
    graded = history_plays[
        (history_plays["day_group"] == day_group)
        & history_plays["side_result"].isin(["win", "loss", "push"])
    ].copy()
    if day_group == "T7-CN":
        graded = graded[(graded["market"] == "spread")
                        & (pd.to_numeric(graded["total_votes"], errors="coerce") >= MIN_PICKS)]
    if graded.empty:
        return None
    if "bucket" in graded.columns:
        graded = graded[graded["bucket"] == bucket]
    else:
        shares = 100.0 * pd.to_numeric(graded["votes"], errors="coerce") / pd.to_numeric(
            graded["total_votes"], errors="coerce")
        graded = graded[[bucket_of(x) == bucket if pd.notna(x) else False for x in shares]]
    if graded.empty:
        return None
    results = graded["side_result"]
    if day_group == "T7-CN":
        results = results.map({"win": "loss", "loss": "win", "push": "push"})
    wins = int((results == "win").sum())
    losses = int((results == "loss").sum())
    pushes = int((results == "push").sum())
    tone = "🟢" if wins > losses else "🔴" if losses > wins else "⚪"
    push_text = f" · {pushes} hòa" if pushes else ""
    label = bucket.replace("-", "–")
    period = "Mon–Fri · follow" if day_group == "T2-6" else "Sat–Sun · fade spread"
    return tone, (f"Lịch sử mùa NFL/NCAAF ({period}, pick_count) · {label}%: {len(graded)} trận"
                  f" · {wins} thắng · {losses} thua{push_text}")


def _playoff_label(row) -> str:
    if row is None:
        return "–"
    rank = pd.to_numeric(getattr(row, "rank", None), errors="coerce")
    seed = pd.to_numeric(getattr(row, "seed", None), errors="coerce")
    place = f"CFP #{int(rank)}" if pd.notna(rank) else f"seed #{int(seed)}" if pd.notna(seed) else "ngoài field"
    probability = pd.to_numeric(getattr(row, "playoff_prob", None), errors="coerce")
    chance = f" · {probability * 100:.0f}%" if pd.notna(probability) else ""
    return f"{getattr(row, 'abbr', '–')} {getattr(row, 'record', '–')} · {place}{chance}"


def _playoff_signal(game_id: int, market: str, side: str, rows: dict) -> tuple[str, str] | None:
    mine, opponent = rows.get((game_id, side)), rows.get((game_id, _OTHER[side]))
    if mine is None or opponent is None:
        return None
    tone = "⚪"
    if market in ("spread", "ml"):
        mine_p = pd.to_numeric(getattr(mine, "playoff_prob", None), errors="coerce")
        opp_p = pd.to_numeric(getattr(opponent, "playoff_prob", None), errors="coerce")
        if pd.notna(mine_p) and pd.notna(opp_p) and abs(mine_p - opp_p) >= .15:
            tone = "🟢" if mine_p > opp_p else "🔴"
        elif getattr(mine, "picture", None) != getattr(opponent, "picture", None):
            strength = {"field": 2, "bubble": 1, "outside": 0}
            difference = strength.get(getattr(mine, "picture", None), 0) - strength.get(
                getattr(opponent, "picture", None), 0)
            tone = "🟢" if difference > 0 else "🔴" if difference < 0 else "⚪"
    return tone, f"PLAYOFF NÓNG · Đội bạn {_playoff_label(mine)} | Đối thủ {_playoff_label(opponent)}"


def _day_group(game, play) -> str | None:
    group = getattr(play, "day_group", None) if play is not None else None
    if group in ("T2-6", "T7-CN"):
        return group
    start = pd.to_datetime(getattr(game, "start_time", None), utc=True, errors="coerce")
    if pd.isna(start):
        return None
    return "T2-6" if start.tz_convert(TZ).dayofweek <= 4 else "T7-CN"


def _form_rate(history: pd.DataFrame | None, league: str, market: str, group: str,
               dim: str, bucket: str) -> tuple[float, int] | None:
    if history is None or history.empty:
        return None
    rows = history[(history["league"] == league) & (history["market"] == market)
                   & (history["day_group"] == group) & (history["dim"] == dim)
                   & (history["bucket"] == bucket)]
    if rows.empty:
        return None
    row = rows.iloc[0]
    rate = pd.to_numeric(row.get("win_pct"), errors="coerce")
    count = pd.to_numeric(row.get("n"), errors="coerce")
    return (float(rate), int(count)) if pd.notna(rate) and pd.notna(count) else None


def _expert_day_signals(experts: pd.DataFrame, game, play, market: str,
                        history: pd.DataFrame | None) -> list[tuple[str, str]]:
    """Special form cues requested for weekdays and weekends.

    Mon–Fri: an expert currently losing more than three straight.
    Sat–Sun: an expert whose 30-day league record is at least +3 units.
    """
    group = _day_group(game, play)
    if experts.empty or group is None:
        return []
    league = str(getattr(game, "league", ""))
    found = []
    for e in experts.itertuples():
        name = str(getattr(e, "expert_name", "") or f"Expert {getattr(e, 'expert_id', '')}")
        if group == "T2-6" and getattr(e, "streak_type", None) == "cold" \
                and pd.to_numeric(getattr(e, "streak_value", None), errors="coerce") > 3:
            rate = _form_rate(history, league, market, group, "streak", "cold_long")
            stats = f" · lịch sử {rate[0] * 100:.1f}% (n={rate[1]})" if rate else ""
            tone = "🟢" if rate and rate[0] >= .5238 else "⚪"
            found.append((tone, f"EXPERT THEO NGÀY · {name} đang thua {int(e.streak_value)} liên tiếp{stats}"))
        elif group == "T7-CN" and pd.to_numeric(getattr(e, "units_30", None), errors="coerce") >= FORM_UNITS:
            rate = _form_rate(history, league, market, group, "units_30", "hot")
            stats = f" · lịch sử {rate[0] * 100:.1f}% (n={rate[1]})" if rate else ""
            tone = "🟢" if rate and rate[0] >= .5238 else "⚪"
            found.append((tone, f"EXPERT THEO NGÀY · {name} cuối tuần đang xanh {float(e.units_30):+.1f}u{stats}"))
    return found


def _green_consensus_signal(play, history: pd.DataFrame | None) -> tuple[str, str] | None:
    """Highlight a profitable majority bucket only when this play follows that majority."""
    if play is None or history is None or history.empty or getattr(play, "method", None) != "follow":
        return None
    votes = pd.to_numeric(getattr(play, "votes", None), errors="coerce")
    total = pd.to_numeric(getattr(play, "total_votes", None), errors="coerce")
    if pd.isna(votes) or pd.isna(total) or total <= 0:
        return None
    bucket = bucket_of(100.0 * float(votes) / float(total))
    rows = history[(history["league"] == getattr(play, "league", None))
                   & (history["market"] == getattr(play, "market", None))
                   & (history["bucket"] == bucket)]
    if rows.empty:
        return None
    r = rows.iloc[0]
    roi = pd.to_numeric(r.get("roi"), errors="coerce")
    rate = pd.to_numeric(r.get("win_pct"), errors="coerce")
    wins, losses = int(r.get("wins") or 0), int(r.get("losses") or 0)
    if pd.isna(roi) or pd.isna(rate) or roi <= 0 or bool(r.get("low_sample", False)):
        return None
    label = bucket.replace("-", "–")
    return "🟢", (f"ĐÁM ĐÔNG ĐANG XANH · {label}% expert cùng phía · {wins}-{losses}"
                  f" · Win {rate * 100:.1f}% · ROI {roi * 100:+.1f}%")


def signals(decisions: pd.DataFrame, games: pd.DataFrame, current: pd.DataFrame, opening: pd.DataFrame,
            context: pd.DataFrame, public: pd.DataFrame, expert_sides: pd.DataFrame,
            forecast: pd.DataFrame, method_plays: pd.DataFrame | None = None,
            history_plays: pd.DataFrame | None = None, playoff: pd.DataFrame | None = None,
            expert_form_history: pd.DataFrame | None = None,
            consensus_history: pd.DataFrame | None = None) -> pd.DataFrame:
    if decisions is None or decisions.empty:
        return pd.DataFrame(columns=SIGNAL_COLS)
    g_by = {int(r.id): r for r in games.itertuples()} if len(games) else {}
    cur = {(int(r.game_id), r.market, r.side): r.line for r in current.itertuples()} if len(current) else {}
    opn = {(int(r.game_id), r.market, r.side): r.line for r in opening.itertuples()} if len(opening) else {}
    ctx = {int(r.game_id): r for r in context.itertuples()} if len(context) else {}
    pub = {(int(r.game_id), r.market, r.side): r for r in public.itertuples()} if len(public) else {}
    fc = {int(r.game_id): r for r in forecast.itertuples()} if forecast is not None and len(forecast) else {}
    method = {(int(r.game_id), r.market): r for r in method_plays.itertuples()} \
        if method_plays is not None and len(method_plays) else {}
    playoff_rows = {(int(r.game_id), r.side): r for r in playoff.itertuples()} \
        if playoff is not None and len(playoff) else {}
    rows = []
    for d in decisions.drop_duplicates(["game_id", "market"]).itertuples():
        gid, market, side = int(d.game_id), d.market, getattr(d, "bet_side", None)
        if market not in ("spread", "total", "ml") or side not in _OTHER:
            continue
        game = g_by.get(gid)
        out = []
        play = method.get((gid, market))
        consensus_signal = _green_consensus_signal(play, consensus_history)
        if consensus_signal:
            out.append(consensus_signal)
        # 6. same situation over the season (user's method plays only): the cover forecast, shown first
        f = fc.get(gid)
        if market == "spread" and f is not None and _fc_side(f) == side:
            line = "" if f.line is None or pd.isna(f.line) else " " + _fmt(f.line)
            out.append(("⚪", f"Dự báo cover {f.pick}{line}: {f.p_win * 100:.0f}% ({int(f.basis_n)} kèo tương tự)"
                              " — chưa kiểm chứng"))
        weekly = _weekly_pick_record(play, method_plays)
        if weekly:
            out.append(weekly)
        history = _history_pick_record(play, history_plays)
        if history:
            out.append(history)
        playoff_signal = _playoff_signal(gid, market, side, playoff_rows)
        if playoff_signal:
            out.append(playoff_signal)
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
        # 4-5. rest and key players (team sides only)
        x = ctx.get(gid)
        if market in ("spread", "ml") and x is not None:
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
                    label = "QB chính đội bạn" if who == side else "QB chính đối thủ"
                    out.append((tone_out if sure else "⚪", f"CẦU THỦ CHỦ CHỐT · {label}: {qb}"))
                for injury in _key_injuries(getattr(x, f"{who}_key_injuries", None)):
                    sure = any(s in injury for s in (", Out)", ", Doubtful)"))
                    label = "đội bạn" if who == side else "đối thủ"
                    out.append((tone_out if sure else "⚪", f"CẦU THỦ CHỦ CHỐT · {label}: {injury}"))
        elif market == "total" and x is not None:
            for who in ("away", "home"):
                team = getattr(game, f"{who}_abbr", who.upper()) if game is not None else who.upper()
                qb = getattr(x, f"{who}_qb")
                if qb and not pd.isna(qb):
                    out.append(("⚪", f"CẦU THỦ CHỦ CHỐT · {team}: QB chính {qb}"))
                for injury in _key_injuries(getattr(x, f"{who}_key_injuries", None)):
                    out.append(("⚪", f"CẦU THỦ CHỦ CHỐT · {team}: {injury}"))
        # 3. experts on the same side
        es = expert_sides[(expert_sides["game_id"] == gid) & (expert_sides["market"] == market)] if len(expert_sides) else expert_sides
        if len(es):
            mine_e = es[es["side"] == side]
            out.extend(_expert_day_signals(mine_e, game, play, market,
                                           expert_form_history))
            hot = int((mine_e["units_30"] >= 3).sum())
            cold = int((mine_e["units_30"] <= -3).sum())
            if len(mine_e):
                out.append(("⚪", f"Expert cùng bên bạn: {len(mine_e)} người · {hot} đang lời, {cold} đang lỗ (30 ngày)"))
        # 7. public tickets vs money
        p = pub.get((gid, market, side))
        if p is not None and not pd.isna(p.tickets_pct) and not pd.isna(p.money_pct):
            gap = p.money_pct - p.tickets_pct
            tone = "🟢" if gap >= 10 else "🔴" if gap <= -10 else "⚪"
            what = "tiền lớn nghiêng về bạn" if gap >= 10 else "tiền lớn ở bên kia" if gap <= -10 else "public"
            out.append((tone, f"{what[0].upper() + what[1:]}: vé {p.tickets_pct:g}% · tiền {p.money_pct:g}%"))
        rows += [{"game_id": gid, "market": market, "side": side, "order": i, "tone": t, "text": s,
                  "highlight": s.startswith(("CẦU THỦ CHỦ CHỐT", "PLAYOFF NÓNG", "EXPERT THEO NGÀY",
                                             "ĐÁM ĐÔNG ĐANG XANH"))}
                 for i, (t, s) in enumerate(out)]
    return pd.DataFrame(rows, columns=SIGNAL_COLS)


def expert_sides(picks: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Latest pre-game pick per expert x game x market with the expert's 30-day units when the pick was made."""
    cols = ["game_id", "market", "side", "expert_id", "expert_name", "units_30", "streak_type", "streak_value"]
    if picks.empty:
        return pd.DataFrame(columns=cols)
    p = picks.copy()
    if "start_time" in p and "created_at" in p:
        p = p[p["created_at"].astype(str) < p["start_time"].astype(str)]
    p = p.sort_values("created_at", kind="stable").drop_duplicates(["game_id", "market", "expert_id"], keep="last")
    form_by = forms.set_index("pick_id") if len(forms) else pd.DataFrame()
    key = "pick_id" if "pick_id" in p.columns else "id"
    p["units_30"] = [form_by.at[i, "units_30"] if i in form_by.index else None for i in p[key]]
    p["streak_type"] = [form_by.at[i, "streak_type"] if i in form_by.index else None for i in p[key]]
    p["streak_value"] = [form_by.at[i, "streak_value"] if i in form_by.index else None for i in p[key]]
    p["units_30"] = pd.to_numeric(p["units_30"], errors="coerce")
    if "expert_name" not in p:
        p["expert_name"] = ""
    return p.rename(columns={"pick_side": "side"})[cols]
