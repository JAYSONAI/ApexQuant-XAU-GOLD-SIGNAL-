"""Market-data feeds. Every feed exposes: name, is_demo, now(), quote(), candles(tfs, bars), calendar_path.

MT5Feed keeps ONE persistent terminal connection (v2 re-initialised MT5 and re-downloaded 3x300 bars on
every Streamlit rerun). Candles are only fetched when a new bar has closed; quotes are cheap tick reads.
"""
import json
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config, demo, market


class FeedError(RuntimeError):
    pass


class MT5Feed:
    name, is_demo = "MetaTrader 5 (read-only)", False

    def __init__(self, symbol, tz):
        self.symbol, self.tz = symbol.strip(), tz.strip()
        self.lock = threading.Lock()
        self._mt5 = None
        self._base = None, None   # (computed_at, (median, p95))
        self._point = None

    def now(self):
        return datetime.now(timezone.utc)

    def _init(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5
            except ImportError as e:
                raise FeedError("MetaTrader5 package is Windows-only; use the data/ folder or DEMO source") from e
            if not mt5.initialize():
                raise FeedError(f"MT5 initialize failed: {mt5.last_error()}")
            if not mt5.symbol_select(self.symbol, True):
                near = [s.name for s in (mt5.symbols_get("*XAU*") or [])] + [s.name for s in (mt5.symbols_get("*GOLD*") or [])]
                raise FeedError(f"Symbol '{self.symbol}' not found. Gold-like symbols: {near[:10] or 'none'}")
            self._mt5 = mt5
            info = mt5.symbol_info(self.symbol)
            self._point = info.point if info else 0.01
        return self._mt5

    def _spread_baseline(self, now):
        """Session-specific (same UTC hour +-1) median/p95 of the M15 bar spread over the last ~300 bars."""
        at, val = self._base
        if at is not None and (now - at).total_seconds() < 1800:
            return val
        mt5 = self._mt5
        r = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M15, 0, 600)
        val = (None, None)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = market.server_to_utc(pd.to_datetime(d["time"], unit="s"), self.tz)
            sp = d["spread"] * self._point
            hrs = d["time"].dt.hour
            sel = sp[(hrs - now.hour).abs().isin([0, 1, 23])]
            use = sel if len(sel) >= 30 else sp
            val = (float(use.median()), float(use.quantile(0.95)))
        self._base = (now, val)
        return val

    def quote(self):
        with self.lock:
            mt5 = self._init()
            t = mt5.symbol_info_tick(self.symbol)
            if t is None:
                raise FeedError(f"No tick for {self.symbol} (market closed / terminal logged out?)")
            ts = market.server_to_utc(pd.Series([pd.Timestamp(t.time, unit="s")]), self.tz).iloc[0]
            med, p95 = self._spread_baseline(self.now())
            q = {"bid": float(t.bid), "ask": float(t.ask), "timestamp": ts.isoformat(), "source": self.name}
            if med is not None:
                q.update(spread_baseline_median=med, spread_baseline_p95=p95)
            return q

    def candles(self, tfs, bars=400):
        with self.lock:
            mt5 = self._init()
            out = {}
            code = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}
            for tf in tfs:
                r = mt5.copy_rates_from_pos(self.symbol, code[tf], 0, bars)
                if r is None or len(r) == 0:
                    raise FeedError(f"No {tf} rates for {self.symbol}")
                d = pd.DataFrame(r)
                d["time"] = market.server_to_utc(pd.to_datetime(d["time"], unit="s"), self.tz)
                out[tf] = d.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume"]]
            return out

    def close(self):
        if self._mt5:
            self._mt5.shutdown()
            self._mt5 = None


class FolderFeed:
    """data/xauusd_{m1,m5,m15,h1,h4}.csv + data/quote.json. Files are re-read only when their mtime changes."""
    name, is_demo = "data/ folder (CSV)", False

    def __init__(self, folder, tz):
        self.dir, self.tz = folder, tz.strip()
        self._cache = {}

    def now(self):
        return datetime.now(timezone.utc)

    def _cached(self, p, loader):
        if not p.exists():
            return None
        m = p.stat().st_mtime
        c = self._cache.get(p)
        if c and c[0] == m:
            return c[1]
        v = loader(p)
        self._cache[p] = (m, v)
        return v

    def quote(self):
        q = self._cached(self.dir / "quote.json", lambda p: json.loads(p.read_text()))
        if q is None:
            raise FeedError("data/quote.json missing")
        return dict(q)

    def candles(self, tfs, bars=400):
        out = {}
        for tf in tfs:
            d = self._cached(self.dir / f"xauusd_{tf.lower()}.csv", lambda p: market.read_candles(p, self.tz))
            if d is not None:
                out[tf] = d.tail(bars).reset_index(drop=True)
        return out

    def version(self):
        ps = [self.dir / "quote.json"] + list(self.dir.glob("xauusd_*.csv"))
        return max([p.stat().st_mtime for p in ps if p.exists()] or [0])


class DemoFeed:
    """SYNTHETIC data on a simulated clock (speed = simulated minutes per real second). Never mixed with live data."""
    name, is_demo = "DEMO (synthetic - not market data)", True

    def __init__(self, speed=5.0, seed=None, history_days=70, start_back_days=25):
        end = pd.Timestamp.now(tz="UTC").floor("1min")
        self.m1, self.labels = demo.make_m1(60 * 24 * history_days, seed=seed or int(end.value // 10**9) % 1000, end=end)
        self.full = {tf: demo.resample(self.m1, tf) for tf in config.TF_MINUTES}
        self.speed = speed
        self.sim0 = end - pd.Timedelta(days=start_back_days)
        self.real0 = datetime.now(timezone.utc)
        self.end = end
        self.rng = np.random.default_rng(1)

    def set_speed(self, speed):
        t = self.now()
        self.sim0, self.real0, self.speed = t, datetime.now(timezone.utc), speed

    def now(self):
        el = (datetime.now(timezone.utc) - self.real0).total_seconds() * self.speed
        t = self.sim0 + pd.Timedelta(minutes=el)
        if t >= self.end - pd.Timedelta(minutes=5):      # wrap around
            self.real0 = datetime.now(timezone.utc)
            t = self.sim0
        return t

    def quote(self):
        now = self.now()
        last = self.m1[self.m1["time"] < now].iloc[-1]
        sp = float(self.rng.uniform(0.2, 0.32))
        mid = float(last["close"])
        return {"bid": mid - sp / 2, "ask": mid + sp / 2, "timestamp": (now - pd.Timedelta(seconds=1)).isoformat(),
                "spread_baseline_median": 0.24, "spread_baseline_p95": 0.38, "source": "DEMO"}

    def candles(self, tfs, bars=400):
        now = self.now()
        return {tf: self.full[tf][self.full[tf]["time"] < now].tail(bars).reset_index(drop=True) for tf in tfs}

    def calendar(self):
        now = self.now()
        return pd.DataFrame({"time_utc": [now + pd.Timedelta(days=30)], "event": ["demo"], "currency": ["USD"], "impact": ["Low"]})
