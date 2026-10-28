"""Deterministic trade-setup detectors: TREND (pullback continuation) and RANGE (edge fade).

Both work on COMPLETED candles only and return a plain dict describing the setup, or a
rejection reason. Confidence is a 0-100 *setup-quality* score from independent factors
(NOT a win probability - see store.stats() for the empirical hit-rate per bucket).
"""
import numpy as np

from . import indicators as ind


def _clip(x, lo=0.0, hi=1.0):
    return float(min(hi, max(lo, x)))


def _f(name, ok, pts, mx, note=""):
    return {"name": name, "ok": bool(ok), "pts": round(float(pts), 1), "max": mx, "note": note}


def _bar_quality(o, h, l, c, prev_h, side):
    """Trigger-candle quality 0..1 and validity for `side` (+1 long / -1 short)."""
    if side < 0:
        o, c, h, l, prev_h = -o, -c, -l, -h, -prev_h  # mirror so the long logic applies; prev_h = prev low mirrored
    rng = h - l
    if rng <= 0:
        return 0.0, False
    body = (c - o) / rng
    loc = (c - l) / rng
    wick = (min(o, c) - l) / rng
    brk = c > prev_h
    q = 0.4 * _clip(body / 0.6) + 0.3 * _clip((loc - 0.5) / 0.4) + 0.3 * (1.0 if brk else 0.5 * _clip(wick / 0.5))
    return q, bool(c > o and loc >= 0.6 and (brk or wick >= 0.35))


def htf_alignment(R, side):
    """Fraction 0..1 of agreement with `side` (+1/-1) and a hard-block flag if the TF trends against it."""
    if not R or R.get("regime") in (None, "UNKNOWN"):
        return 0.0, False, "n/a"
    reg, st = R["regime"], R.get("structure", "RANGE")
    want = "UP" if side > 0 else "DOWN"
    if reg.startswith("TRENDING"):
        return (1.0, False, reg) if reg.endswith(want) else (0.0, True, reg + " (against)")
    want_s = "BULLISH" if side > 0 else "BEARISH"
    if st == want_s:
        return 0.5, False, f"{reg}, structure {st}"
    if st == "RANGE":
        return 0.35, False, f"{reg}, structure range"
    return 0.0, False, f"{reg}, structure {st} (against)"


def _nearest_obstacle(ctx, side, entry, atr, min_gap):
    """Nearest swing level beyond `entry` in trade direction (exec + confirm TF pivots + 50-bar extreme)."""
    lv = []
    for key in ("exec", "conf"):
        R = ctx["regimes"].get(key) or {}
        for p in R.get("pivots", []):
            if side > 0 and p["type"] == "H" and p["p"] > entry + min_gap:
                lv.append(p["p"])
            if side < 0 and p["type"] == "L" and p["p"] < entry - min_gap:
                lv.append(p["p"])
    d = ctx["frames"]["exec"]
    ext = float(d["high"].tail(50).max()) if side > 0 else float(d["low"].tail(50).min())
    if (side > 0 and ext > entry + min_gap) or (side < 0 and ext < entry - min_gap):
        lv.append(ext)
    if not lv:
        return None
    return min(lv) if side > 0 else max(lv)


def _net_rr(entry, sl, tp, cost):
    risk, reward = abs(entry - sl), abs(tp - entry)
    return (reward - cost) / (risk + cost) if risk + cost > 0 else 0.0


