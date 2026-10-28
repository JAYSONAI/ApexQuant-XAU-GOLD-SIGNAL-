"""Deterministic Gates 0-3 (data quality, macro, news, liquidity) for the v3 engine.

Differences vs the v2 `precheck.build`:
 * works for any execution TF set (M1/M5/M15 + confirm + context),
 * calendar coverage is verified automatically (no "I confirm" tick-box needed),
 * FRED staleness is checked, macro can be off / soft (score) / hard (gate),
 * spread is judged against ATR (cost efficiency) as well as absolute / p95 limits,
 * returns a confidence bump (off-session, post-news, missing spread baseline) instead of
   leaving those rules to the LLM prompt.
"""
from datetime import timedelta

import pandas as pd

from . import config, fred as fredmod, indicators as ind, market
from .precheck import parse_quote, relevant, session_window


def evaluate(quote, candles, tfs, calendar, fred_stats, cfg, now, broker_tz="UTC", cal_override=False, atr_exec=None):
    G, issues, bump, notes = {}, [], 0.0, []
    frames = {}

    # ---------------- Gate 0: data quality
    g0 = "PASS"
    q = parse_quote(quote, broker_tz) if quote else None
    age = None
    if q is None:
        g0 = "FAIL"
        issues.append("no valid live quote")
    else:
        age = (now - q["ts"]).total_seconds()
        if age > cfg["max_quote_age"] or age < -5:
            g0 = "FAIL"
            issues.append(f"quote age {age:.0f}s > {cfg['max_quote_age']:.0f}s")
    for tf in tfs:
        raw = candles.get(tf)
        if raw is None:
            g0 = "FAIL"
            issues.append(f"{tf} candles missing")
            continue
        d, info = market.validate(raw, tf, now)
        issues += [f"{tf}: {i}" for i in info["issues"] if "forming" not in i]
        if info["hard_fail"]:
            g0 = "FAIL"
        else:
            frames[tf] = d
    # calendar coverage (automatic)
    cal_cover = None
    if calendar is None:
        cal_state = "UNVERIFIED"
        issues.append("economic calendar not supplied")
    else:
        cal_cover = calendar["time_utc"].max() if len(calendar) else None
        need = now + timedelta(hours=cfg["calendar_min_cover_hours"])
        if cal_override:
            cal_state = "OVERRIDE"
            notes.append("calendar coverage manually overridden")
        elif cal_cover is None or cal_cover < need:
            cal_state = "UNVERIFIED"
            issues.append(f"calendar ends {cal_cover:%Y-%m-%d %H:%M}Z, need coverage to {need:%Y-%m-%d %H:%MZ} - import a fresh calendar")
        else:
            cal_state = "OK"
    G["gate0"] = {"status": g0, "issues": issues, "quote_age_sec": age, "calendar": cal_state}

    # ---------------- Gate 1: macro
    mode = cfg["macro_mode"]
    if mode == "off":
        macro, mnote = "OFF", "macro disabled (MACRO_MODE=off)"
    elif not fred_stats or "UNVERIFIED" in (fred_stats["DFII10"].get("direction"), fred_stats["DTWEXBGS"].get("direction")):
        macro, mnote = "UNVERIFIED", "FRED not loaded / insufficient observations"
    else:
        ages = []
        for sid in ("DFII10", "DTWEXBGS"):
            try:
                ages.append((now.date() - pd.Timestamp(fred_stats[sid]["latest_date"]).date()).days)
            except Exception:
                ages.append(999)
        if max(ages) > cfg["fred_max_age_days"]:
            macro, mnote = "UNVERIFIED", f"FRED data {max(ages)} days old (> {cfg['fred_max_age_days']:.0f})"
        else:
            macro = fredmod.classify_macro(fred_stats["DFII10"], fred_stats["DTWEXBGS"])
            mnote = f"real yield {fred_stats['DFII10']['direction']}, USD {fred_stats['DTWEXBGS']['direction']} (daily data, lagged)"
    G["gate1"] = {"status": macro, "note": mnote, "mode": mode}

    # ---------------- Gate 2: news shield
    g2, detail, next_event = "UNVERIFIED", [], None
    if cal_state in ("OK", "OVERRIDE"):
        g2 = "CLEAR"
        cf = relevant(calendar, cfg)
        imp = cf["impact"].astype(str).str.lower() if "impact" in cf.columns else pd.Series(["high"] * len(cf), index=cf.index)
        for _, ev in cf[imp == "high"].iterrows():
            mins = (now - ev["time_utc"]).total_seconds() / 60
            name = str(ev.get("event", "event"))
            if -30 <= mins < 15:
                g2 = "FREEZE ACTIVE"
                detail.append(f"{name}: {mins:+.0f} min (freeze -30/+15)")
            elif 15 <= mins < 60 and g2 == "CLEAR":
                g2 = "POST-NEWS REVIEW"
                detail.append(f"{name}: released {mins:.0f} min ago")
            if -240 <= mins < -30 and (next_event is None or -mins < next_event[1]):
                next_event = (name, -mins)
    else:
        detail.append("calendar coverage not verified")
    G["gate2"] = {"status": g2, "detail": detail, "next_event": next_event}
    if g2 == "POST-NEWS REVIEW":
        bump += cfg["postnews_bump"]

    # ---------------- Gate 3: session & liquidity
    if atr_exec is None and tfs and tfs[0] in frames:
        atr_exec = float(ind.atr(frames[tfs[0]]).iloc[-1])
    g3, g3d = "PASS", []
    spread = None
    if q:
        spread = q["ask"] - q["bid"]
        if spread > cfg["max_spread"]:
            g3 = "FAIL"
            g3d.append(f"spread {spread:.2f} > max {cfg['max_spread']:.2f}")
        p95 = q.get("spread_baseline_p95")
        if p95 is not None and float(p95) > 0:
            if spread > float(p95) * cfg["spread_mult"]:
                g3 = "FAIL"
                g3d.append(f"spread {spread:.2f} > {cfg['spread_mult']:.1f}x baseline p95 {float(p95):.2f}")
        else:
            if cfg["require_spread_baseline"]:
                g3 = "FAIL"
                g3d.append("spread baseline missing (REQUIRE_SPREAD_BASELINE=1)")
            else:
                bump += 3
                g3d.append("spread baseline missing: +3 confidence required")
        if atr_exec:
            if spread > cfg["max_spread_atr"] * atr_exec:
                g3 = "FAIL"
                g3d.append(f"spread {spread:.2f} = {spread / atr_exec * 100:.0f}% of ATR (> {cfg['max_spread_atr'] * 100:.0f}%): cost too high for this timeframe")
            if cfg["est_cost"] and atr_exec < 4 * cfg["est_cost"]:
                g3 = "FAIL"
                g3d.append("ATR too small relative to estimated costs")
    else:
        g3 = "FAIL"
    ws, we, wmode = session_window(cfg, now)
    in_window = ws <= now < we
    if not in_window:
        bump += cfg["offsession_bump"]
        g3d.append(f"outside {ws:%H:%M}-{we:%H:%M} UTC window: +{cfg['offsession_bump']:.0f} confidence required")
    G["gate3"] = {"status": g3, "detail": g3d, "in_window": in_window, "spread": spread}

    # ---------------- verdict
    reason = None
    if g0 == "FAIL":
        reason = "INSUFFICIENT DATA"
    elif cal_state == "UNVERIFIED":
        reason = "NEWS CALENDAR UNVERIFIED"
    elif g2 == "FREEZE ACTIVE":
        reason = "NEWS FREEZE"
    elif g3 == "FAIL":
        reason = "LIQUIDITY / SPREAD"
    elif mode == "gate" and macro in ("NEUTRAL", "UNVERIFIED"):
        reason = "MACRO CONFLICT" if macro == "NEUTRAL" else "MACRO UNVERIFIED"
    detail = []
    if reason:
        detail = ([f"Data: {i}" for i in issues] if g0 == "FAIL" or cal_state == "UNVERIFIED" else []) + \
                 ([f"News: {d}" for d in G["gate2"]["detail"]] if g2 == "FREEZE ACTIVE" else []) + \
                 ([f"Liquidity: {d}" for d in g3d] if g3 == "FAIL" else []) + ([f"Macro: {mnote}"] if reason.startswith("MACRO") else [])
    permitted = {"BULLISH": "LONG", "BEARISH": "SHORT"}.get(macro) if mode == "gate" else None
    return {"gates": G, "blocked": reason is not None, "block_reason": reason, "frames": frames, "quote": q,
            "spread": spread, "block_detail": detail, "in_window": in_window, "macro": macro, "conf_bump": bump, "permitted": permitted,
            "notes": notes}
