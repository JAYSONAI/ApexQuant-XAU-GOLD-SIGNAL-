"""Deterministic analysis cycle: gates -> regime -> strategies -> quality thresholds -> de-dup -> snapshot.

`analyze()` is a pure function of its inputs (plus the signal store) so the same code runs live and in replay tests.
It must be called once per CLOSED exec-TF candle (evaluate-on-close = no repainting, no intrabar noise).
"""
import time

import numpy as np
import pandas as pd

from . import config, gates, indicators as ind, regime as regmod, strategies as strat

BIAS_ON = 0.35


def _dir_val(R):
    if not R or R.get("regime") in (None, "UNKNOWN"):
        return 0.0
    if R["regime"] == "TRENDING_UP":
        return 1.0
    if R["regime"] == "TRENDING_DOWN":
        return -1.0
    return {"BULLISH": 0.5, "BEARISH": -0.5}.get(R.get("structure"), 0.0)


def market_bias(regs, macro, macro_mode):
    """Weighted multi-timeframe direction score in [-1, 1] (+macro as a small soft input)."""
    s = 2.0 * _dir_val(regs.get("ctx")) + 1.5 * _dir_val(regs.get("conf")) + 1.0 * _dir_val(regs.get("exec"))
    w = 4.5
    if macro_mode != "off" and macro in ("BULLISH", "BEARISH"):
        s += 0.5 if macro == "BULLISH" else -0.5
        w += 0.5
    v = s / w
    lab = "BULLISH" if v >= BIAS_ON else "BEARISH" if v <= -BIAS_ON else "NEUTRAL"
    return lab, round(v, 2)


def key_levels(frames, regs, price, atr, box, n_each=3):
    """Cluster swing pivots of all three TFs + prior-day H/L + range edges into ranked S/R levels."""
    cand = []
    for key, wgt in (("ctx", 3.0), ("conf", 2.0), ("exec", 1.0)):
        for p in (regs.get(key) or {}).get("pivots", []):
            cand.append((p["p"], wgt, key))
    d = frames["exec"]
    day = d["time"].dt.normalize()
    today = day.iloc[-1]
    prev = d[day < today]
    if len(prev):
        pd_ = prev[prev["time"].dt.normalize() == prev["time"].dt.normalize().iloc[-1]]
        cand += [(float(pd_["high"].max()), 3.0, "PDH"), (float(pd_["low"].min()), 3.0, "PDL")]
    if box:
        cand += [(box["res"], 3.0, "RNG"), (box["sup"], 3.0, "RNG")]
    cand.sort()
    tol = 0.4 * atr
    groups = []
    for p, w, tag in cand:
        if groups and p - groups[-1]["hi"] <= tol:
            g = groups[-1]
            g["pts"].append(p)
            g["w"] += w
            g["tags"].add(tag)
            g["hi"] = p
        else:
            groups.append({"pts": [p], "w": w, "tags": {tag}, "hi": p})
    lv = [{"p": float(np.mean(g["pts"])), "w": g["w"], "tags": sorted(g["tags"]), "n": len(g["pts"])} for g in groups]
    above = sorted([l for l in lv if l["p"] > price + 0.15 * atr], key=lambda l: l["p"])
    below = sorted([l for l in lv if l["p"] < price - 0.15 * atr], key=lambda l: -l["p"])
    # keep the strongest of the nearest few on each side
    def pick(side):
        near = side[:6]
        top = sorted(near, key=lambda l: -l["w"])[:n_each]
        return sorted(top, key=lambda l: abs(l["p"] - price))
    return {"resistance": pick(above), "support": pick(below)}


def _fingerprint(sig, atr):
    grid = 0.75 * atr
    return f"{sig['type']}:{sig['side']}:{sig['tf']}:{int(round(sig['anchor'] / grid))}"


