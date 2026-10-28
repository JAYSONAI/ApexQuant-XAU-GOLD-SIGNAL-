"""ApexQuant-XAU v3 - single-screen signal terminal.

The analysis loop lives in src/monitor.py (a background thread), NOT in this script. This script only
(1) pushes the user's control choices to the monitor and (2) repaints one HTML fragment every 2 s,
so changing a widget never re-runs the analysis and no browser refresh is ever needed.
"""
import streamlit as st

from src import config, llm, monitor, ui

st.set_page_config(page_title="ApexQuant-XAU | Signal Terminal", page_icon="🪙", layout="wide", initial_sidebar_state="collapsed")


@st.cache_resource
def get_monitor():
    m = monitor.Monitor()
    m.start()
    return m


mon = get_monitor()
st.markdown(ui.CSS, unsafe_allow_html=True)

SRC = {"Demo (synthetic)": "demo", "data/ folder": "folder", "MetaTrader 5": "mt5"}
SRC_INV = {v: k for k, v in SRC.items()}

c = st.columns([1.15, 1.5, 1.0, 1.55, 1.1, 0.95, 1.15, 0.45], vertical_alignment="bottom")
c[0].markdown("#### 🪙 ApexQuant‑XAU")
if hasattr(st, "segmented_control"):
    tf = c[1].segmented_control("Analysis timeframe", ["M1", "M5", "M15"], default=mon.s["tf"], key="ui_tf", label_visibility="collapsed") or mon.s["tf"]
else:
    tf = c[1].radio("Analysis timeframe", ["M1", "M5", "M15"], index=["M1", "M5", "M15"].index(mon.s["tf"]), horizontal=True, key="ui_tf", label_visibility="collapsed")
enabled = c[2].toggle("Monitor", value=mon.s["enabled"], key="ui_en")
source = SRC[c[3].selectbox("Data source", list(SRC), index=list(SRC).index(SRC_INV[mon.s["source"]]), key="ui_src", label_visibility="collapsed")]
llm_mode = c[4].selectbox("LLM", ["off", "manual", "auto"], index=["off", "manual", "auto"].index(mon.s["llm_mode"]), key="ui_llm",
                          format_func=lambda x: f"LLM: {x}", label_visibility="collapsed",
                          help="off = never. manual = only when you press Validate. auto = only for high-conviction new signals, with hourly/daily budget.")
run_clicked = c[5].button("▶ Run now", type="primary", use_container_width=True)
val_clicked = c[6].button("🧠 Validate", use_container_width=True, disabled=(llm_mode == "off"), help="Ask the LLM for a second opinion on the active signal (counts toward the budget).")

with c[7].popover("⚙", use_container_width=True):
    prov = st.selectbox("LLM provider", list(llm.PROVIDERS), index=list(llm.PROVIDERS).index(mon.s["provider"]) if mon.s["provider"] in llm.PROVIDERS else 0)
    av = llm.available(mon.cfg)
    st.caption(" · ".join(f"{p}: {'✅' if ok else '❌'}" for p, ok in av.items()) + f" · FRED: {'✅' if mon.cfg['fred_key'] else '❌'}")
    sym = st.text_input("MT5 symbol", mon.s["symbol"])
    btz = st.text_input("Broker time zone (IANA)", mon.s["broker_tz"], help="HFM = Europe/Athens")
    ctz = st.text_input("Calendar time zone", mon.s["cal_tz"], help="ForexFactory CSV export = UTC")
    cal_ov = st.checkbox("Override calendar coverage check", mon.s["cal_override"], help="Only if you are sure no high-impact event is missing.")
    up = st.file_uploader("Replace data/calendar.csv", type="csv")
    if up is not None and st.button("Save calendar"):
        (config.DATA_DIR / "calendar.csv").write_bytes(up.getvalue())
        mon.cal = None
        mon.run_now()
        st.toast("Calendar saved")
    st.caption(f"Signal log: {config.VAR_DIR / 'signals.db'}")

mon.configure(tf=tf, enabled=enabled, source=source, llm_mode=llm_mode, provider=prov, symbol=sym.strip(), broker_tz=btz.strip(),
              cal_tz=ctz.strip(), cal_override=cal_ov)
if run_clicked:
    mon.run_now()
if val_clicked:
    s = mon.snapshot() or {}
    act = s.get("active") or []
    if not act:
        st.toast("No active signal to validate — the engine only validates signals it has produced.")
    else:
        ok, why = mon.request_llm(act[0]["id"], manual=True)
        st.toast("LLM validation queued" if ok else f"Not sent: {why}")


@st.fragment(run_every=2)
def live():
    s = mon.snapshot()
    info = {"enabled": mon.s["enabled"], "llm_calls": mon.llm_calls, "llm_mode": mon.s["llm_mode"]}
    st.html(ui.render(s, mon.cfg, info, mon.store.recent(7), mon.store.stats(), mon.store))


live()
