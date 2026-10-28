"""Replay the engine bar-by-bar over SYNTHETIC history. Verifies mechanics (regime labelling, de-dup, LLM budget,
no look-ahead) - it does NOT prove profitability. Usage: python tests/replay.py [days] [seed]"""
import json, sys, time
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from harness import *
from src import engine, store, config, indicators as ind

def run(days=40, seed=11, tf="M15", warm_days=20, **over):
    end = pd.Timestamp('2026-10-23 20:00', tz='UTC')
    m1, lab = demo.make_m1(60 * 24 * days, seed=seed, end=end)
    tfs = config.TF_MAP[tf]; full = full_frames(m1, tfs)
    cfg = make_cfg(analysis_tf=tf, **over); st = store.Store(':memory:')
    step = pd.Timedelta(minutes=config.TF_MINUTES[tf])
    t = m1["time"].iloc[0] + pd.Timedelta(days=warm_days); t = t.ceil(f"{config.TF_MINUTES[tf]}min")
    rows, events, ms, prev = [], [], [], None
    truth_map = {"TREND_UP": "TRENDING_UP", "TREND_DOWN": "TRENDING_DOWN", "RANGE": "RANGING", "SHOCK": "SHOCK"}
    llm_ok = 0; llm_calls_old = 0; sup = 0; blocked_hi = 0; n = 0
    while t < end - step:
        now = t + pd.Timedelta(seconds=5)
        fr, q = inputs_at(m1, full, now, tfs)
        s = engine.analyze(fr, q, calendar_stub(now), None, cfg, tf, now, st, 'UTC', prev=prev)
        prev = s; n += 1; ms.append(s["timing_ms"]["total"])
        st.resolve(full[tf][full[tf]["time"] < now], config.TF_MINUTES[tf])
        truth = lab.loc[t - pd.Timedelta(minutes=1)]
        rows.append({"t": t, "truth": truth_map[truth], "pred": s["regime"]["regime"] if s["regime"] else "NA",
                     "vol": s["regime"]["vol_state"] if s["regime"] else "NA", "verdict": s["verdict"]})
        for ns in s["new_signals"]:
            ok, why = engine.llm_eligible(ns, dict(cfg, llm_mode="auto"), st, now)
            if ok:
                llm_ok += 1; st.log_llm_attempt(ns["id"], "test", True, ts=now)
        sup += sum("suppressed" in w for w in s["why_not"])
        if s["regime"] and s["regime"]["allowed"] and not s["blocked"]: llm_calls_old += 1   # v2 policy: LLM whenever pre-check passes on a new candle
        t += step
    df = pd.DataFrame(rows)
    return df, st, ms, llm_ok, llm_calls_old, sup, n, cfg

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    t0 = time.time()
    df, st, ms, llm_ok, old, sup, n, cfg = run(days, seed)
    print(f"cycles={n} wall={time.time()-t0:.0f}s  engine ms mean={np.mean(ms):.0f} p95={np.percentile(ms,95):.0f} max={max(ms):.0f}")
    print(pd.crosstab(df["truth"], df["pred"]))
    print("vol states:", df["vol"].value_counts().to_dict())
    sig = st.recent(10000)
    print("signals:", len(sig), pd.Series([s['type']+' '+s['side'] for s in sig]).value_counts().to_dict())
    print("stats:", json.dumps(st.stats(), indent=1))
    days_span = n / 96
    print(f"signals/day={len(sig)/days_span:.2f}  duplicates suppressed={sup}  LLM-eligible(auto)={llm_ok} -> {llm_ok/days_span:.2f}/day vs v2-style calls on every passing candle={old} ({old/days_span:.0f}/day)")
    df.to_pickle("/tmp/claude-0/-home-claude/dadffd6e-d796-55a2-ac54-8653aaf244e4/scratchpad/replay_df.pkl")
