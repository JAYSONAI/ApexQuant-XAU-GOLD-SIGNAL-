"""Mechanics tests on SYNTHETIC data: causality (no look-ahead), de-dup, LLM gating, regime blocking. Run: python tests/test_core.py"""
import sys, os, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *
from src import engine, store, config, indicators as ind

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
m1, lab = demo.make_m1(60*24*45, seed=5, end=pd.Timestamp('2026-10-23 20:00', tz='UTC'))
tfs = config.TF_MAP['M15']; full = full_frames(m1, tfs); m15 = full['M15']

# 1. causality of indicators: values at bar N identical when 40 future bars are appended
a = ind.enrich(m15.iloc[:1500]); b = ind.enrich(m15.iloc[:1540]).iloc[:1500]
cols = ['atr','adx','ema20','ema50','rsi','er','bbw']
ok(all(np.allclose(a[c].values, b[c].values, equal_nan=True) for c in cols), "indicators are causal (no look-ahead)")
# 2. pivots only use data up to i+k
pv = ind.pivots(m15.iloc[:1500], k=2)
ok(all(p['i'] <= 1500-1-2 for p in pv), "pivots confirmed >= k bars late (no repaint of newest bars)")
# 3. engine ignores the forming bar: appending a partial exec bar changes nothing
cfg = make_cfg(); now = pd.Timestamp('2026-10-10 12:15:05', tz='UTC')
fr, q = inputs_at(m1, full, now, tfs)
s1 = engine.analyze(fr, q, calendar_stub(now), None, cfg, 'M15', now, store.Store(':memory:'), 'UTC')
now2 = now + pd.Timedelta(minutes=7)   # mid-bar: same closed candles, newer quote
fr2, q2 = inputs_at(m1, full, now2, tfs)
s2 = engine.analyze(fr2, q2, calendar_stub(now2), None, cfg, 'M15', now2, store.Store(':memory:'), 'UTC')
ok(s1['regime']['regime'] == s2['regime']['regime'] and s1['bias'] == s2['bias'], "mid-bar rerun gives the same regime/bias (evaluate-on-close)")
# 4. de-dup: identical signal twice -> second suppressed
st = store.Store(':memory:')
sig = dict(type='TREND', side='LONG', tf='M15', bar_time='2026-10-10T12:00:00+00:00', entry=4000., sl=3996., tp1=4006., tp2=4010., rr=2.5,
           confidence=80., atr=3., expiry_bars=8, anchor=3997., fingerprint='x', id='a', confluence={'count':8,'total':10,'factors':[]}, regime='TRENDING_UP')
ok(not st.is_duplicate(sig, 15, 8), "first signal accepted"); st.add(sig)
sig2 = dict(sig, id='b', bar_time='2026-10-10T12:15:00+00:00', fingerprint='y', entry=4001.)
ok(st.is_duplicate(sig2, 15, 8), "near-identical active signal suppressed (different fingerprint, same idea)")
# 5. LLM gating
c = dict(cfg, llm_mode='auto'); now = pd.Timestamp.now(tz='UTC')
ok(not engine.llm_eligible(dict(sig, confidence=75.), c, st, now)[0], "LLM not called below confidence threshold")
ok(engine.llm_eligible(sig, c, st, now)[0], "LLM eligible for 80+ conf / 80% confluence")
for i in range(3): st.log_llm_attempt(f'z{i}', 'p', True, ts=now)
ok(not engine.llm_eligible(sig, c, st, now)[0], "hourly LLM budget enforced")
ok(not engine.llm_eligible(sig, dict(c, llm_mode='off'), st, now)[0], "LLM off respected")
# 6. why-not tally over a 12-day slice + regime/vol blocking
cnt = collections.Counter(); n = 0
t = pd.Timestamp('2026-10-05 00:00', tz='UTC'); stt = store.Store(':memory:')
while t < pd.Timestamp('2026-10-17 00:00', tz='UTC'):
    now = t + pd.Timedelta(seconds=5); fr, q = inputs_at(m1, full, now, tfs)
    s = engine.analyze(fr, q, calendar_stub(now), None, cfg, 'M15', now, stt, 'UTC')
    for w in s['why_not']:
        cnt[re.sub(r'[\d.]+', '#', w)[:90]] += 1
    n += 1; t += pd.Timedelta(minutes=15)
print(f"{n} cycles; top rejection reasons:"); [print(f"  {v:5d}  {k}") for k, v in cnt.most_common(8)]
print("ALL TESTS PASSED")
