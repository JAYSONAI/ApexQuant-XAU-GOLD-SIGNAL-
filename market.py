"""Candle loading/validation, ATR, swing structure. Optional read-only MT5 data pull."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}
REQ = ["open", "high", "low", "close"]


def server_to_utc(series, tz):
    """Naive wall-clock timestamps in IANA zone `tz` (DST-aware) -> UTC. Tz-aware input is just converted."""
    t = pd.to_datetime(series, errors="coerce")
    if t.dt.tz is not None:
        return t.dt.tz_convert("UTC")
    try:
        loc = t.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
    except Exception:  # repeated hour at DST end that cannot be inferred -> drop those rows (flagged by validate)
        loc = t.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
    return loc.dt.tz_convert("UTC")


def read_candles(src, tz="UTC"):
    df = pd.read_csv(src)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in ("time", "datetime", "timestamp", "date") if c in df.columns), None)
    if tcol is None:
        raise ValueError("Candle CSV needs a time column (time/datetime/timestamp/date)")
    df["time"] = server_to_utc(df[tcol], tz)
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]
    return df


def validate(df, tf, now):
    """Returns (completed_candles, info). Candle time is assumed to be the OPEN time."""
    issues, hard = [], False
    miss = [c for c in REQ if c not in df.columns]
    if miss:
        return df.iloc[0:0], {"issues": [f"missing columns {miss}"], "hard_fail": True}
    df = df.copy()
    if df["time"].isna().any() or df[REQ].isna().any().any():
        issues.append("NaN values in time/OHLC rows (rows dropped)")
        df = df.dropna(subset=["time"] + REQ)
    if not df["time"].is_monotonic_increasing:
        issues.append("candles not chronological (sorted)")
        df = df.sort_values("time")
    dups = int(df["time"].duplicated().sum())
    if dups:
        issues.append(f"{dups} duplicate candle timestamps (dropped)")
        df = df.drop_duplicates("time", keep="last")
    df = df.reset_index(drop=True)
    step = pd.Timedelta(minutes=TF_MIN[tf])
    forming = False
    if len(df) and df["time"].iloc[-1] + step > now:
        forming = True
        df = df.iloc[:-1].reset_index(drop=True)
    if len(df) < 100:
        issues.append(f"only {len(df)} completed candles (need >= 100)")
        hard = True
    last_close = (df["time"].iloc[-1] + step) if len(df) else None
    if last_close is not None and (now - last_close) > 2 * step:
        issues.append(f"latest completed {tf} candle closed {(now - last_close)} ago (stale or market closed)")
        hard = True
    return df, {"issues": issues, "hard_fail": hard, "forming_dropped": forming,
                "last_close_utc": last_close.isoformat() if last_close is not None else None,
                "n": len(df)}


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pivots(df, k=2):
    hi, lo = [], []
    for i in range(k, len(df) - k):
        w = df.iloc[i - k:i + k + 1]
        if df["high"].iloc[i] == w["high"].max():
            hi.append((df["time"].iloc[i].isoformat(), float(df["high"].iloc[i])))
        if df["low"].iloc[i] == w["low"].min():
            lo.append((df["time"].iloc[i].isoformat(), float(df["low"].iloc[i])))
    return hi, lo


def structure(hi, lo):
    if len(hi) < 2 or len(lo) < 2:
        return "RANGE/UNCLEAR"
    hh, hl = hi[-1][1] > hi[-2][1], lo[-1][1] > lo[-2][1]
    lh, ll = hi[-1][1] < hi[-2][1], lo[-1][1] < lo[-2][1]
    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "RANGE/UNCLEAR"


def summarize(df, tf, now, tail=30):
    a = atr(df)
    hi, lo = pivots(df)
    today = df[df["time"].dt.date == now.date()]
    s = {
        "timeframe": tf,
        "last_completed_close": float(df["close"].iloc[-1]),
        "atr14": float(a.iloc[-1]),
        "structure_fractal_k2": structure(hi, lo),
        "recent_swing_highs": hi[-4:], "recent_swing_lows": lo[-4:],
        "range_high_50": float(df["high"].tail(50).max()), "range_low_50": float(df["low"].tail(50).min()),
        "utc_day_high": float(today["high"].max()) if len(today) else None,
        "utc_day_low": float(today["low"].min()) if len(today) else None,
    }
    cols = [c for c in ("time", "open", "high", "low", "close", "volume") if c in df.columns]
    t = df[cols].tail(tail).copy()
    t["time"] = t["time"].dt.strftime("%Y-%m-%dT%H:%MZ")
    s["candles_csv"] = t.round(2).to_csv(index=False)
    return s
