# Input files (folder mode)

Put your own real data here. Nothing in this folder is auto-generated or sample data.

| File | Format |
|---|---|
| `xauusd_m15.csv`, `xauusd_h1.csv`, `xauusd_h4.csv` | columns `time,open,high,low,close,volume` — `time` = candle OPEN time, oldest first, >= 30 candles |
| `quote.json` | `{"bid": <num>, "ask": <num>, "timestamp": "<ISO8601>", "source": "<name>", "spread_baseline_median": <num>, "spread_baseline_p95": <num>}` |
| `calendar.csv` | the ForexFactory CSV export as-is (`Title,Country,Date,Time,Impact,Forecast,Previous,URL`), or a simple CSV with `time,event,impact,actual,consensus,previous` |

Time zones (all DST-aware, set in `.env` or the sidebar):
- Candles and `quote.json` with no timezone are read as **broker server time** (`BROKER_TZ`, HFM = `Europe/Athens`).
- `calendar.csv` times with no timezone are read in `CALENDAR_TZ` (default `UTC`, which is what the ForexFactory export uses).
- Times with an explicit zone (`...Z`, `+08:00`) are always honored. 12-hour times like `2026-10-23 8:30pm` work; use a full date.
- Calendar columns: `time` (or `time_utc`), `event`, `impact`, `actual`, `consensus`, `previous`.
Missing quote, stale candles, no calendar, or no spread baseline all end in NO TRADE — INSUFFICIENT DATA by design.
Alternatively choose "MetaTrader 5 (read-only)" in the sidebar (Windows, terminal running) to pull quote + candles.

Calendar notes: the ForexFactory export is in UTC (default `CALENDAR_TZ=UTC`). Only `High` impact events for the currencies in `CALENDAR_CURRENCIES` (default USD + ALL) trigger the news freeze. The export has no Actual column, so post-news results cannot be scored from it.
