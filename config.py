"""Loads settings from .env (re-read on every call so edits apply after a dashboard rerun)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VAR_DIR = ROOT / "var"
PROMPT_PATH = ROOT / "prompts" / "system_prompt.md"
VALIDATION_PROMPT_PATH = ROOT / "prompts" / "validation_prompt.md"

# execution TF -> (confirmation TF, context TF)
TF_MAP = {"M1": ("M1", "M15", "H1"), "M5": ("M5", "H1", "H4"), "M15": ("M15", "H1", "H4")}
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}


def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def load():
    load_dotenv(ROOT / ".env", override=True)
    g = lambda k, d="": os.getenv(k, d).strip()
    tf = g("ANALYSIS_TF", "M15").upper()
    return {
        "fred_key": g("FRED_API_KEY"),
        "groq_key": g("GROQ_API_KEY"),
        "groq_model": g("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "openai_key": g("OPENAI_API_KEY"),
        "openai_model": g("OPENAI_MODEL", "gpt-4o"),
        "anthropic_key": g("ANTHROPIC_API_KEY"),
        "anthropic_model": g("ANTHROPIC_MODEL"),
        "gemini_key": g("GEMINI_API_KEY"),
        "gemini_model": g("GEMINI_MODEL", "gemini-2.5-flash"),
        "default_provider": g("DEFAULT_PROVIDER", "groq").lower(),
        "session_start": int(_f("SESSION_START_UTC", 13)),
        "session_end": int(_f("SESSION_END_UTC", 17)),
        "max_spread": _f("MAX_SPREAD_USD", 0.60),
        "max_quote_age": _f("MAX_QUOTE_AGE_SEC", 60),
        "est_cost": _f("EST_COST_USD", 0.0),
        "mt5_symbol": g("MT5_SYMBOL", "XAUUSDb"),
        "spread_mult": _f("SPREAD_P95_MULT", 2.0),
        "offsession_min_conf": _f("OFFSESSION_MIN_CONFIDENCE", 7.5),
        "broker_tz": g("BROKER_TZ", "Europe/Athens"),
        "calendar_tz": g("CALENDAR_TZ", "UTC"),
        "session_mode": g("SESSION_MODE", "auto").lower(),
        "calendar_currencies": [c.strip().upper() for c in g("CALENDAR_CURRENCIES", "USD,ALL").split(",") if c.strip()],
        # ---- v3 engine
        "analysis_tf": tf if tf in TF_MAP else "M15",
        "macro_mode": g("MACRO_MODE", "score").lower(),            # off | score (soft factor) | gate (hard direction filter)
        "fred_max_age_days": _f("FRED_MAX_AGE_DAYS", 10),
        "calendar_min_cover_hours": _f("CALENDAR_MIN_COVER_HOURS", 2),
        "require_spread_baseline": g("REQUIRE_SPREAD_BASELINE", "0") == "1",
        "max_spread_atr": _f("MAX_SPREAD_ATR", 0.12),               # spread must be <= this x exec-TF ATR
        "min_stop_spread_mult": _f("MIN_STOP_SPREAD_MULT", 6),
        "min_conf_trend": _f("MIN_CONF_TREND", 70),
        "min_conf_range": _f("MIN_CONF_RANGE", 72),
        "min_box_conf": _f("MIN_BOX_CONF", 75),                     # range box shown as ARMED only above this
        "min_confluence_trend": int(_f("MIN_CONFLUENCE_TREND", 6)),  # of 10
        "min_confluence_range": int(_f("MIN_CONFLUENCE_RANGE", 8)),  # of 13
        "min_rr_trend": _f("MIN_RR_TREND", 2.0),
        "min_rr_range": _f("MIN_RR_RANGE", 1.8),
        "transition_min_conf": _f("TRANSITION_MIN_CONF", 90),
        "offsession_bump": _f("OFFSESSION_CONF_BUMP", 5),
        "postnews_bump": _f("POSTNEWS_CONF_BUMP", 8),
        "range_lookback": int(_f("RANGE_LOOKBACK", 60)),
        "range_min_width_atr": _f("RANGE_MIN_WIDTH_ATR", 2.5),
        "range_max_width_atr": _f("RANGE_MAX_WIDTH_ATR", 9.0),
        "trend_expiry_bars": int(_f("TREND_EXPIRY_BARS", 8)),
        "range_expiry_bars": int(_f("RANGE_EXPIRY_BARS", 16)),
        "cooldown_bars": int(_f("SIGNAL_COOLDOWN_BARS", 8)),
        # ---- selective LLM
        "llm_mode": g("LLM_MODE", "manual").lower(),                # off | manual | auto
        "llm_min_conf": _f("LLM_MIN_CONF", 80),
        "llm_min_confluence_ratio": _f("LLM_MIN_CONFLUENCE_RATIO", 0.8),
        "llm_max_per_hour": int(_f("LLM_MAX_PER_HOUR", 3)),
        "llm_max_per_day": int(_f("LLM_MAX_PER_DAY", 12)),
        "llm_veto": g("LLM_VETO", "1") == "1",                      # LLM may veto (never originate) a signal
    }


def system_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")


def validation_prompt():
    return VALIDATION_PROMPT_PATH.read_text(encoding="utf-8")
