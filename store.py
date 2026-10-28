"""Signal log (SQLite): de-duplication, lifecycle/outcome tracking, empirical hit-rate statistics, LLM call ledger.

Thread-safe (single connection + lock). Use path=':memory:' in tests.
"""
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals(
  id TEXT PRIMARY KEY, created TEXT, bar_time TEXT, tf TEXT, type TEXT, side TEXT, fingerprint TEXT,
  entry REAL, sl REAL, tp1 REAL, tp2 REAL, rr REAL, confidence REAL, regime TEXT, atr REAL,
  status TEXT, outcome TEXT, resolved TEXT, r_mult REAL, expiry_bars INTEGER, payload TEXT, llm TEXT);
CREATE INDEX IF NOT EXISTS ix_sig_status ON signals(status);
CREATE TABLE IF NOT EXISTS llm_calls(ts TEXT, signal_id TEXT, provider TEXT, ok INTEGER, note TEXT);
"""
ACTIVE = "ACTIVE"


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ------------------------------------------------------------------ writes
    def is_duplicate(self, sig, tf_min, cooldown_bars):
        """Same fingerprint that is still ACTIVE, or created within the cooldown, is a repeat alert."""
        with self.lock:
            rows = self.db.execute("SELECT created,status FROM signals WHERE fingerprint=? ORDER BY created DESC LIMIT 5",
                                   (sig["fingerprint"],)).fetchall()
            for r in rows:
                if r["status"] == ACTIVE:
                    return True
                age = pd.Timestamp(sig["bar_time"]) - pd.Timestamp(r["created"])
                if age < pd.Timedelta(minutes=tf_min * cooldown_bars):
                    return True
            # same side/type/tf with a nearby entry while one is still ACTIVE = same idea, not a new one
            r = self.db.execute("SELECT entry,atr FROM signals WHERE status=? AND tf=? AND type=? AND side=?",
                                (ACTIVE, sig["tf"], sig["type"], sig["side"])).fetchall()
            for x in r:
                if abs(x["entry"] - sig["entry"]) < 1.0 * max(x["atr"], sig["atr"]):
                    return True
        return False

    def add(self, sig):
        with self.lock:
            self.db.execute(
                "INSERT INTO signals(id,created,bar_time,tf,type,side,fingerprint,entry,sl,tp1,tp2,rr,confidence,regime,atr,status,expiry_bars,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sig["id"], sig["bar_time"], sig["bar_time"], sig["tf"], sig["type"], sig["side"], sig["fingerprint"], sig["entry"], sig["sl"],
                 sig["tp1"], sig["tp2"], sig["rr"], sig["confidence"], sig.get("regime", ""), sig["atr"], ACTIVE, sig["expiry_bars"],
                 json.dumps(sig, default=str)))
            self.db.commit()

    def set_llm(self, sid, result, provider, ok, note=""):
        with self.lock:
            self.db.execute("UPDATE signals SET llm=? WHERE id=?", (json.dumps(result) if result else None, sid))
            self.db.execute("INSERT INTO llm_calls VALUES(?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), sid, provider, int(ok), note))
            self.db.commit()

    def log_llm_attempt(self, sid, provider, ok, note="", ts=None):
        with self.lock:
            self.db.execute("INSERT INTO llm_calls VALUES(?,?,?,?,?)", ((ts or datetime.now(timezone.utc)).isoformat(), sid, provider, int(ok), note))
            self.db.commit()

    def set_status(self, sid, status, outcome=None, r_mult=None):
        with self.lock:
            self.db.execute("UPDATE signals SET status=?,outcome=?,resolved=?,r_mult=? WHERE id=?",
                            (status, outcome, datetime.now(timezone.utc).isoformat() if status != ACTIVE else None, r_mult, sid))
            self.db.commit()

    # ------------------------------------------------------------------ lifecycle
    def resolve(self, df, tf_min):
        """Walk completed candles after each ACTIVE signal. Conservative: SL wins a same-bar tie.
        Outcome: TP2 / TP1 (TP1 reached before SL) / SL / EXPIRED. R: TP1->rr1, TP2->rr2, SL->-1, EXPIRED->0."""
        changed = []
        step = pd.Timedelta(minutes=tf_min)
        with self.lock:
            for r in self.db.execute("SELECT * FROM signals WHERE status=?", (ACTIVE,)).fetchall():
                if r["tf"] != self._tf_of(tf_min):
                    continue
                t0 = pd.Timestamp(r["bar_time"])
                after = df[df["time"] > t0]
                long_ = r["side"] in ("LONG", "BUY")
                risk = abs(r["entry"] - r["sl"])
                rr1 = abs(r["tp1"] - r["entry"]) / risk
                tp1_hit, outcome, when = False, None, None
                for k, (t, hi, lo) in enumerate(zip(after["time"], after["high"], after["low"])):
                    sl_hit = lo <= r["sl"] if long_ else hi >= r["sl"]
                    t1 = hi >= r["tp1"] if long_ else lo <= r["tp1"]
                    t2 = hi >= r["tp2"] if long_ else lo <= r["tp2"]
                    if sl_hit:
                        outcome, when = ("TP1" if tp1_hit else "SL"), t
                        break
                    if t2:
                        outcome, when = "TP2", t
                        break
                    if t1:
                        tp1_hit = True
                    if k + 1 >= r["expiry_bars"]:
                        outcome, when = ("TP1" if tp1_hit else "EXPIRED"), t
                        break
                if outcome:
                    rm = {"TP2": abs(r["tp2"] - r["entry"]) / risk, "TP1": rr1, "SL": -1.0, "EXPIRED": 0.0}[outcome]
                    self.db.execute("UPDATE signals SET status=?,outcome=?,resolved=?,r_mult=? WHERE id=?",
                                    ("CLOSED", outcome, pd.Timestamp(when).isoformat(), round(rm, 2), r["id"]))
                    changed.append((r["id"], outcome))
            self.db.commit()
        return changed

    @staticmethod
    def _tf_of(tf_min):
        return {1: "M1", 5: "M5", 15: "M15", 60: "H1", 240: "H4"}[tf_min]

    # ------------------------------------------------------------------ reads
    def active(self, tf=None):
        with self.lock:
            q = "SELECT * FROM signals WHERE status=?" + (" AND tf=?" if tf else "") + " ORDER BY created DESC"
            return [dict(r) for r in self.db.execute(q, (ACTIVE, tf) if tf else (ACTIVE,)).fetchall()]

    def recent(self, n=8):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM signals ORDER BY created DESC LIMIT ?", (n,)).fetchall()]

    def get(self, sid):
        with self.lock:
            r = self.db.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
            return dict(r) if r else None

    def llm_calls_since(self, since_ts):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM llm_calls WHERE ts>=?", (since_ts.isoformat(),)).fetchone()["c"]

    def llm_attempted(self, sid):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM llm_calls WHERE signal_id=?", (sid,)).fetchone()["c"]

    def stats(self):
        """Empirical results by type and confidence bucket (only CLOSED, non-expired signals count as decided)."""
        with self.lock:
            rows = [dict(r) for r in self.db.execute("SELECT type,confidence,outcome,r_mult FROM signals WHERE status='CLOSED'").fetchall()]
        df = pd.DataFrame(rows)
        out = {"n_closed": len(df), "buckets": []}
        if df.empty:
            return out
        df = df[df["outcome"] != "EXPIRED"]
        df["win"] = df["outcome"].isin(["TP1", "TP2"])
        df["bucket"] = pd.cut(df["confidence"], [0, 70, 80, 90, 101], labels=["<70", "70-80", "80-90", "90+"], right=False)
        for (ty, b), g in df.groupby(["type", "bucket"], observed=True):
            out["buckets"].append({"type": ty, "bucket": str(b), "n": int(len(g)), "win_rate": round(float(g["win"].mean()), 3),
                                   "avg_r": round(float(g["r_mult"].mean()), 2)})
        out["overall_win_rate"] = round(float(df["win"].mean()), 3) if len(df) else None
        out["overall_avg_r"] = round(float(df["r_mult"].mean()), 2) if len(df) else None
        out["n_decided"] = int(len(df))
        return out
