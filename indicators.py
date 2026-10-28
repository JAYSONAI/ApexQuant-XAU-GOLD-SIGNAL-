"""Vectorised indicators + non-repainting swing detection. Pure functions, no I/O.

Everything here is computed on COMPLETED candles only, so a value at bar i never changes
when later bars arrive (no repainting). Swing pivots are confirmed `k` bars late by design.
"""
import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def true_range(df):
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df, n=14):
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    """Wilder ADX with +DI/-DI. Returns DataFrame(adx, pdi, mdi)."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = 1 / n
    tr = true_range(df).ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=a, adjust=False).mean() / tr
    mdi = 100 * pd.Series(mdm, index=df.index).ewm(alpha=a, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=a, adjust=False).mean(), "pdi": pdi, "mdi": mdi})


def rsi(close, n=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def efficiency_ratio(close, n=20):
    """Kaufman ER: |net move| / sum |bar moves|. ~1 = clean trend, ~0 = chop."""
    net = (close - close.shift(n)).abs()
    path = close.diff().abs().rolling(n).sum()
    return net / path.replace(0, np.nan)


def bb_width(close, n=20, k=2.0):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    return (2 * k * sd) / ma


def pct_rank_last(s, window=100):
    """Percentile rank (0-1) of the last value inside the trailing window."""
    w = s.dropna().tail(window)
    if len(w) < 20:
        return 0.5
    return float((w <= w.iloc[-1]).mean())


def pivots(df, k=2, min_amp=None):
    """Confirmed fractal pivots, alternating H/L, noise-filtered by `min_amp` (price units, array
    aligned with df, typically mult*ATR). Pivot at i is only known at bar i+k (no repaint).
    Returns list of dicts: {i, t, p, type}."""
    h, l = df["high"].values, df["low"].values
    n = len(df)
    raw = []
    for i in range(k, n - k):
        wh, wl = h[i - k:i + k + 1], l[i - k:i + k + 1]
        if np.argmax(wh) == k:  # first occurrence of the window max is bar i (ties -> earliest)
            raw.append((i, float(h[i]), "H"))
        if np.argmin(wl) == k:
            raw.append((i, float(l[i]), "L"))
    raw.sort(key=lambda x: (x[0], x[2]))
    out = []
    for i, p, t in raw:
        if out and out[-1]["type"] == t:  # same side twice: keep the more extreme
            if (t == "H" and p > out[-1]["p"]) or (t == "L" and p < out[-1]["p"]):
                out[-1] = {"i": i, "p": p, "type": t}
            continue
        if out and min_amp is not None:
            need = float(min_amp[i]) if np.ndim(min_amp) else float(min_amp)
            if abs(p - out[-1]["p"]) < need:  # swing too small to matter -> ignore
                continue
        out.append({"i": i, "p": p, "type": t})
    for o in out:
        o["t"] = df["time"].iloc[o["i"]]
    return out


def structure_from_pivots(piv):
    """BULLISH (HH+HL) / BEARISH (LH+LL) / RANGE from the last two pivots of each side."""
    hi = [p for p in piv if p["type"] == "H"][-2:]
    lo = [p for p in piv if p["type"] == "L"][-2:]
    if len(hi) < 2 or len(lo) < 2:
        return "RANGE"
    if hi[1]["p"] > hi[0]["p"] and lo[1]["p"] > lo[0]["p"]:
        return "BULLISH"
    if hi[1]["p"] < hi[0]["p"] and lo[1]["p"] < lo[0]["p"]:
        return "BEARISH"
    return "RANGE"


def enrich(df):
    """Add all indicator columns once per analysis cycle (the only O(n) pass)."""
    d = df.copy()
    d["atr"] = atr(d)
    a = adx(d)
    d["adx"], d["pdi"], d["mdi"] = a["adx"], a["pdi"], a["mdi"]
    d["ema20"], d["ema50"] = ema(d["close"], 20), ema(d["close"], 50)
    d["rsi"] = rsi(d["close"])
    d["er"] = efficiency_ratio(d["close"])
    d["bbw"] = bb_width(d["close"])
    return d