# ============================================================================ TREND
def trend_setup(ctx):
    cfg, d, R = ctx["cfg"], ctx["frames"]["exec"], ctx["regimes"]["exec"]
    if not R["regime"].startswith("TRENDING"):
        return None, f"regime is {R['regime']}"
    side = 1 if R["direction"] == "UP" else -1
    n, atr = len(d), float(d["atr"].iloc[-1])
    last, prev = d.iloc[-1], d.iloc[-2]
    sp = ctx["spread"]
    cost = sp + cfg["est_cost"]

    a1, block1, lab1 = htf_alignment(ctx["regimes"].get("conf"), side)
    a2, block2, lab2 = htf_alignment(ctx["regimes"].get("ctx"), side)
    if block1 or block2:
        return None, f"higher timeframe opposes ({'confirm' if block1 else 'context'}: {lab1 if block1 else lab2})"

    s = side
    hi, lo = (d["high"], d["low"]) if s > 0 else (-d["low"], -d["high"])
    cl, e20, e50 = s * d["close"], s * d["ema20"], s * d["ema50"]
    seg = slice(n - 6, n)
    k_pb = int(np.argmin(lo.values[seg])) + (n - 6)
    pb_lo = float(lo.iloc[k_pb])
    imp_hi = float(hi.tail(25).max())
    depth = (imp_hi - pb_lo) / atr
    touched = float((lo.iloc[seg] - e20.iloc[seg]).min()) <= 0.15 * atr
    unbroken = pb_lo >= float(e50.iloc[k_pb]) - 0.6 * atr
    above = float(cl.iloc[-1]) > float(e20.iloc[-1])
    chase = (float(cl.iloc[-1]) - float(e20.iloc[-1])) / atr
    q, trig_ok = _bar_quality(last["open"], last["high"], last["low"], last["close"],
                              prev["high"] if s > 0 else prev["low"], s)
    why = []
    if not (0.7 <= depth <= 3.5):
        why.append(f"pullback depth {depth:.1f} ATR outside 0.7-3.5")
    if not touched:
        why.append("price did not pull back to the EMA20 value zone")
    if not unbroken:
        why.append("pullback broke through EMA50 (trend damaged)")
    if not above:
        why.append("close not back on trend side of EMA20")
    if chase > 1.5:
        why.append(f"extended {chase:.1f} ATR from EMA20 (chasing)")
    if not trig_ok:
        why.append("no valid trigger candle on the last close")
    if why:
        return None, "; ".join(why)

    entry = float(last["close"])
    stop_px = (pb_lo - 0.25 * atr)               # in transformed coords
    risk = s * entry - stop_px
    note_stop = "structural (below pullback low)"
    if risk < 0.8 * atr:
        risk, note_stop = 0.8 * atr, "widened to 0.8 ATR minimum"
    if risk > 2.5 * atr:
        return None, f"stop distance {risk / atr:.1f} ATR > 2.5 ATR (poor risk geometry)"
    if risk < cfg["min_stop_spread_mult"] * sp:
        return None, f"stop {risk:.2f} too small vs spread {sp:.2f}"
    sl = entry - s * risk
    obs = _nearest_obstacle(ctx, s, entry, atr, 0.3 * atr)
    tp1 = entry + s * 1.5 * risk
    if obs is not None:
        room = abs(obs - entry) / risk
        if room < cfg["min_rr_trend"]:
            return None, f"next structure {obs:.2f} only {room:.1f}R away (< {cfg['min_rr_trend']}R)"
        tp2 = obs - s * 0.1 * atr
        tp2 = entry + s * min(abs(tp2 - entry), 3.0 * risk)
    else:
        tp2 = entry + s * 2.5 * risk
    rr = abs(tp2 - entry) / risk
    net = _net_rr(entry, sl, tp2, cost)

    # ---- confidence
    mx = {"regime": 20, "h1": 12, "h4": 8, "pullback": 15, "trigger": 10, "rr": 15, "vol": 5, "session": 5, "macro": 5, "cost": 5}
    tp_pts = R["trend_pts"]
    pb_q = 0.5 * _clip(1 - abs(depth - 1.5) / 1.5) + 0.5 * (1.0 if abs(float((lo.iloc[k_pb] - e20.iloc[k_pb]) / atr)) < 0.5 else 0.5)
    macro = ctx.get("macro", "UNVERIFIED")
    macro_ok = (macro == "BULLISH" and s > 0) or (macro == "BEARISH" and s < 0)
    macro_pts = 5 if macro_ok else 2.5 if macro in ("NEUTRAL", "UNVERIFIED", "OFF") else 0
    cost_ratio = cost / risk
    F = [
        _f("Trend regime strength", tp_pts >= 70, mx["regime"] * _clip(tp_pts / 100), mx["regime"], f"{tp_pts:.0f} trend pts"),
        _f("H1 alignment", a1 >= 0.5, mx["h1"] * a1, mx["h1"], lab1),
        _f("H4 alignment", a2 >= 0.5, mx["h4"] * a2, mx["h4"], lab2),
        _f("Pullback to EMA zone", pb_q >= 0.6, mx["pullback"] * pb_q, mx["pullback"], f"depth {depth:.1f} ATR"),
        _f("Trigger candle", q >= 0.6, mx["trigger"] * q, mx["trigger"], f"quality {q:.2f}"),
        _f("Room to target / R:R", rr >= 2.5, mx["rr"] * _clip((rr - 1.5) / 1.5), mx["rr"], f"{rr:.1f}R to TP2"),
        _f("Volatility normal", 0.8 <= R["atr_ratio"] <= 1.3, mx["vol"] * (1 if 0.8 <= R["atr_ratio"] <= 1.3 else 0.5), mx["vol"], f"ATR x{R['atr_ratio']:.2f}"),
        _f("Preferred session", ctx["in_window"], mx["session"] if ctx["in_window"] else 0, mx["session"], "London/NY overlap" if ctx["in_window"] else "outside window"),
        _f("Macro aligned", macro_ok, macro_pts, mx["macro"], f"macro {macro}"),
        _f("Cost efficiency", cost_ratio <= 0.08, mx["cost"] * _clip(1 - (cost_ratio - 0.04) / 0.08), mx["cost"], f"cost {cost_ratio * 100:.0f}% of risk"),
    ]
    conf = sum(f["pts"] for f in F)
    sd = "LONG" if s > 0 else "SHORT"
    reasons = [f"{R['regime'].replace('_', ' ')} confirmed (ADX {R['adx']:.0f}, ER {R['er']:.2f})",
               f"H1: {lab1}; H4: {lab2}",
               f"Pullback of {depth:.1f} ATR into EMA20 zone, then {'bullish' if s > 0 else 'bearish'} trigger candle (q={q:.2f})",
               f"Stop {note_stop}; TP2 {'at next structure' if obs is not None else '2.5R projection'}"]
    return {"type": "TREND", "side": sd, "state": "TRIGGERED", "entry": entry, "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2),
            "rr": round(rr, 2), "net_rr": round(net, 2), "risk": round(risk, 2), "confidence": round(conf, 1),
            "confluence": {"count": sum(f["ok"] for f in F), "total": len(F), "factors": F}, "reasons": reasons,
            "anchor": s * pb_lo, "atr": atr, "expiry_bars": cfg["trend_expiry_bars"]}, None


