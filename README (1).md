ApexQuant-XAU v3 — deterministic gold signal terminal
=====================================================

Run: `start.bat` (Windows) or `pip install -r requirements.txt && streamlit run app.py`. Copy `.env.example` to `.env` first.
Rotate any API key that was ever stored in a shared zip.

How it works
------------
* `src/monitor.py` runs in a background thread. It analyses once per CLOSED candle of the timeframe you pick (M1/M5/M15), and between candles only refreshes the quote, gates and live SL/TP checks. Closing the browser tab does not stop it; stopping the Streamlit server does.
* Decision engine is deterministic: gates (data, macro, news, liquidity) -> regime (trending / ranging / transitioning, volatility) -> strategy (trend pullback only in trends, range fade only in ranges) -> confidence + confluence thresholds -> de-duplication.
* The LLM never creates signals. It can only second-opinion (and veto) a signal the engine already produced: `LLM_MODE=off|manual|auto`, auto needs confidence >= LLM_MIN_CONF and 80% confluence, with hourly/daily budgets.
* Every signal is logged to `var/signals.db` and its outcome (TP1/TP2/SL/expired) is tracked, so the dashboard shows real hit-rates per confidence bucket once 20+ signals are decided. Confidence is a setup-quality score, not a probability, until you have that data.

Sources: DEMO (synthetic, clearly labelled), data/ folder CSV (xauusd_m1/m5/m15/h1/h4.csv + quote.json + calendar.csv), MetaTrader 5 (read-only, Windows).

Before trusting it
------------------
1. Replace `data/calendar.csv` weekly — the engine now refuses to trade when the calendar does not cover the next 2 hours.
2. Set `EST_COST_USD` to your real cost per oz.
3. Run `python tests/backtest_csv.py your_m1_export.csv --tf M15 --tz Europe/Athens` on real history and read the per-bucket results. `python tests/test_core.py` checks the mechanics (no look-ahead, de-dup, LLM gating).
4. Synthetic tests prove mechanics only — not profitability.

Research / signal-only software. It never places orders.
