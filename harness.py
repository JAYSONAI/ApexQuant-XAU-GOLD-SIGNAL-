"""Shared replay helpers: build frames/quote/calendar for a simulated 'now' from a synthetic M1 history."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src import config, demo

def make_cfg(**over):
    cfg = config.load()
    cfg.update(macro_mode="off", llm_mode="off", est_cost=0.0, **over)
    return cfg

def calendar_stub(now):
    return pd.DataFrame({"time_utc": [pd.Timestamp(now) + pd.Timedelta(days=30)], "event": ["stub"], "currency": ["USD"], "impact": ["Low"]})

def full_frames(m1, tfs):
    return {tf: demo.resample(m1, tf) for tf in tfs}

def inputs_at(m1, full, now, tfs, bars=400, spread=0.25):
    fr = {tf: full[tf][full[tf]["time"] < now].tail(bars).reset_index(drop=True) for tf in tfs}
    last = m1[m1["time"] < now].iloc[-1]
    mid = float(last["close"])
    q = {"bid": mid - spread / 2, "ask": mid + spread / 2, "timestamp": (now - pd.Timedelta(seconds=2)).isoformat(),
         "spread_baseline_median": 0.22, "spread_baseline_p95": 0.40}
    return fr, q