# ============================================================================ RANGE
def _cluster(pts, tol):
    """Best cluster of pivot prices within `tol`: most members, then most recent. pts: list of (i, price)."""
    best = None
    for a in pts:
        mem = [p for p in pts if abs(p[1] - a[1]) <= tol]
        key = (len(mem), max(m[0] for m in mem))
        if best is None or key > best[0]:
            best = (key, mem)
    return best[1] if best else []


def range_box(ctx):
    """Find the active range box. Returns (box|None, reason)."""
    cfg, d, R = ctx["cfg"], ctx["frames"]["exec"], ctx["regimes"]["exec"]
    n, N = len(d), cfg["range_lookback"]
    atr = float(d["atr"].iloc[-1])
    piv = [p for p in R.get("pivots", []) if p["i"] >= n - N]
    hs = [(p["i"], p["p"]) for p in piv if p["type"] == "H"]
    ls = [(p["i"], p["p"]) for p in piv if p["type"] == "L"]
    ch, cl = _cluster(hs, 0.45 * atr), _cluster(ls, 0.45 * atr)
    if len(ch) < 2 or len(cl) < 2:
        return None, f"no repeated tests of a ceiling/floor (resistance touches {len(ch)}, support touches {len(cl)}; need 2+2)"
    res, sup = float(np.mean([p[1] for p in ch])), float(np.mean([p[1] for p in cl]))
    res_ext, sup_ext = max(p[1] for p in ch), min(p[1] for p in cl)
    width = res - sup
    if width <= 0:
        return None, "inverted box"
    wa = width / atr
    if not (cfg["range_min_width_atr"] <= wa <= cfg["range_max_width_atr"]):
        return None, f"box width {wa:.1f} ATR outside {cfg['range_min_width_atr']}-{cfg['range_max_width_atr']}"
    first = min(p[0] for p in ch + cl)
    span = n - 1 - first
    if span < 20:
        return None, f"box only {span} bars old (need 20+)"
    w = d.iloc[first:]
    inside = float(((w["close"] >= sup - 0.3 * atr) & (w["close"] <= res + 0.3 * atr)).mean())
    if inside < 0.85:
        return None, f"only {inside * 100:.0f}% of closes inside the box (need 85%+)"
    last3 = d["close"].tail(3)
    if (last3 > res + 0.5 * atr).any() or (last3 < sup - 0.5 * atr).any():
        return None, "price closed outside the box (breakout) - range invalidated"
    last_touch = max(p[0] for p in ch + cl)
    return {"res": res, "sup": sup, "res_ext": res_ext, "sup_ext": sup_ext, "width": width, "width_atr": wa, "mid": (res + sup) / 2,
            "t_res": len(ch), "t_sup": len(cl), "inside": inside, "span": span, "since_touch": n - 1 - last_touch, "atr": atr}, None


