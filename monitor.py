"""Background monitor: continuous analysis that is independent of the browser tab and of Streamlit reruns.

Cadence
  * FULL cycle  - once per CLOSED candle of the selected timeframe (+3 s settle), on timeframe change, on
                  manual 'run now', or when folder data changes. Downloads candles, runs the whole engine.
  * LIGHT cycle - every few seconds: quote only. Refreshes price/spread/news/liquidity gates and closes active
                  signals that hit SL/TP on the live quote. No candle download, no indicators.
LLM validation runs on its own single-worker pool so a slow API never stalls the analysis loop.
"""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import config, engine, feeds, fred, gates, llm, precheck
from .store import Store


class Monitor:
    THREAD_NAME = "goldy-monitor"

    def __init__(self):
        self.cfg = config.load()
        config.VAR_DIR.mkdir(exist_ok=True)
        self.store = Store(config.VAR_DIR / "signals.db")
        self.lock = threading.RLock()
        self.s = {"enabled": True, "tf": self.cfg["analysis_tf"], "source": "demo", "llm_mode": self.cfg["llm_mode"],
                  "provider": self.cfg["default_provider"], "model": "", "cal_override": False,
                  "symbol": self.cfg["mt5_symbol"], "broker_tz": self.cfg["broker_tz"], "cal_tz": self.cfg["calendar_tz"]}
        self.feed = feeds.DemoFeed(speed=config.TF_MINUTES[self.s['tf']] / 3.0)
        self.snap = None
        self.raw = None             # cached raw candles of the last full cycle
        self.err = None
        self.fred_stats, self.fred_at, self.fred_err = None, None, None
        self.cal, self.cal_mtime = None, None
        self.force = True
        self.last_bar_key = None
        self.last_quote_at = 0.0
        self.last_full = None
        self.llm_state = {}        # signal id -> {"status": "pending|done|error", ...}
        self.llm_calls = 0
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="goldy-llm")
        self.stop_ev = threading.Event()
        self.thread = None
        self.version = 0
        self.last_change = ""

    # ------------------------------------------------------------------ control API (called from the UI thread)
    def configure(self, **kw):
        with self.lock:
            changed = {k: v for k, v in kw.items() if self.s.get(k) != v}
            self.s.update(kw)
            if "source" in changed or {"symbol", "broker_tz"} & set(changed):
                self._make_feed()
            if "tf" in changed and getattr(self.feed, "is_demo", False):
                self.feed.set_speed(config.TF_MINUTES[self.s["tf"]] / 3.0)   # demo: one exec bar every ~3 s
            if {"tf", "source", "symbol", "broker_tz", "cal_tz", "cal_override"} & set(changed):
                self.force = True
                self.last_bar_key = None
            return bool(changed)

    def run_now(self):
        self.force = True

    def _make_feed(self):
        src = self.s["source"]
        if hasattr(self.feed, "close"):
            try:
                self.feed.close()
            except Exception:
                pass
        if src == "mt5":
            self.feed = feeds.MT5Feed(self.s["symbol"], self.s["broker_tz"])
        elif src == "folder":
            self.feed = feeds.FolderFeed(config.DATA_DIR, self.s["broker_tz"])
        else:
            self.feed = feeds.DemoFeed(speed=config.TF_MINUTES[self.s["tf"]] / 3.0)
        self.raw, self.snap = None, None

    def start(self):
        for t in threading.enumerate():                       # retire an orphan from a hot-reloaded module
            if t.name == self.THREAD_NAME and getattr(t, "stop_ev", None) is not self.stop_ev:
                t.stop_ev.set()
        self.thread = threading.Thread(target=self._loop, name=self.THREAD_NAME, daemon=True)
        self.thread.stop_ev = self.stop_ev
        self.thread.start()

    def snapshot(self):
        return self.snap

    # ------------------------------------------------------------------ helpers
    def _calendar(self):
        if self.s["source"] == "demo":
            return self.feed.calendar()
        p = config.DATA_DIR / "calendar.csv"
        if not p.exists():
            return None
        m = p.stat().st_mtime
        if m != self.cal_mtime or self.cal is None:
            self.cal = precheck.read_calendar(p, self.s["cal_tz"])
            self.cal_mtime = m
        return self.cal

    def _refresh_fred(self, now):
        if self.cfg["macro_mode"] == "off" or self.s["source"] == "demo" or not self.cfg["fred_key"]:
            return
        if self.fred_at and (now - self.fred_at) < timedelta(hours=6) and self.fred_stats:
            return
        if self.fred_at and (now - self.fred_at) < timedelta(minutes=10) and self.fred_err:
            return
        try:
            stats = {}
            for sid in fred.SERIES:
                df, ts = fred.fetch_series(sid, self.cfg["fred_key"])
                stats[sid] = fred.analyze(df, ts)
            self.fred_stats, self.fred_err = stats, None
        except Exception as e:
            self.fred_err = str(e)
        self.fred_at = now

    # ------------------------------------------------------------------ main loop
    def _loop(self):
        while not self.stop_ev.is_set():
            try:
                if self.s["enabled"]:
                    with self.lock:
                        self._tick()
            except Exception as e:
                self.err = f"{type(e).__name__}: {e}"
                self.last_full = self.last_full or datetime.now(timezone.utc)
                traceback.print_exc()
                self.force = False
                time.sleep(3)
            self.stop_ev.wait(0.5 if getattr(self.feed, "is_demo", False) else 1.0)

    def _tick(self):
        self.cfg = config.load() if int(time.time()) % 30 == 0 else self.cfg   # .env edits apply within ~30 s
        tf, mins = self.s["tf"], config.TF_MINUTES[self.s["tf"]]
        now = pd.Timestamp(self.feed.now())
        bar_key = now.floor(f"{mins}min")
        settle = (now - bar_key).total_seconds() >= 3
        ver = getattr(self.feed, "version", lambda: None)()
        due_full = (self.force or self.snap is None or (bar_key != self.last_bar_key and settle)
                    or (ver is not None and ver != getattr(self, "_ver", None)))
        if due_full:
            self._full(now, tf, bar_key, ver)
        elif time.time() - self.last_quote_at >= (1.0 if self.s["source"] == "demo" else 2.0):
            self._light(now, tf)

    def _inputs(self, now, tf, need_candles=True):
        feed = self.feed
        quote = feed.quote()
        raw = self.raw
        if need_candles:
            raw = feed.candles(config.TF_MAP[tf])
            self.raw = raw
        return quote, raw

    def _full(self, now, tf, bar_key, ver):
        self._refresh_fred(now)
        try:
            quote, raw = self._inputs(now, tf, True)
            err = None
        except Exception as e:
            quote, raw, err = None, {}, f"{type(e).__name__}: {e}"
        cal = self._calendar()
        prev = self.snap
        snap = engine.analyze(raw, quote, cal, self.fred_stats, self.cfg | {"llm_mode": self.s["llm_mode"]}, tf, now,
                              self.store, self.s["broker_tz"], self.s["cal_override"], prev=prev)
        snap["feed_error"] = err
        snap["source"] = self.feed.name
        snap["is_demo"] = self.feed.is_demo
        ex = raw.get(config.TF_MAP[tf][0])
        if ex is not None and len(ex):
            self.store.resolve(ex[ex["time"] + pd.Timedelta(minutes=config.TF_MINUTES[tf]) <= now], config.TF_MINUTES[tf])
        snap["active"] = self.store.active(tf)
        self._attach_llm(snap)
        if snap["events"]:
            self.last_change = f"{now:%H:%M} UTC · " + " | ".join(snap["events"][:2])
        snap["last_change"] = self.last_change
        # selective LLM: deterministic eligibility, then async call
        for s in snap["new_signals"]:
            if self.s["llm_mode"] == "auto":
                self.request_llm(s["id"], now, snap)
        self.err = err
        self.snap = snap
        self.last_bar_key, self.force, self.last_full, self.last_quote_at = bar_key, False, datetime.now(timezone.utc), time.time()
        self._ver = ver
        self.version += 1

    def _light(self, now, tf):
        snap = self.snap
        try:
            quote = self.feed.quote()
        except Exception as e:
            snap["feed_error"] = f"{type(e).__name__}: {e}"
            self.last_quote_at = time.time()
            return
        snap["feed_error"] = None
        tfs = config.TF_MAP[tf]
        G = gates.evaluate(quote, self.raw or {}, tfs, self._calendar(), self.fred_stats, self.cfg, now,
                           self.s["broker_tz"], self.s["cal_override"],
                           atr_exec=(snap.get("regime") or {}).get("atr"))
        q = G["quote"]
        if q:
            snap["price"] = {"bid": q["bid"], "ask": q["ask"], "mid": (q["bid"] + q["ask"]) / 2, "spread": q["ask"] - q["bid"]}
            self._tick_exits(snap, q["bid"], q["ask"], now)
        snap["gates"], snap["blocked"], snap["block_reason"], snap["in_window"], snap["spread"] = \
            G["gates"], G["blocked"], G["block_reason"], G["in_window"], G["spread"]
        snap["active"] = self.store.active(tf)
        self._attach_llm(snap)
        if G["blocked"]:
            snap["verdict"] = f"NO TRADE — {G['block_reason']}"
            snap["why_not"] = G["block_detail"][:3]
        elif snap["active"]:
            snap["verdict"] = f"{snap['active'][0]['type']} {snap['active'][0]['side']} ACTIVE"
        elif snap.get("regime"):
            snap["verdict"] = f"NO SETUP — {snap['regime']['regime'].replace('_', ' ')}"
        snap["ts_quote"] = now
        self.last_quote_at = time.time()
        self.version += 1

    def _tick_exits(self, snap, bid, ask, now):
        """Close ACTIVE signals the moment the live quote crosses SL/TP2 (long exits on bid, short on ask)."""
        for a in self.store.active(self.s["tf"]):
            risk = abs(a["entry"] - a["sl"])
            if a["side"] in ("LONG", "BUY"):
                hit_sl, hit_tp = bid <= a["sl"], bid >= a["tp2"]
            else:
                hit_sl, hit_tp = ask >= a["sl"], ask <= a["tp2"]
            if hit_sl:
                self.store.set_status(a["id"], "CLOSED", "SL", -1.0)
                snap["events"].append(f"{a['type']} {a['side']} stopped out")
                self.last_change = f"{now:%H:%M} UTC · {a['type']} {a['side']} stopped out"
            elif hit_tp:
                self.store.set_status(a["id"], "CLOSED", "TP2", round(abs(a["tp2"] - a["entry"]) / risk, 2))
                self.last_change = f"{now:%H:%M} UTC · {a['type']} {a['side']} hit TP2"
        snap["last_change"] = self.last_change

    # ------------------------------------------------------------------ LLM (selective, async)
    def _attach_llm(self, snap):
        snap["llm_state"] = dict(self.llm_state)
        snap["llm_calls"] = self.llm_calls

    def request_llm(self, sid, now=None, snap=None, manual=False):
        """Queue a validation of ONE existing deterministic signal (auto-trigger or the manual button).
        Auto path applies the confidence/confluence thresholds; manual skips them but never the budget."""
        import json as _j
        mode = self.s["llm_mode"]
        if mode == "off":
            return False, "LLM is off"
        snap = snap or self.snap
        st = self.llm_state.get(sid)
        if st and st["status"] in ("pending", "done"):
            return False, "already requested"
        row = self.store.get(sid)
        if not row:
            return False, "unknown signal"
        sig = _j.loads(row["payload"])
        now = now or pd.Timestamp(self.feed.now())
        c = self.cfg | {"llm_mode": mode}
        if manual:
            c |= {"llm_min_conf": 0, "llm_min_confluence_ratio": 0}
        ok, why = engine.llm_eligible(sig, c, self.store, now)
        if not ok:
            return False, why
        provider = self.s["provider"]
        self.llm_state[sid] = {"status": "pending", "provider": provider, "since": datetime.now(timezone.utc).isoformat()}
        self.pool.submit(self._llm_job, sid, sig, snap, provider, None, now)
        return True, "queued"

    def _llm_job(self, sid, sig, snap, provider, model, now):
        try:
            payload = {
                "signal": {k: sig[k] for k in ("type", "side", "entry", "sl", "tp1", "tp2", "rr", "net_rr", "confidence", "tf")},
                "confluence": [(f["name"], f["ok"], f["note"]) for f in sig["confluence"]["factors"]],
                "reasons": sig["reasons"],
                "regimes": {k: {kk: (round(v, 2) if isinstance(v, float) else v) for kk, v in r.items() if kk in
                                ("regime", "adx", "er", "structure", "vol_state", "atr", "atr_ratio", "sub")}
                            for k, r in (snap.get("regimes") or {}).items()},
                "bias": snap.get("bias"), "macro": snap.get("macro"),
                "levels": {k: [round(l["p"], 2) for l in v] for k, v in (snap.get("levels") or {}).items()},
                "events": snap["gates"]["gate2"], "price": snap.get("price"),
                "box": {k: round(v, 2) for k, v in (sig.get("box") or {}).items() if isinstance(v, (int, float))} or None,
            }
            res = llm.validate(provider, self.s["model"] or llm.default_model(self.cfg, provider), config.validation_prompt(), payload, self.cfg)
            self.store.set_llm(sid, res, provider, True)
            self.llm_calls += 1
            if res["verdict"] == "REJECT" and self.cfg["llm_veto"]:
                self.store.set_status(sid, "VETOED", "LLM_VETO", 0.0)
            self.llm_state[sid] = {"status": "done", "provider": provider, "result": res}
        except Exception as e:
            self.store.log_llm_attempt(sid, provider, False, str(e)[:200])
            self.llm_state[sid] = {"status": "error", "provider": provider, "error": f"{type(e).__name__}: {str(e)[:160]}"}
