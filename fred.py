"""FRED retrieval + heuristic macro classification (DFII10, DTWEXBGS). Daily series, never live."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES = {"DFII10": "10Y TIPS real yield", "DTWEXBGS": "Broad trade-weighted USD index"}


def fetch_series(series_id, api_key, limit=120):
    if not api_key:
        raise ValueError("FRED_API_KEY is missing in .env")
    r = requests.get(
        URL,
        params={"series_id": series_id, "api_key": api_key, "file_type": "json",
                "sort_order": "desc", "limit": limit},
        timeout=20,
    )
    r.raise_for_status()
    obs = r.json().get("observations", [])
    df = pd.DataFrame(obs)
    if df.empty:
        raise ValueError(f"No observations returned for {series_id}")
    df = df[["date", "value"]].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    df = df.dropna().sort_values("date").reset_index(drop=True)
    return df, datetime.now(timezone.utc).isoformat()


def analyze(df, retrieved_at):
    v = df["value"].reset_index(drop=True)
    out = {"latest_date": str(df["date"].iloc[-1]), "latest_value": float(v.iloc[-1]),
           "n_obs": int(len(v)), "retrieved_at_utc": retrieved_at,
           "method": "heuristic: change / (std of 1-obs changes * sqrt(n)), last 60 obs"}
    if len(v) < 12:
        out["direction"] = "UNVERIFIED"
        return out
    std = float(v.diff().dropna().tail(60).std())
    zs = []
    for n in (3, 5):
        ch = float(v.iloc[-1] - v.iloc[-1 - n])
        z = ch / (std * np.sqrt(n)) if std > 0 else 0.0
        out[f"chg{n}"], out[f"z{n}"] = ch, z
        zs.append(z)
    score = sum(zs) / 2
    if score >= 1.0 and all(z > 0 for z in zs):
        out["direction"] = "RISING"
    elif score <= -1.0 and all(z < 0 for z in zs):
        out["direction"] = "FALLING"
    else:
        out["direction"] = "STABLE/NOISY"
    out["recent_obs"] = df.tail(8).to_dict("records")
    return out


def classify_macro(ry, usd):
    """Conservative reading of Gate 1.3. Both stable is treated as NEUTRAL (consolidation alone
    is not a directional signal)."""
    a, b = ry.get("direction"), usd.get("direction")
    if "UNVERIFIED" in (a, b) or a is None or b is None:
        return "UNVERIFIED"
    if a == "FALLING" and b in ("FALLING", "STABLE/NOISY"):
        return "BULLISH"
    if b == "FALLING" and a in ("FALLING", "STABLE/NOISY"):
        return "BULLISH"
    if a == "RISING" and b == "RISING":
        return "BEARISH"
    return "NEUTRAL"