def analyze(raw_candles, quote, calendar, fred_stats, cfg, tf, now, store, broker_tz="UTC", cal_override=False, prev=None):
    t0 = time.perf_counter()
    tfs = config.TF_MAP[tf]                                   # (exec, confirm, context)
    G = gates.evaluate(quote, raw_candles, tfs, calendar, fred_stats, cfg, now, broker_tz, cal_override)
    snap = {"ts": now, "tf": tf, "tfs": tfs, "gates": G["gates"], "blocked": G["blocked"], "block_reason": G["block_reason"],
            "macro": G["macro"], "permitted": G["permitted"], "in_window": G["in_window"], "spread": G["spread"],
            "price": None, "regime": None, "regimes": {}, "bias": ("NEUTRAL", 0.0), "levels": None, "range": None,
            "new_signals": [], "why_not": [], "events": [], "verdict": "", "notes": G["notes"], "spark": None,
            "bar_time": None}
    q = G["quote"]
    if q:
        snap["price"] = {"bid": q["bid"], "ask": q["ask"], "mid": (q["bid"] + q["ask"]) / 2, "spread": q["ask"] - q["bid"]}
    if any(t not in G["frames"] for t in tfs):
        snap["why_not"] = G["block_detail"][:3]
        snap["verdict"] = f"NO TRADE — {G['block_reason'] or 'INSUFFICIENT DATA'}"
        snap["timing_ms"] = {"total": round((time.perf_counter() - t0) * 1000, 1)}
        return snap

    t1 = time.perf_counter()
    frames = {k: ind.enrich(G["frames"][t]) for k, t in zip(("exec", "conf", "ctx"), tfs)}
    t2 = time.perf_counter()
    regs = {k: regmod.detect(frames[k]) for k in frames}
    t3 = time.perf_counter()
    R = regs["exec"]
    price = snap["price"]["mid"] if snap["price"] else float(frames["exec"]["close"].iloc[-1])
    atr = R["atr"]
    bar_time = frames["exec"]["time"].iloc[-1]
    snap["bar_time"] = bar_time
    snap["regimes"] = {k: {kk: v for kk, v in r.items() if kk != "pivots"} for k, r in regs.items()}
    snap["regime"] = snap["regimes"]["exec"]
    snap["bias"] = market_bias(regs, G["macro"], cfg["macro_mode"])
    d = frames["exec"].tail(90)
    snap["spark"] = {"t": [t.isoformat() for t in d["time"]], "c": [round(float(x), 2) for x in d["close"]],
                     "e20": [round(float(x), 2) for x in d["ema20"]], "e50": [round(float(x), 2) for x in d["ema50"]]}

    ctx = {"cfg": cfg, "frames": frames, "regimes": regs, "spread": G["spread"] or 0.0, "in_window": G["in_window"],
           "macro": G["macro"], "now": now}

    # ---------------- strategies (only those the regime permits)
    cands, why = [], []
    box = None
    allowed = list(R["allowed"])
    override = False
    if R["regime"] == "TRANSITIONING" and R["vol_state"] == "NORMAL" and R["raw_last"] != "TRANSITIONING":
        # unconfirmed regime: evaluate the strategy the last bar points to, but demand exceptional confidence
        R2 = dict(R, regime=R["raw_last"])
        regs2 = dict(regs, exec=R2)
        ctx2 = dict(ctx, regimes=regs2)
        allowed, override, ctx_use = (["TREND"] if R["raw_last"].startswith("TRENDING") else ["RANGE"]), True, ctx2
    else:
        ctx_use = ctx
    min_extra = G["conf_bump"]
    if "TREND" in allowed:
        sig, reason = strat.trend_setup(ctx_use)
        if sig is None:
            why.append(f"Trend: {reason}")
        else:
            need = max(cfg["min_conf_trend"] + min_extra, cfg["transition_min_conf"] if override else 0)
            if G["permitted"] and sig["side"] != G["permitted"]:
                why.append(f"Trend {sig['side']} blocked: macro gate permits {G['permitted']} only")
            elif sig["confidence"] < need or sig["confluence"]["count"] < cfg["min_confluence_trend"]:
                why.append(f"Trend {sig['side']} scored {sig['confidence']:.0f} (need {need:.0f}), confluence {sig['confluence']['count']}/{sig['confluence']['total']} (need {cfg['min_confluence_trend']})")
            else:
                cands.append(sig)
    if "RANGE" in allowed:
        rs, reason = strat.range_setup(ctx_use)
        if rs is None:
            why.append(f"Range: {reason}")
        else:
            box = rs["box"]
            need = max(cfg["min_conf_range"] + min_extra, cfg["transition_min_conf"] if override else 0)
            qualified = rs["box_conf"] >= cfg["min_box_conf"] and rs["box_confluence"] >= 7
            rs["qualified"] = bool(qualified)
            rs["min_conf_needed"] = need
            if rs["state"] == "TRIGGERED":
                if rs["confidence"] >= need and rs["confluence"]["count"] >= cfg["min_confluence_range"]:
                    sig = {"type": "RANGE", "side": "LONG" if rs["side"] == "BUY" else "SHORT", "state": "TRIGGERED", **rs["plan"],
                           "rr": rs["plan"]["rr2"], "net_rr": rs["net_rr"], "confidence": rs["confidence"], "confluence": rs["confluence"],
                           "reasons": rs["reasons"], "anchor": (rs["box"]["sup"] if rs["side"] == "BUY" else rs["box"]["res"]),
                           "atr": atr, "expiry_bars": cfg["range_expiry_bars"], "box": rs["box"]}
                    cands.append(sig)
                else:
                    why.append(f"Range {rs['side']} scored {rs['confidence']:.0f} (need {need:.0f}), confluence {rs['confluence']['count']}/{rs['confluence']['total']}")
            if qualified:
                snap["range"] = rs                                  # only qualified boxes are ever displayed
            else:
                why.append(f"Range box seen but below display quality ({rs['box_conf']:.0f} < {cfg['min_box_conf']:.0f} or confluence {rs['box_confluence']}/10 < 7)")
    if not allowed and not R["allowed"]:
        why.append(f"Regime {R['regime']}" + (f" ({R['sub']})" if R.get("sub") else "") + (f", volatility {R['vol_state']}" if R["vol_state"] != "NORMAL" else "") + ": no strategy permitted")
    if G["blocked"]:
        cands = []                                                  # gates always win

    # ---------------- de-dup, persistence
    tf_min = config.TF_MINUTES[tf]
    for s in cands:
        s.update({"tf": tf, "bar_time": bar_time.isoformat(), "regime": R["regime"], "atr": atr})
        s["fingerprint"] = _fingerprint(s, atr)
        s["id"] = f"{tf}-{s['type'][0]}-{s['side'][0]}-{bar_time:%Y%m%d%H%M}"
        if store.is_duplicate(s, tf_min, cfg["cooldown_bars"]):
            why.append(f"{s['type']} {s['side']} suppressed: duplicate of an active/recent signal")
            continue
        store.add(s)
        snap["new_signals"].append(s)
        snap["events"].append(f"NEW {s['type']} {s['side']} @ {s['entry']:.2f} (conf {s['confidence']:.0f})")
    if prev and prev.get("regime") and prev["regime"]["regime"] != R["regime"]:
        snap["events"].append(f"Regime {prev['regime']['regime']} -> {R['regime']}")

    snap["levels"] = key_levels(frames, regs, price, atr, box)
    act = store.active(tf)
    snap["active"] = act
    snap["why_not"] = (G["block_detail"] if G["blocked"] else why)[:3]
    if G["blocked"]:
        snap["verdict"] = f"NO TRADE — {G['block_reason']}"
    elif act:
        a = act[0]
        snap["verdict"] = f"{a['type']} {a['side']} ACTIVE"
    else:
        snap["verdict"] = f"NO SETUP — {R['regime'].replace('_', ' ')}"
    snap["timing_ms"] = {"gates": round((t1 - t0) * 1000, 1), "indicators": round((t2 - t1) * 1000, 1),
                         "regime": round((t3 - t2) * 1000, 1), "total": round((time.perf_counter() - t0) * 1000, 1)}
    return snap


def llm_eligible(sig, cfg, store, now):
    """Deterministic gate in front of any LLM call. Returns (ok, reason)."""
    if cfg["llm_mode"] == "off":
        return False, "LLM off"
    c = sig["confluence"]
    if sig["confidence"] < cfg["llm_min_conf"]:
        return False, f"confidence {sig['confidence']:.0f} < {cfg['llm_min_conf']:.0f}"
    if c["count"] / max(c["total"], 1) < cfg["llm_min_confluence_ratio"]:
        return False, f"confluence {c['count']}/{c['total']} below {cfg['llm_min_confluence_ratio']:.0%}"
    if store.llm_attempted(sig["id"]) >= 2:
        return False, "already attempted for this signal"
    if store.llm_calls_since(now - pd.Timedelta(hours=1)) >= cfg["llm_max_per_hour"]:
        return False, "hourly LLM budget used"
    if store.llm_calls_since(now - pd.Timedelta(days=1)) >= cfg["llm_max_per_day"]:
        return False, "daily LLM budget used"
    return True, "ok"
