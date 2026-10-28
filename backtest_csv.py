"""Replay the engine over YOUR real history to measure hit-rate by confidence bucket.
Export MT5 M1 (or M5) bars to CSV (time,open,high,low,close,volume; broker time) with >= 25 days of history.
  python tests/backtest_csv.py path/to/xauusd_m1.csv --tf M15 --tz Europe/Athens --spread 0.25
Calendar/FRED are not replayed (macro off, no news freeze) -> results are an UPPER bound; exclude known news bars manually."""
import argparse, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
from src import engine, store, config, market

ap = argparse.ArgumentParser(); ap.add_argument("csv"); ap.add_argument("--tf", default="M15"); ap.add_argument("--tz", default="UTC")
ap.add_argument("--spread", type=float, default=0.25); ap.add_argument("--warm-days", type=int, default=20)
a = ap.parse_args()
m1 = market.read_candles(a.csv, a.tz).sort_values("time").reset_index(drop=True)
tfs = config.TF_MAP[a.tf]; full = full_frames(m1, tfs); cfg = make_cfg(analysis_tf=a.tf); st = store.Store(":memory:")
mins = config.TF_MINUTES[a.tf]; t = (m1["time"].iloc[0] + pd.Timedelta(days=a.warm_days)).ceil(f"{mins}min"); end = m1["time"].iloc[-1]; prev = None; n = 0
while t < end - pd.Timedelta(minutes=mins):
    now = t + pd.Timedelta(seconds=5)
    fr, q = inputs_at(m1, full, now, tfs, spread=a.spread)
    prev = engine.analyze(fr, q, calendar_stub(now), None, cfg, a.tf, now, st, "UTC", prev=prev)
    st.resolve(full[a.tf][full[a.tf]["time"] < now], mins); n += 1; t += pd.Timedelta(minutes=mins)
print(f"{n} cycles, {len(st.recent(100000))} signals"); print(json.dumps(st.stats(), indent=1))
