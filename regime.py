"""Market regime detection: TRENDING_UP / TRENDING_DOWN / RANGING / TRANSITIONING + volatility state.

Deterministic, points-based, evaluated on completed candles only. A regime is "confirmed" only when
the last two completed bars agree; otherwise it is reported as TRANSITIONING (signals blocked).
"""
import numpy as np
import pandas as pd

from . import indicators as ind

T_ON, R_ON, OPP_MAX = 60, 60, 40   # points needed to call a regime / max points of the opposite regime


def _clip(x, lo=0.0, hi=1.0):
    return float(min(hi, max(lo, x)))


def _score(d, piv, i):
    """Trend and range points (0-100 each) at bar index i of enriched frame d."""
    r = d.iloc[i]
    atr = float(r["atr"]) if r["atr"] > 0 else np.nan
    if not np.isfinite(atr):
        return None
    sep = (r["ema20"] - r["ema50"]) / atr
    slope = (d["ema50"].iloc[i] - d["ema50"].iloc[max(0, i - 10)]) / atr
    struct = ind.structure_from_pivots(piv)
    direction = "UP" if (sep > 0 and r["pdi"] > r["mdi"]) else "DOWN" if (sep < 0 and r["mdi"] > r["pdi"]) else None
    adx, er = float(r["adx"]), float(r["er"]) if np.isfinite(r["er"]) else 0.0

    # --- trend evidence
    t = 30 * _clip((adx - 18) / 10) + 20 * _clip((er - 0.15) / 0.30) + 15 * _clip((abs(sep) - 0.2) / 0.4) \
        + 10 * _clip((abs(slope) - 0.15) / 0.35)
    price_side_ok = (direction == "UP" and r["close"] > r["ema50"]) or (direction == "DOWN" and r["close"] < r["ema50"])
    t += 5 if price_side_ok else 0
    if (direction == "UP" and struct == "BULLISH") or (direction == "DOWN" and struct == "BEARISH"):
        t += 20
    # --- range evidence
    seg = (d["close"].iloc[max(0, i - 29):i + 1] - d["ema50"].iloc[max(0, i - 29):i + 1])
    crosses = int((np.sign(seg).diff().abs() > 0).sum())
    rg = 25 * _clip((22 - adx) / 6) + 20 * _clip((0.35 - er) / 0.15) + 15 * _clip((0.8 - abs(sep)) / 0.5) \
        + 10 * _clip((0.6 - abs(slope)) / 0.35) + (15 if struct == "RANGE" else 0) \
        + (15 if crosses >= 3 else 8 if crosses == 2 else 0)
    return {"trend": round(t, 1), "range": round(rg, 1), "dir": direction, "struct": struct, "adx": adx, "er": er,
            "sep": float(sep), "slope": float(slope), "crosses": crosses, "atr": atr}


def _label(s):
    if s is None:
        return "TRANSITIONING"
    if s["trend"] >= T_ON and s["range"] <= OPP_MAX and s["dir"]:
        return "TRENDING_UP" if s["dir"] == "UP" else "TRENDING_DOWN"
    if s["range"] >= R_ON and s["trend"] <= OPP_MAX:
        return "RANGING"
    return "TRANSITIONING"


def _vol_state(d):
    a = d["atr"]
    base = float(a.tail(100).median())
    ratio = float(a.iloc[-1] / base) if base > 0 else 1.0
    tr = ind.true_range(d).tail(3)
    shock = bool((tr >= 3.0 * d["atr"].shift().tail(3)).any())
    if ratio >= 1.6 or shock:
        return "HIGH", ratio
    if ratio <= 0.65:
        return "LOW", ratio
    return "NORMAL", ratio


def detect(d, k=2, zz_mult=0.8):
    """d: enriched completed-candle frame (>= 80 bars). Returns regime dict (see keys below)."""
    n = len(d)
    if n < 80:
        return {"regime": "UNKNOWN", "reasons": [f"only {n} bars (need >= 80)"], "allowed": [], "vol_state": "UNKNOWN"}
    out = []
    for back in (0, 1):                      # persistence: evaluate at the last bar and the one before
        dd = d.iloc[:n - back]
        piv = ind.pivots(dd, k=k, min_amp=(zz_mult * dd["atr"]).values)
        out.append((_score(dd, piv, len(dd) - 1), piv))
    (s0, piv0), (s1, _) = out
    l0, l1 = _label(s0), _label(s1)
    confirmed = l0 == l1
    regime = l0 if confirmed else "TRANSITIONING"
    vol, ratio = _vol_state(d)
    reasons = []
    if s0:
        reasons.append(f"ADX {s0['adx']:.0f}, ER {s0['er']:.2f}, EMA20-50 gap {s0['sep']:+.2f} ATR, structure {s0['struct']}")
        reasons.append(f"trend pts {s0['trend']:.0f} / range pts {s0['range']:.0f}")
    if not confirmed:
        reasons.append(f"unconfirmed: last bar {l0}, previous {l1}")
    sub = ""
    if regime == "TRANSITIONING" and s0:
        adx_hist = d["adx"].tail(12)
        bbp = ind.pct_rank_last(d["bbw"])
        if adx_hist.max() >= 25 and s0["adx"] < adx_hist.max() - 4:
            sub = "trend exhausting"
        elif bbp <= 0.2 and s0["adx"] > float(d["adx"].iloc[-4]):
            sub = "compression, breakout pending"
        else:
            sub = "mixed signals"
        reasons.append(f"transition: {sub}")
    allowed = []
    if vol == "NORMAL" and confirmed:
        allowed = ["TREND"] if regime.startswith("TRENDING") else ["RANGE"] if regime == "RANGING" else []
    if vol != "NORMAL":
        reasons.append(f"volatility {vol} (ATR x{ratio:.2f} of 100-bar median) - signals blocked")
    return {"regime": regime, "direction": s0["dir"] if s0 else None, "trend_pts": s0["trend"] if s0 else 0,
            "range_pts": s0["range"] if s0 else 0, "adx": s0["adx"] if s0 else None, "er": s0["er"] if s0 else None,
            "structure": s0["struct"] if s0 else "RANGE", "atr": float(d["atr"].iloc[-1]), "atr_ratio": ratio,
            "vol_state": vol, "confirmed": confirmed, "sub": sub, "reasons": reasons, "allowed": allowed,
            "pivots": piv0, "raw_last": l0, "raw_prev": l1}
