"""SYNTHETIC price generator for tests and the clearly-labelled DEMO data source.

This is NOT market data. It builds a gold-like M1 path from alternating regimes
(trend / mean-reverting range / shock) so the engine and dashboard can be exercised offline.
"""
import numpy as np
import pandas as pd

RULES = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}


def make_m1(minutes, seed=7, start_price=4000.0, end=None, plan=None, sigma=0.45):
    """Returns (m1 DataFrame[time,open,high,low,close,volume], labels Series of regime per minute)."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end if end is not None else pd.Timestamp.now(tz="UTC").floor("1min"))
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    times = pd.date_range(end=end, periods=minutes, freq="1min")
    # regime plan: list of (label, minutes)
    if plan is None:
        plan, tot = [], 0
        kinds = ["RANGE", "TREND_UP", "RANGE", "TREND_DOWN", "RANGE", "TREND_UP", "SHOCK", "RANGE", "TREND_DOWN"]
        i = 0
        while tot < minutes:
            k = kinds[i % len(kinds)]
            L = (int(rng.integers(2880, 5760)) if k.startswith("TREND") else int(rng.integers(2160, 4320))) if k != "SHOCK" else 90
            plan.append((k, L))
            tot += L
            i += 1
    labels = []
    for k, L in plan:
        labels += [k] * L
    labels = np.array(labels[:minutes])
    x = np.empty(minutes)
    px, center = start_price, start_price
    for t in range(minutes):
        k = labels[t]
        if t == 0 or labels[t - 1] != k:
            center = px
        e = rng.normal(0, sigma)
        if k == "RANGE":                      # bounded box with reflecting edges (+ weak pull to centre)
            px += -0.01 * (px - center) + e
            hw = 6.0
            if px > center + hw:
                px = 2 * (center + hw) - px
            elif px < center - hw:
                px = 2 * (center - hw) - px
        elif k == "TREND_UP":
            px += 0.03 + 1.0 * e
        elif k == "TREND_DOWN":
            px += -0.03 + 1.0 * e
        else:  # SHOCK: very high variance
            px += 3.0 * e
        x[t] = px
    close = x
    open_ = np.r_[start_price, close[:-1]]
    wick = np.abs(rng.normal(0, sigma * 0.5, minutes))
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.normal(0, sigma * 0.5, minutes))
    vol = rng.integers(40, 400, minutes)
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close, "volume": vol})
    return df, pd.Series(labels, index=times)


def resample(m1, tf):
    """Broker-style bars; `time` = bar OPEN time (UTC). Incomplete leading/trailing bars are kept (caller trims)."""
    r = m1.set_index("time").resample(RULES[tf], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return r.reset_index()


def frames_upto(m1, now, tfs, bars=400):
    """All requested TFs from M1 history, including the still-forming bar (like a live feed would)."""
    m = m1[m1["time"] < now]
    return {tf: resample(m, tf).tail(bars).reset_index(drop=True) for tf in tfs}
