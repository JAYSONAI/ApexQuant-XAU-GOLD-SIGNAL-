"""Deterministic pre-check of Gates 0-3. These results are passed to the LLM as authoritative."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from . import fred as fredmod
from . import market


def read_calendar(src, tz="UTC"):
    """Accepts the ForexFactory CSV export (Title,Country,Date,Time,Impact,Forecast,Previous,URL;
    date MM-DD-YYYY, time like 2:15pm) or a simple CSV with a `time`/`time_utc` column.
    Naive times are read in zone `tz`. Rows without a clock time (All Day/Tentative) are dropped."""
    df = pd.read_csv(src)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={"title": "event", "forecast": "consensus", "country": "currency"})
    if "date" in df.columns and "time" in df.columns:
        d = pd.to_datetime(df["date"].astype(str).str.strip(), format="%m-%d-%Y", errors="coerce")
        if d.isna().all():
            d = pd.to_datetime(df["date"], errors="coerce")
        t = pd.to_datetime(df["time"].astype(str).str.strip().str.upper(), format="%I:%M%p", errors="coerce")
        naive = d + (t - t.dt.normalize())
    else:
        tcol = next((c for c in ("time_utc", "time", "datetime", "timestamp") if c in df.columns), df.columns[0])
        naive = pd.to_datetime(df[tcol], errors="coerce")
    df["time_utc"] = market.server_to_utc(naive, tz)
    df = df.drop(columns=[c for c in ("url",) if c in df.columns])
    return df.dropna(subset=["time_utc"]).sort_values("time_utc").reset_index(drop=True)


def relevant(calendar, cfg):
    """Keep only events for the configured currencies (default USD + global)."""
    if calendar is None or "currency" not in calendar.columns or not cfg.get("calendar_currencies"):
        return calendar
    return calendar[calendar["currency"].astype(str).str.upper().isin(cfg["calendar_currencies"])]


def session_window(cfg, now):
    """auto: NY 08:00 -> London 17:00 (each in its own DST regime). fixed: SESSION_START/END_UTC."""
    if cfg.get("session_mode") == "fixed":
        s = now.replace(hour=cfg["session_start"], minute=0, second=0, microsecond=0)
        e = now.replace(hour=cfg["session_end"], minute=0, second=0, microsecond=0)
        return s, e, "fixed"
    ny, ld = ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
    d, dl = now.astimezone(ny).date(), now.astimezone(ld).date()
    s = datetime(d.year, d.month, d.day, 8, 0, tzinfo=ny).astimezone(timezone.utc)
    e = datetime(dl.year, dl.month, dl.day, 17, 0, tzinfo=ld).astimezone(timezone.utc)
    return s, e, "auto"


def parse_quote(q, tz="UTC"):
    ts = pd.to_datetime(q.get("timestamp"), errors="coerce")
    if pd.isna(ts):
        return None
    ts = market.server_to_utc(pd.Series([ts]), tz).iloc[0]
    q = dict(q)
    q["ts"] = ts
    q["bid"], q["ask"] = float(q["bid"]), float(q["ask"])
    return q


def build(quote, candles, calendar, fred_stats, cfg, now, calendar_confirmed, broker_tz="UTC"):
    G, notes = {}, []

    # ---- Gate 0
    g0_issues, g0 = [], "PASS"
    q = parse_quote(quote, broker_tz) if quote else None
    if q is None:
        g0, _ = "FAIL", g0_issues.append("no valid live quote (bid/ask/timestamp)")
        age = None
    else:
        age = (now - q["ts"]).total_seconds()
        if age > cfg["max_quote_age"] or age < -5:
            g0 = "FAIL"
            g0_issues.append(f"quote age {age:.0f}s exceeds {cfg['max_quote_age']:.0f}s")
    summaries = {}
    for tf in ("M15", "H1", "H4"):
        if tf not in candles or candles[tf] is None:
            g0 = "FAIL"
            g0_issues.append(f"{tf} candles missing")
            continue
        d, info = market.validate(candles[tf], tf, now)
        g0_issues += [f"{tf}: {i}" for i in info["issues"]]
        if info["hard_fail"]:
            g0 = "FAIL"
        else:
            summaries[tf] = market.summarize(d, tf, now)
            summaries[tf]["last_close_utc"] = info["last_close_utc"]
    if not fred_stats or "UNVERIFIED" in (fred_stats["DFII10"].get("direction"), fred_stats["DTWEXBGS"].get("direction")):
        g0 = "FAIL"
        g0_issues.append("FRED observations unavailable/insufficient")
    if calendar is None:
        g0 = "FAIL"
        g0_issues.append("economic calendar not supplied")
    elif not calendar_confirmed:
        g0 = "FAIL"
        g0_issues.append("calendar coverage not confirmed (tick the confirmation box in the sidebar)")
    G["gate0"] = {"status": g0, "issues": g0_issues, "quote_age_sec": age, "now_utc": now.isoformat()}

    # ---- Gate 1
    if fred_stats:
        bias = fredmod.classify_macro(fred_stats["DFII10"], fred_stats["DTWEXBGS"])
    else:
        bias = "UNVERIFIED"
    G["gate1"] = {"status": bias, "note": "heuristic z-score classification; daily data, not live"}

    # ---- Gate 2
    g2, detail = "UNVERIFIED", []
    if calendar is not None and calendar_confirmed:
        g2 = "CLEAR"
        cal_f = relevant(calendar, cfg)
        hi = cal_f[cal_f.get("impact", pd.Series(["high"] * len(cal_f), index=cal_f.index)).astype(str).str.lower() == "high"]
        for _, ev in hi.iterrows():
            mins = (now - ev["time_utc"]).total_seconds() / 60
            name = str(ev.get("event", "event"))
            if -30 <= mins < 15:
                g2 = "FREEZE ACTIVE"
                detail.append(f"{name}: {mins:+.0f} min vs release (freeze window -30/+15)")
            elif 15 <= mins < 60 and g2 == "CLEAR":
                g2 = "POST-NEWS REVIEW"
                detail.append(f"{name}: released {mins:.0f} min ago; actual={ev.get('actual')} "
                              f"consensus={ev.get('consensus')} previous={ev.get('previous')} "
                              "- price response must be assessed")
            elif -240 <= mins < -30:
                detail.append(f"upcoming: {name} in {-mins:.0f} min")
    if g2 == "UNVERIFIED":
        detail.append("calendar missing - save the ForexFactory CSV as data/calendar.csv (or upload it)" if calendar is None
                      else "calendar coverage not confirmed - tick the sidebar confirmation box")
    G["gate2"] = {"status": g2, "detail": detail}

    # ---- Gate 3
    g3, g3d = "PASS", []
    if q:
        spread = q["ask"] - q["bid"]
        G_sp = {"spread_usd": round(spread, 3)}
        if spread > cfg["max_spread"]:
            g3 = "FAIL"
            g3d.append(f"spread {spread:.2f} > max {cfg['max_spread']:.2f}")
        p95, med = q.get("spread_baseline_p95"), q.get("spread_baseline_median")
        if p95 is not None and float(p95) <= 0:
            p95 = None
        if p95 is None:
            g3d.append("spread baseline UNVERIFIED (no session baseline supplied)")
            if g3 == "PASS":
                g3 = "UNVERIFIED"
        elif spread > float(p95) * cfg["spread_mult"]:
            g3 = "FAIL"
            g3d.append(f"spread {spread:.2f} above {cfg['spread_mult']:.1f}x baseline p95 {float(p95):.2f}")
        else:
            g3d.append(f"spread {spread:.2f} acceptable vs baseline p95 {float(p95):.2f}")
        G_sp.update(baseline_median=med, baseline_p95=p95)
    else:
        G_sp = {}
        g3 = "UNVERIFIED"
    ws, we, wmode = session_window(cfg, now)
    in_window = ws <= now < we
    wtxt = f"{ws:%H:%M}-{we:%H:%M} UTC ({wmode})"
    g3d.append(f"inside preferred session window {wtxt}" if in_window else
               f"OUTSIDE preferred window {wtxt} - require stronger confirmation, lower confidence")
    if "M15" in summaries and cfg["est_cost"] and summaries["M15"]["atr14"] < 4 * cfg["est_cost"]:
        g3 = "FAIL"
        g3d.append("M15 ATR too small relative to estimated costs")
    G["gate3"] = {"status": g3, "detail": g3d, "in_preferred_window": in_window, **G_sp}

    # ---- Prefilter verdict
    if g0 == "FAIL" or "UNVERIFIED" in (bias, g2) or g3 == "UNVERIFIED":
        v = "NO TRADE — INSUFFICIENT DATA"
    elif bias == "NEUTRAL":
        v = "NO TRADE — MACRO CONFLICT"
    elif g2 == "FREEZE ACTIVE":
        v = "NO TRADE — NEWS FREEZE"
    elif g3 == "FAIL":
        v = "NO TRADE — LIQUIDITY / SPREAD FAILURE"
    else:
        v = "PASS — proceed to Gate 4 structure and risk geometry"
    return {"gates": G, "prefilter_verdict": v, "permitted_direction":
            {"BULLISH": "LONG only", "BEARISH": "SHORT only"}.get(bias, "NONE"),
            "summaries": summaries, "quote": ({k: (v if k != "ts" else v.isoformat()) for k, v in q.items()} if q else None)}


def to_llm_payload(pre, fred_stats, calendar, cfg, now):
    cal = []
    if calendar is not None:
        calendar = relevant(calendar, cfg)
        w = calendar[(calendar["time_utc"] > now - pd.Timedelta(hours=6)) & (calendar["time_utc"] < now + pd.Timedelta(hours=24))]
        w = w.copy()
        w["time_utc"] = w["time_utc"].dt.strftime("%Y-%m-%dT%H:%MZ")
        cal = w.to_dict("records")
    return json.dumps({
        "analysis_timestamp_utc": now.isoformat(),
        "instructions": "The deterministic pre-check below is AUTHORITATIVE for Gates 0-3. Do not overturn a failed or "
                        "unverified gate. Only evaluate Gate 4 and risk geometry if the prefilter verdict is PASS. "
                        "Use only the numbers given here. "
                        f"If gate3.in_preferred_window is false, approve a setup only when your confidence score is >= "
                        f"{cfg['offsession_min_conf']}; otherwise return a NO TRADE verdict and say confidence was below "
                        "the off-session minimum. Confidence is setup quality, not a win probability.",
        "config": {k: cfg[k] for k in ("session_start", "session_end", "max_spread", "max_quote_age", "est_cost", "spread_mult", "offsession_min_conf")},
        "precheck": {k: pre[k] for k in ("gates", "prefilter_verdict", "permitted_direction", "quote")},
        "fred": fred_stats,
        "calendar_window": cal,
        "candles": pre["summaries"],
    }, indent=1, default=str)


def local_card(pre, now):
    g = pre["gates"]
    lines = [
        "🪙 **APEXQUANT-XAU ANALYTICAL SIGNAL CARD (local pre-check, LLM skipped)**", "",
        f"- Analysis Timestamp: {now.isoformat()}",
        f"- **SYSTEM VERDICT: {pre['prefilter_verdict']}**", "- CONFIDENCE SCORE: NOT SCORED", "",
        f"- Gate 0 — Data Quality: **{g['gate0']['status']}** — " + ("; ".join(g['gate0']['issues']) or "all checks passed"),
        f"- Gate 1 — Macro Bias: **{g['gate1']['status']}**",
        f"- Gate 2 — News Shield: **{g['gate2']['status']}** — " + ("; ".join(g['gate2']['detail']) or "no events in window"),
        f"- Gate 3 — Session & Liquidity: **{g['gate3']['status']}** — " + "; ".join(g['gate3']['detail']),
        "- Gate 4 — Technical Structure: NOT EVALUATED (upstream gate failed)", "",
        "⚠️ Signal-only analytical output. Not an order, broker instruction, or guarantee of profit.",
    ]
    return "\n".join(lines)
