
Project Overview

What it does. ApexQuant-XAU is a Streamlit dashboard that evaluates intraday gold (XAUUSD) conditions through a five-gate pipeline: data quality, macro regime (FRED real yields and the broad US dollar index), news risk (ForexFactory calendar), liquidity (live spread and session), and multi-timeframe structure (H4/H1/M15). The first four gates are computed deterministically in Python; only the final structure and risk-geometry judgement is delegated to a large language model (Groq by default, or OpenAI / Anthropic), which receives the gate results as authoritative and cannot override them. The output is a standardised signal card with a verdict and a confidence score — or a precise NO TRADE — <reason>.

Why it was built. Most AI "trading signal" tools always produce a signal and let the model improvise facts. This project inverts that: it treats missing or stale data as a reason to stand aside, keeps everything verifiable in code, and uses the LLM only for the part that genuinely needs interpretation.

Who it is for. Retail and discretionary gold traders who want a disciplined pre-trade checklist; developers and students interested in LLM guardrails, fail-closed design and market-data engineering; and anyone who wants a worked example of combining APIs, time-zone-correct data handling and AI in one tool.

<img width="1915" height="943" alt="Screenshot 2026-10-29 000508" src="https://github.com/user-attachments/assets/dd8eb10c-da57-4428-97ba-846558be8784" />


Key benefits.

Rejects trades for explicit, auditable reasons instead of vague AI prose.
Cannot be "talked into" a signal: failed gates are final.
Correct across broker daylight-saving changes and mixed time zones.
Signal-only and read-only: never places or manages orders.
Runs locally; keys stay in a git-ignored .env.

Features
Feature	What it does
Deterministic gate pipeline	Gates 0–3 computed in Python and passed to the LLM as authoritative
FRED macro filter	DFII10 (10Y real yield) and DTWEXBGS (broad USD) normalised by their own variability; clearly labelled as daily data
News shield	Reads the ForexFactory CSV export; freezes signals from 30 min before to 15 min after High-impact USD events
Liquidity gate	Live spread vs. recent baseline and absolute ceiling; quote freshness; cost-vs-ATR feasibility
DST-aware sessions	London/New York overlap computed from each city's own DST rules
MetaTrader 5 (read-only)	Pulls quote, spread baseline and M15/H1/H4 candles; configurable broker symbol such as XAUUSDb
Time-zone engine	Broker server time, calendar time and UTC handled with IANA zones; survives the repeated hour at DST fall-back
Multi-provider LLM	Groq, OpenAI or Anthropic selectable in the sidebar
Off-session safeguard	Outside the preferred window a setup needs a higher confidence score
Local fallback card	If a gate fails (or the LLM errors) a transparent local card is shown and tokens are saved
One-click Windows launcher	start.bat builds the virtualenv, installs dependencies and opens the dashboard
Automated tests + CI	23 pytest tests, Ruff linting, GitHub Actions on Python 3.10 and 3.12

Tech Stack
Technology	Purpose
Python 3.10+	Core language
Streamlit	Interactive dashboard UI
pandas / NumPy	Candle processing, ATR, swing detection, z-score statistics
requests	FRED REST API client
python-dotenv	Configuration via .env
MetaTrader5 (Python package)	Read-only market data on Windows
Groq, OpenAI, Anthropic SDKs	Pluggable LLM back-ends
zoneinfo + tzdata	DST-correct time-zone conversion
Altair (via Streamlit)	Price chart
pytest	Unit tests (no network, synthetic fixtures only)
Ruff	Linting and import sorting
GitHub Actions	Continuous integration
Mermaid	Architecture diagram in the README
Windows batch	One-click launcher

Folder Structure
ApexQuant-XAU/
├── app.py                  Streamlit dashboard (UI + orchestration)
├── start.bat               One-click Windows launcher
├── requirements.txt        Runtime dependencies
├── requirements-dev.txt    pytest, ruff
├── .env.example            Settings template (copy to .env)
├── src/
│   ├── config.py           .env loading and typed settings
│   ├── fred.py             FRED fetch + macro classification
│   ├── market.py           Candles, ATR, swings, time-zone engine, MT5 (read-only)
│   ├── precheck.py         Gates 0–3, calendar parser, local signal card
│   └── llm.py              Groq / OpenAI / Anthropic client
├── prompts/
│   └── system_prompt.md    The rule book given to the LLM
├── data/                   Your own CSV/JSON inputs (git-ignored)
├── tests/                  pytest suite (23 tests)
├── docs/                   Architecture notes and screenshots
└── .github/                CI workflow, issue and PR templates

Installation Guide
Windows (recommended)

Install Python 3.10 or newer and tick Add Python to PATH.
Download or clone the repository.
Copy .env.example to .env.
Add a free FRED API key and a Groq API key.
Double-click start.bat. The first run creates .venv, installs dependencies and opens http://localhost:8501.