def _plan(box, side, entry, cfg, sp, atr, bar_extreme=None):
    """SL/TP for fading `side` (+1 buy at support, -1 sell at resistance) from `entry`."""
    buf = max(0.5 * atr, 2 * sp)
    if side > 0:
        ext = box["sup_ext"] if bar_extreme is None else min(box["sup_ext"], bar_extreme)
        sl, tp1, tp2 = ext - buf, box["mid"], box["res"] - 0.25 * atr
    else:
        ext = box["res_ext"] if bar_extreme is None else max(box["res_ext"], bar_extreme)
        sl, tp1, tp2 = ext + buf, box["mid"], box["sup"] + 0.25 * atr
    risk = abs(entry - sl)
    rr1, rr2 = abs(tp1 - entry) / risk, abs(tp2 - entry) / risk
    return {"entry": float(entry), "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2), "risk": float(risk),
            "rr1": round(rr1, 2), "rr2": round(rr2, 2)}


def range_setup(ctx):
    cfg, d, R = ctx["cfg"], ctx["frames"]["exec"], ctx["regimes"]["exec"]
    if R["regime"] != "RANGING":
        return None, f"regime is {R['regime']}"
    box, why = range_box(ctx)
    if box is None:
        return None, why
    atr, sp = box["atr"], ctx["spread"]
    cost = sp + cfg["est_cost"]
    if box["width"] < 8 * sp:
        return None, f"box width {box['width']:.2f} too small vs spread {sp:.2f}"
    last, prev = d.iloc[-1], d.iloc[-2]
    close, w = float(last["close"]), box["width"]
    zb = (box["sup"] - 0.35 * atr, box["sup"] + 0.22 * w)      # buy zone
    zs = (box["res"] - 0.22 * w, box["res"] + 0.35 * atr)      # sell zone
    in_buy, in_sell = zb[0] <= close <= zb[1], zs[0] <= close <= zs[1]
    buy_plan = _plan(box, +1, box["sup"] + 0.10 * w, cfg, sp, atr)
    sell_plan = _plan(box, -1, box["res"] - 0.10 * w, cfg, sp, atr)

    out = {"box": box, "zones": {"buy": zb, "sell": zs}, "plans": {"BUY": buy_plan, "SELL": sell_plan}, "atr": atr}
    side = 1 if in_buy else -1 if in_sell else 0
    sidestr = {1: "BUY", -1: "SELL", 0: None}[side]

    # ---- box-level factors (always scored)
    # HTF for ranges: only need "not trending against the fade" (side 0 = armed box: not trending at all)
    def htf_ok(side_):
        r1 = ctx["regimes"].get("conf") or {}
        r2 = ctx["regimes"].get("ctx") or {}
        if side_ == 0:
            bad1 = r1.get("regime", "").startswith("TRENDING")
            bad2 = r2.get("regime", "").startswith("TRENDING") and r2.get("trend_pts", 0) >= 75
        else:
            against = "DOWN" if side_ > 0 else "UP"
            bad1 = r1.get("regime", "").startswith("TRENDING") and r1["regime"].endswith(against)
            bad2 = r2.get("regime", "").startswith("TRENDING") and r2["regime"].endswith(against) and r2.get("trend_pts", 0) >= 75
        return (not bad1, not bad2, r1.get("regime", "n/a"), r2.get("regime", "n/a"))

    bbp = ind.pct_rank_last(d["bbw"])
    hr = ctx["now"].hour
    touches = box["t_res"] + box["t_sup"]

    def box_factors(side_):
        ok1, ok2, lab1, lab2 = htf_ok(side_)
        r1 = ctx["regimes"].get("conf") or {}
        htf1 = 10 if (ok1 and r1.get("regime") == "RANGING") else 6 if ok1 else 0
        F = [
            _f("Ranging regime confirmed", True, 16 * _clip(R["range_pts"] / 100 + 0.1), 16, f"{R['range_pts']:.0f} range pts, ADX {R['adx']:.0f}"),
            _f("Repeated edge tests", touches >= 5, 14 * _clip(touches / 6), 14, f"{box['t_res']} res / {box['t_sup']} sup"),
            _f("Price contained", box["inside"] >= 0.9, 9 * _clip((box["inside"] - 0.85) / 0.12), 9, f"{box['inside'] * 100:.0f}% closes inside"),
            _f("Tradable width", 3 <= box["width_atr"] <= 7, 6 if 3 <= box["width_atr"] <= 7 else 3, 6, f"{box['width_atr']:.1f} ATR"),
            _f("H1 not trending against", ok1, htf1, 10, lab1),
            _f("H4 not trending against", ok2, 6 if ok2 else 0, 6, lab2),
            _f("Volatility normal / not expanding", R["vol_state"] == "NORMAL" and bbp <= 0.6, 4 if (R["vol_state"] == "NORMAL" and bbp <= 0.6) else 1, 4, f"BB width pct {bbp * 100:.0f}"),
            _f("Fresh structure", box["since_touch"] <= 20, 3 if box["since_touch"] <= 20 else 0, 3, f"last touch {box['since_touch']} bars ago"),
            _f("Range-friendly session", 0 <= hr < 10, 3 if 0 <= hr < 10 else 0, 3, f"{hr:02d}:00 UTC"),
        ]
        return F, (ok1 and ok2)

    # ---- state machine
    if side == 0:
        F, ok = box_factors(0)
        rr_best = max(buy_plan["rr2"], sell_plan["rr2"])
        F.append(_f("Reward:risk available", rr_best >= cfg["min_rr_range"], 7 * _clip((rr_best - 1.5) / 2), 7, f"{rr_best:.1f}R"))
        raw = sum(f["pts"] for f in F)
        out.update(state="ARMED", side=None, confidence=round(raw / 78 * 100, 1), box_conf=round(raw / 78 * 100, 1),
                   box_confluence=sum(f["ok"] for f in F), box_total=len(F), factors=F)
    else:
        plan = buy_plan if side > 0 else sell_plan
        F, ok = box_factors(side)
        s = side
        o, h, l, c = last["open"], last["high"], last["low"], last["close"]
        ph = prev["high"] if s > 0 else prev["low"]
        q, trig = _bar_quality(o, h, l, c, ph, s)
        extreme = float(l if s > 0 else h)
        if (extreme < box["sup"] - 0.6 * atr) if s > 0 else (extreme > box["res"] + 0.6 * atr):
            trig = False  # the bar pushed far through the edge: breakout attempt, not a rejection
        entry = close
        plan = _plan(box, s, entry, cfg, sp, atr, bar_extreme=extreme)
        rsi = float(last["rsi"])
        rsi_ok = (rsi <= 35) if s > 0 else (rsi >= 65)
        rsi_part = (rsi <= 42) if s > 0 else (rsi >= 58)
        edge_dist = abs(close - (box["sup"] if s > 0 else box["res"])) / w
        F += [
            _f("Rejection candle at edge", trig, 10 * q if trig else 0, 10, f"quality {q:.2f}" if trig else "none yet"),
            _f("Oscillator extreme (RSI)", rsi_ok, 7 if rsi_ok else 3.5 if rsi_part else 0, 7, f"RSI {rsi:.0f}"),
            _f("Entry close to edge", edge_dist <= 0.12, 5 * _clip(1 - edge_dist / 0.25), 5, f"{edge_dist * 100:.0f}% of width from edge"),
            _f("Reward:risk", plan["rr2"] >= cfg["min_rr_range"], 7 * _clip((plan["rr2"] - 1.5) / 2), 7, f"{plan['rr2']:.1f}R to far edge"),
        ]
        box_raw = sum(f["pts"] for f in F[:9]) + 7 * _clip((plan["rr2"] - 1.5) / 2)
        box_ok = sum(f["ok"] for f in F[:9]) + (1 if plan["rr2"] >= cfg["min_rr_range"] else 0)
        raw = sum(f["pts"] for f in F)
        state = "TRIGGERED" if (trig and ok and plan["rr2"] >= cfg["min_rr_range"] and plan["rr1"] >= 1.0) else "IN_ZONE"
        if not ok:
            out["blocked"] = "higher timeframe trending against the fade"
        out.update(state=state, side=sidestr, confidence=round(raw, 1), factors=F, plan=plan,
                   box_conf=round(box_raw / 78 * 100, 1), box_confluence=box_ok, box_total=10)
    out["confluence"] = {"count": sum(f["ok"] for f in out["factors"]), "total": len(out["factors"]), "factors": out["factors"]}
    out["net_rr"] = round(_net_rr(plan["entry"], plan["sl"], plan["tp2"], cost), 2) if side else None
    box_txt = f"Box {box['sup']:.2f}-{box['res']:.2f} ({box['width_atr']:.1f} ATR), {box['t_sup']} support / {box['t_res']} resistance tests, {box['inside'] * 100:.0f}% closes inside"
    reasons = [box_txt, f"Ranging regime confirmed: ADX {R['adx']:.0f}, ER {R['er']:.2f}, EMA20/50 flat and interwoven",
               f"H1 {(ctx['regimes'].get('conf') or {}).get('regime', 'n/a')}, H4 {(ctx['regimes'].get('ctx') or {}).get('regime', 'n/a')}"]
    if side:
        reasons.append(f"Price in {'buy' if side > 0 else 'sell'} zone with {'a rejection candle' if out['state'] == 'TRIGGERED' else 'no confirmed rejection yet'}")
    else:
        reasons.append("Price mid-range: wait for a test of the buy or sell zone")
    out["reasons"] = reasons
    return out, None