macOS / Linux

bash
git clone https://github.com/YOUR_USERNAME/ApexQuant-XAU.git
cd ApexQuant-XAU
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then edit
streamlit run app.py

MetaTrader 5 access is Windows-only; on other systems use the data/ folder or Upload files source.

Optional – MetaTrader 5: open and log in to the terminal first, set MT5_SYMBOL (for example XAUUSDb) and BROKER_TZ (for example Europe/Athens).

Usage Guide
Open the dashboard and check the sidebar shows ✅ for your keys.
Choose the LLM provider and model (for Groq, a bare ID such as openai/gpt-oss-20b).
Choose a data source: data/ folder, Upload files, or MetaTrader 5 (read-only).
Save your ForexFactory calendar export as data/calendar.csv and tick "I confirm the calendar covers the next 60+ minutes".
Click Fetch FRED now to load the macro panel.
Click ▶ Run analysis.
Read the five gate tiles and the pre-check verdict. If every gate passes, the LLM adds the Gate 4 structure review and a full signal card; otherwise you get a local NO TRADE card explaining which gate blocked.

Example Workflow
It is Friday evening in Manila (≈13:45 UTC). The trader opens MT5 and logs in to the broker account.
They run start.bat; the dashboard opens and shows FRED, Groq and the chosen symbol XAUUSDb.
They export that week's ForexFactory calendar to data/calendar.csv and tick the coverage confirmation.
Fetch FRED now shows real yields falling and the dollar flat → macro bias BULLISH, direction LONG only.
Run analysis pulls the live quote and candles from MT5; the code converts broker time (GMT+3 in summer) to UTC.
Gate results: data PASS, macro BULLISH, news CLEAR (no High-impact USD event nearby), liquidity PASS (spread within 3× the recent p95), session window 12:00–16:00 UTC.
Because every gate passed, the compact summary goes to Groq. The model reviews H4/H1/M15 structure and either approves a LONG setup with an analytical zone, invalidation, target and reward-to-risk ≥ 2.0 — or returns NO TRADE — TECHNICAL INVALIDATION.
The trader reads the card, verifies it independently and makes their own decision. Nothing is ever executed by the app.

Architecture Summary
The app is a thin Streamlit layer over small, testable modules. Data enters through three adapters — FRED (REST), MetaTrader 5 or CSV/JSON (market data), and the ForexFactory CSV (events). Everything is normalised to UTC (market.server_to_utc), validated (freshness, completeness, ordering, duplicates, forming candles dropped), then precheck.build evaluates Gates 0–3 and produces a prefilter verdict. If the verdict is a rejection, a local card is rendered and the LLM is skipped. If it passes, precheck.to_llm_payload builds a compact JSON containing the gate results (marked authoritative), FRED statistics, nearby calendar events and recent candle summaries. llm.run sends it with prompts/system_prompt.md to the selected provider, which performs only Gate 4 and writes the card. The design is fail-closed: any UNVERIFIED input ends in NO TRADE — INSUFFICIENT DATA.

Future Improvements
Backtesting harness for the gate logic, kept separate from live code, with out-of-sample reporting
Scheduled auto-scan that alerts only on approved signals
Tick-based spread baseline instead of bar spreads
Calendar sources that include Actual values for post-news confirmation
Persisted history of signal cards with outcome tracking
Docker image and a cross-platform data adapter
Calibration study to relate confidence scores to observed outcomes
Additional instruments and configurable gate profiles
Unit-test coverage for the FRED statistics and MT5 adapter (mocked)

<img width="1915" height="943" alt="Screenshot 2026-10-29 000508" src="https://github.com/user-attachments/assets/b1659817-f493-4b1e-b1c6-7bf2236892ca" />
Challenges Solved
LLM overconfidence and hallucination: moved every verifiable check into code and made the model's input authoritative; the LLM can only reject or evaluate structure.
Daylight-saving correctness: broker time (GMT+2/+3), US and UK sessions change on different dates; implemented IANA-zone conversion with ambiguous-hour inference so the repeated hour at fall-back stays monotonic.
Messy real-world inputs: parsed the ForexFactory export (month-first dates, 12-hour times, untimed rows) and identified that it is UTC by cross-checking known releases.
Broker symbol differences: configurable symbols (XAUUSDb) with helpful errors listing gold-like symbols.
Noisy spreads: replaced a brittle "spread > p95" rule with a tolerance multiplier and baseline sanity checks.
Stale and forming candles: drops incomplete bars, flags stale feeds and weekends, repairs duplicates and ordering.
Provider quirks: tolerates model IDs pasted with a groq: prefix; unified three SDKs behind one function.
Safe publishing: git-ignored secrets and personal data, CRLF-safe launcher, CI, tests and a clear disclaimer.
