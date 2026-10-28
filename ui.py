"""HTML rendering for the single-screen dashboard. Pure functions: snapshot dict in, HTML string out."""
import base64
from html import escape as esc

import pandas as pd

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
:root{--bg:#070c15;--card:#0f1726;--card2:#121c2f;--line:rgba(148,163,184,.16);--mut:#8b9bb4;--txt:#e9f0fb;
--cyan:#57e3d0;--gold:#f2c879;--up:#35d69b;--dn:#ff6b6b;--amb:#f2b84b;--pad:clamp(6px,1.1vh,12px);--fs:clamp(11px,1.75vh,16.5px)}
html,body,.stApp{background:var(--bg)!important;color:var(--txt);font-family:'Manrope',sans-serif}
header[data-testid="stHeader"],footer,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important}
.block-container,[data-testid="stMainBlockContainer"]{padding:.35rem .8rem 0!important;max-width:100%!important}
[data-testid="stVerticalBlock"]{gap:.3rem!important}
[data-testid="stHorizontalBlock"]{gap:.5rem!important;align-items:center}
[data-testid="stWidgetLabel"] p{font-size:.68rem!important;color:var(--mut)!important}
div[data-baseweb="select"]>div,[data-testid="stSegmentedControl"] button,[data-testid="stButton"] button{min-height:1.9rem!important;font-size:.76rem!important}
[data-testid="stButton"] button[kind="primary"]{background:linear-gradient(110deg,#39cbb9,#78e9d5);color:#07131b;border:0;font-weight:700}
.aq-wrap{height:calc(100vh - 76px);display:flex;flex-direction:column;gap:6px;font-size:var(--fs);min-height:430px}
.aq-bar{display:flex;gap:14px;align-items:center;flex-wrap:nowrap;white-space:nowrap;overflow:hidden;padding:5px 10px;border:1px solid var(--line);border-radius:9px;background:var(--card);font-family:'DM Mono',monospace;font-size:calc(var(--fs) - 1px);flex:0 0 auto}
.aq-bar b{color:var(--txt);font-weight:500}.aq-bar .m{color:var(--mut)}.aq-bar .grow{flex:1;overflow:hidden;text-overflow:ellipsis;color:var(--gold)}
.aq-demo{background:#5b3a00;color:#ffd27a;border-radius:5px;padding:1px 7px;font-weight:700}
.aq-grid{flex:1;min-height:0;display:grid;gap:6px;grid-template-columns:1.05fr 1.25fr 1.25fr;grid-template-rows:minmax(0,1fr) minmax(0,.95fr)}
.aq-grid.nollm .hist{grid-column:span 2}
.card{background:linear-gradient(160deg,var(--card2),var(--card));border:1px solid var(--line);border-radius:11px;padding:var(--pad);overflow:hidden;min-height:0;display:flex;flex-direction:column;gap:5px}
.card h4{margin:0;font-size:calc(var(--fs) - 2px);letter-spacing:.12em;text-transform:uppercase;color:var(--mut);font-weight:700;display:flex;justify-content:space-between;align-items:center;flex:0 0 auto}
.card h4 span{letter-spacing:0;text-transform:none;font-weight:500}
.big{font-size:clamp(18px,4vh,40px);font-weight:800;letter-spacing:-.03em;line-height:1}
.up{color:var(--up)}.dn{color:var(--dn)}.amb{color:var(--amb)}.mut{color:var(--mut)}.cy{color:var(--cyan)}.gd{color:var(--gold)}
.mono{font-family:'DM Mono',monospace}
.chip{display:inline-block;padding:1px 7px;border-radius:99px;border:1px solid var(--line);font:500 calc(var(--fs) - 2px) 'DM Mono',monospace;white-space:nowrap}
.chip.g{color:var(--up);border-color:#35d69b55;background:#35d69b12}.chip.r{color:var(--dn);border-color:#ff6b6b55;background:#ff6b6b12}.chip.a{color:var(--amb);border-color:#f2b84b55;background:#f2b84b12}.chip.n{color:var(--mut)}
.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.kv{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}
.kv div{background:#0a1220;border:1px solid var(--line);border-radius:7px;padding:3px 6px;min-width:0}
.kv small{display:block;color:var(--mut);font-size:calc(var(--fs) - 3px);text-transform:uppercase;letter-spacing:.06em}
.kv b{font:500 calc(var(--fs) + .5px) 'DM Mono',monospace;white-space:nowrap}
.meter{height:6px;border-radius:9px;background:#0a1220;position:relative;border:1px solid var(--line);flex:0 0 auto}
.meter i{position:absolute;top:-3px;width:3px;height:12px;border-radius:2px;background:var(--txt)}
.meter:before{content:"";position:absolute;left:50%;top:-1px;width:1px;height:6px;background:var(--mut)}
table.t{width:100%;border-collapse:collapse;font-size:calc(var(--fs) - 1px)}
table.t th{color:var(--mut);font-weight:600;text-align:left;font-size:calc(var(--fs) - 3px);text-transform:uppercase;letter-spacing:.05em;padding:2px 4px;border-bottom:1px solid var(--line)}
table.t td{padding:2px 4px;border-bottom:1px solid #ffffff08;font-family:'DM Mono',monospace;white-space:nowrap}
.note{color:var(--mut);font-size:calc(var(--fs) - 1.5px);line-height:1.3;overflow:hidden}
.ring{flex:0 0 auto;width:clamp(54px,9.5vh,92px);height:clamp(54px,9.5vh,92px);position:relative}
.ring b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:600 clamp(13px,2.4vh,22px) 'DM Mono',monospace}
.sig{border:1px solid var(--line);border-radius:9px;padding:6px 8px;background:#0a1220;display:flex;gap:10px;align-items:center;min-height:0}
.sig.long{border-left:3px solid var(--up)}.sig.short{border-left:3px solid var(--dn)}
.ladder{position:relative;margin-right:62px;flex:0 0 clamp(50px,7vw,84px);border-left:1px solid var(--line);border-right:1px solid var(--line)}
.ladder div{position:absolute;left:0;right:0}
.ladder .lbl{font:500 calc(var(--fs) - 3px) 'DM Mono',monospace;color:var(--mut);left:calc(100% + 4px);right:auto;white-space:nowrap;transform:translateY(-50%)}
.chart{position:relative;flex:1;min-height:0}
.chart .lv{position:absolute;right:2px;font:500 calc(var(--fs) - 3px) 'DM Mono',monospace;transform:translateY(-50%);padding:0 3px;border-radius:3px;background:#070c15cc}
.cols{display:flex;gap:8px;flex:1;min-height:0}
.empty{display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:4px;flex:1}
@media(max-width:900px){.aq-wrap{height:auto}.aq-grid{grid-template-columns:1fr;grid-template-rows:none}.aq-grid.nollm .hist{grid-column:auto}.card{min-height:200px}.aq-bar{flex-wrap:wrap;white-space:normal}}
</style>
"""

def _img(svg, style=""):
    """st.html sanitises inline <svg>; a data-URI <img> survives and renders identically."""
    return '<img style="%s" src="data:image/svg+xml;base64,%s"/>' % (style, base64.b64encode(svg.encode()).decode())


def _p(x):
    return "—" if x is None else f"{x:,.2f}"

def _col(v, good=("PASS", "CLEAR", "OK", "BULLISH"), bad=("FAIL", "FREEZE ACTIVE", "UNVERIFIED", "BEARISH")):
    return "g" if v in good else "r" if v in bad else "a"

def _regime_cls(r):
    return "up" if r == "TRENDING_UP" else "dn" if r == "TRENDING_DOWN" else "cy" if r == "RANGING" else "amb"

def _ring(conf, thr):
    if conf is None:
        return '<div class="ring">' + _img('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><circle cx="40" cy="40" r="32" fill="none" stroke="#1b2740" stroke-width="8"/></svg>', "width:100%;height:100%") + '<b class="mut">—</b></div>'
    c = 2 * 3.14159 * 32
    col = "#35d69b" if conf >= thr else "#f2b84b"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"><circle cx="40" cy="40" r="32" fill="none" stroke="#1b2740" stroke-width="8"/>'
           f'<circle cx="40" cy="40" r="32" fill="none" stroke="{col}" stroke-width="8" stroke-linecap="round" stroke-dasharray="{c * conf / 100:.1f} {c:.1f}" transform="rotate(-90 40 40)"/></svg>')
    return f'<div class="ring">{_img(svg, "width:100%;height:100%")}<b>{conf:.0f}</b></div>'

def _ago(ts, created):
    try:
        m = (pd.Timestamp(ts) - pd.Timestamp(created)).total_seconds() / 60
    except Exception:
        return ""
    return f"{m:.0f}m" if m < 90 else f"{m / 60:.1f}h"

# ------------------------------------------------------------------ cards
def card_bias(s, cfg):
    if not s.get("regime"):
        why = esc(s.get("block_reason") or "waiting for data")
        err = esc(str(s.get("feed_error") or ""))
        return f'<div class="card"><h4>Market bias</h4><div class="empty"><div class="big amb">NO DATA</div><div class="note">{why}</div><div class="note">{err}</div></div></div>'
    lab, v = s["bias"]
    cl = "up" if lab == "BULLISH" else "dn" if lab == "BEARISH" else "amb"
    R = s["regime"]
    pos = 50 + 50 * max(-1, min(1, v))
    rows = ""
    for key, tf in zip(("ctx", "conf", "exec"), reversed(s["tfs"])):
        r = s["regimes"].get(key) or {}
        arrow = {"BULLISH": "▲", "BEARISH": "▼"}.get(r.get("structure"), "◆")
        rows += (f'<tr><td class="mut">{tf}</td><td class="{_regime_cls(r.get("regime"))}">{esc(str(r.get("regime", "n/a")).replace("_", " "))}</td>'
                 f'<td>{arrow} {esc(str(r.get("structure", "")))}</td><td>ADX {r.get("adx") or 0:.0f}</td></tr>')
    g = s["gates"]
    chips = (f'<span class="chip {_col(g["gate0"]["status"])}">DATA {g["gate0"]["status"]}</span>'
             f'<span class="chip {_col(g["gate2"]["status"], ("CLEAR",), ("FREEZE ACTIVE", "UNVERIFIED"))}">NEWS {g["gate2"]["status"].replace("POST-NEWS ", "")}</span>'
             f'<span class="chip {_col(g["gate3"]["status"])}">LIQ {g["gate3"]["status"]}</span>'
             f'<span class="chip {"n" if g["gate1"]["status"] in ("OFF", "UNVERIFIED") else _col(g["gate1"]["status"])}">MACRO {g["gate1"]["status"]}</span>')
    nx = g["gate2"].get("next_event")
    nxt = f'<div class="note">Next high-impact: {esc(nx[0])} in {nx[1]:.0f} min</div>' if nx else ""
    sub = f' · {esc(R["sub"])}' if R.get("sub") else ""
    vol = R["vol_state"]
    return f'''<div class="card"><h4>Market bias <span class="mono">{v:+.2f}</span></h4>
<div class="row" style="justify-content:space-between"><div class="big {cl}">{lab}</div><div style="text-align:right"><div class="{_regime_cls(R["regime"])}" style="font-weight:800">{esc(R["regime"].replace("_"," "))}</div><div class="note">{esc(s["tf"])} regime{sub}</div></div></div>
<div class="meter"><i style="left:calc({pos:.0f}% - 1px)"></i></div>
<table class="t"><tr><th>TF</th><th>Regime</th><th>Structure</th><th></th></tr>{rows}</table>
<div class="row"><span class="chip {"g" if vol=="NORMAL" else "r"}">VOL {vol} ×{R["atr_ratio"]:.2f}</span><span class="chip n">ER {R["er"] or 0:.2f}</span><span class="chip n">ATR {R["atr"]:.2f}</span></div>
<div class="row">{chips}</div>{nxt}</div>'''


def card_signal(s, cfg, llm_state):
    act = s.get("active") or []
    a = act[0] if act else None
    thr_t, thr_r = cfg["min_conf_trend"], cfg["min_conf_range"]
    if a:
        import json
        p = json.loads(a["payload"])
        conf = a["confidence"]
        cls = "long" if a["side"] in ("LONG", "BUY") else "short"
        sc = "up" if cls == "long" else "dn"
        c = p["confluence"]
        price = (s.get("price") or {}).get("mid")
        pnl = ""
        if price:
            r = abs(a["entry"] - a["sl"])
            m = (price - a["entry"]) / r * (1 if cls == "long" else -1)
            pnl = f'<span class="chip {"g" if m >= 0 else "r"}">{m:+.2f}R live</span>'
        lv = llm_state.get(a["id"], {})
        lb = ""
        if lv.get("status") == "done":
            v = lv["result"]["verdict"]
            lb = f'<span class="chip {"g" if v == "CONFIRM" else "a" if v == "DOWNGRADE" else "r"}">LLM {v}</span>'
        elif lv.get("status") == "pending":
            lb = '<span class="chip a">LLM …</span>'
        more = f'<div class="note">+{len(act) - 1} more active signal(s) in history</div>' if len(act) > 1 else ""
        thr = thr_t if a["type"] == "TREND" else thr_r
        body = f'''<div class="sig {cls}">{_ring(conf, thr)}<div style="flex:1;min-width:0">
<div class="row"><span class="chip {"cy" if a["type"] == "RANGE" else "gd"}" style="color:var(--{ "cyan" if a["type"]=="RANGE" else "gold"})">{a["type"]}</span><span class="big {sc}" style="font-size:clamp(15px,2.8vh,25px)">{a["side"]}</span>{pnl}{lb}<span class="note">{_ago(s["ts"], a["created"])} ago</span></div>
<div class="kv" style="margin-top:4px"><div><small>Entry</small><b>{_p(a["entry"])}</b></div><div><small>Stop</small><b class="dn">{_p(a["sl"])}</b></div><div><small>TP1</small><b class="up">{_p(a["tp1"])}</b></div><div><small>TP2</small><b class="up">{_p(a["tp2"])}</b></div></div>
<div class="row" style="margin-top:4px"><span class="chip n">R:R {a["rr"]:.1f}</span><span class="chip n">net {p.get("net_rr", 0):.1f}</span><span class="chip n">confluence {c["count"]}/{c["total"]}</span><span class="chip n">{esc(a["regime"].replace("_"," "))}</span></div></div></div>
<div class="note">{esc(" · ".join(p["reasons"][:2]))}</div>{more}'''
    else:
        wn = s.get("why_not") or []
        txt = "".join(f'<div class="note">• {esc(w)}</div>' for w in wn) or '<div class="note">Waiting for a qualifying setup.</div>'
        body = f'''<div class="sig" style="flex:0 0 auto">{_ring(None, 0)}<div><div class="big amb" style="font-size:clamp(14px,2.6vh,22px)">NO ACTIVE SIGNAL</div>
<div class="note">{esc(s["verdict"])}</div><div class="note">Needs ≥{thr_t:.0f} (trend) / ≥{thr_r:.0f} (range) and confluence</div></div></div>{txt}'''
    return f'<div class="card"><h4>Active trade signal <span>{esc(s["tf"])} · evaluated on candle close</span></h4>{body}</div>'


def card_range(s, cfg):
    rs = s.get("range")
    if not rs:
        why = next((w for w in (s.get("why_not") or []) if w.startswith("Range")), None)
        reg = (s.get("regime") or {}).get("regime", "")
        txt = esc(why) if why else (f"Regime is {esc(reg.replace('_', ' '))}: range strategies are disabled." if reg and reg != "RANGING" else "No high-confluence box detected.")
        return f'<div class="card"><h4>Range opportunity <span>quality-gated</span></h4><div class="empty"><div class="big mut" style="font-size:clamp(14px,2.6vh,22px)">NONE QUALIFIED</div><div class="note">{txt}</div><div class="note">Shown only when box confidence ≥{cfg["min_box_conf"]:.0f} and ≥7/10 confluence.</div></div></div>'
    b, z, pl = rs["box"], rs["zones"], rs["plans"]
    price = (s.get("price") or {}).get("mid") or b["mid"]
    lo, hi = b["sup"] - 0.9 * b["atr"], b["res"] + 0.9 * b["atr"]
    y = lambda v: max(0, min(100, (hi - v) / (hi - lo) * 100))
    st = rs["state"]
    stc = {"TRIGGERED": "g", "IN_ZONE": "a", "ARMED": "n"}[st]
    side = rs.get("side")
    ladder = (f'<div class="ladder"><div style="top:{y(z["sell"][1]):.1f}%;height:{y(z["sell"][0]) - y(z["sell"][1]):.1f}%;background:#ff6b6b22"></div>'
              f'<div style="top:{y(z["buy"][1]):.1f}%;height:{y(z["buy"][0]) - y(z["buy"][1]):.1f}%;background:#35d69b22"></div>'
              f'<div style="top:{y(b["res"]):.1f}%;border-top:2px solid var(--dn)"></div><div style="top:{y(b["sup"]):.1f}%;border-top:2px solid var(--up)"></div>'
              f'<div style="top:{y(b["mid"]):.1f}%;border-top:1px dashed var(--mut)"></div>'
              f'<div style="top:{y(price):.1f}%;border-top:2px solid var(--gold);box-shadow:0 0 6px var(--gold)"></div>'
              f'<div class="lbl" style="top:{y(b["res"]):.1f}%">{b["res"]:.2f}</div><div class="lbl" style="top:{y(b["sup"]):.1f}%">{b["sup"]:.2f}</div>'
              f'<div class="lbl gd" style="top:{y(price):.1f}%">▸ {price:.2f}</div></div>')
    def prow(name, z_, p, cls, hl):
        return (f'<tr style="{"background:#ffffff0d" if hl else ""}"><td class="{cls}">{name}</td><td>{z_[0]:.2f}–{z_[1]:.2f}</td>'
                f'<td class="dn">{p["sl"]:.2f}</td><td class="up">{p["tp1"]:.2f}</td><td class="up">{p["tp2"]:.2f}</td><td>{p["rr2"]:.1f}</td></tr>')
    tbl = ('<table class="t"><tr><th></th><th>Zone</th><th>SL</th><th>TP1</th><th>TP2</th><th>R</th></tr>'
           + prow("BUY", z["buy"], pl["BUY"], "up", side == "BUY") + prow("SELL", z["sell"], pl["SELL"], "dn", side == "SELL") + "</table>")
    c = rs["confluence"]
    conf = rs["confidence"] if st != "ARMED" else rs["box_conf"]
    label = "setup" if st != "ARMED" else "box"
    why = "".join(f"<div>• {esc(r)}</div>" for r in rs["reasons"][:3])
    blk = f'<div class="note amb">⚠ {esc(rs["blocked"])}</div>' if rs.get("blocked") else ""
    return f'''<div class="card"><h4>Range opportunity <span><span class="chip {stc}">{st.replace("_"," ")}{" · " + side if side else ""}</span></span></h4>
<div class="cols">{ladder}<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:5px">
<div class="row" style="justify-content:space-between"><div class="kv" style="grid-template-columns:1fr 1fr;flex:1"><div><small>Support</small><b class="up">{b["sup"]:.2f}</b></div><div><small>Resistance</small><b class="dn">{b["res"]:.2f}</b></div></div>
<div style="text-align:center"><div class="mono" style="font-size:clamp(15px,3vh,26px);font-weight:600;color:var(--{"up" if conf >= cfg["min_conf_range"] else "amb"})">{conf:.0f}</div><div class="note" style="line-height:1">{label} conf</div></div></div>
{tbl}<div class="row"><span class="chip n">{c["count"]}/{c["total"]} confluence</span><span class="chip n">{b["t_sup"]}S/{b["t_res"]}R tests</span><span class="chip n">width {b["width_atr"]:.1f} ATR</span>{f'<span class="chip n">net R {rs["net_rr"]:.1f}</span>' if rs.get("net_rr") else ""}</div>
<div class="note">{why}</div>{blk}</div></div></div>'''


def _spark(s):
    sp, lv = s.get("spark"), s.get("levels")
    if not sp:
        return ""
    c, e20 = sp["c"], sp["e20"]
    price = (s.get("price") or {}).get("mid") or c[-1]
    cand = [l for l in (lv["resistance"] + lv["support"])] if lv else []
    lo, hi = min(c), max(c)
    pad = (hi - lo) * 0.08 or 1
    near = [l for l in cand if lo - 3 * pad <= l["p"] <= hi + 3 * pad]
    lo = min([lo] + [l["p"] for l in near]) - pad
    hi = max([hi] + [l["p"] for l in near]) + pad
    n = len(c)
    X = lambda i: i / (n - 1) * 1000
    Y = lambda v: (hi - v) / (hi - lo) * 100
    line = " ".join(f"{X(i):.1f},{Y(v):.2f}" for i, v in enumerate(c))
    em = " ".join(f"{X(i):.1f},{Y(v):.2f}" for i, v in enumerate(e20))
    lines, labels = "", ""
    for l in near:
        res = l["p"] > price
        col = "#ff6b6b" if res else "#35d69b"
        lines += f'<line x1="0" x2="1000" y1="{Y(l["p"]):.2f}" y2="{Y(l["p"]):.2f}" stroke="{col}" stroke-width="{1 + min(l["w"], 6) / 3:.1f}" stroke-dasharray="6 5" opacity=".75" vector-effect="non-scaling-stroke"/>'
        labels += f'<div class="lv" style="top:{Y(l["p"]):.1f}%;color:{col}">{l["p"]:.2f}</div>'
    lines += f'<line x1="0" x2="1000" y1="{Y(price):.2f}" y2="{Y(price):.2f}" stroke="#f2c879" stroke-width="1" opacity=".9" vector-effect="non-scaling-stroke"/>'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 100" preserveAspectRatio="none">{lines}'
           f'<polyline points="{em}" fill="none" stroke="#6b7fa6" stroke-width="1" vector-effect="non-scaling-stroke" opacity=".7"/>'
           f'<polyline points="{line}" fill="none" stroke="#57e3d0" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>')
    return f'<div class="chart">{_img(svg, "position:absolute;inset:0;width:100%;height:100%")}{labels}</div>'


def card_levels(s):
    lv = s.get("levels")
    body = _spark(s)
    if lv:
        def chips(lst, cls):
            return "".join(f'<span class="chip {cls}">{l["p"]:.2f} <span class="mut">{"●" * min(int(l["w"]), 5)}</span></span>' for l in lst) or '<span class="note">none nearby</span>'
        body += (f'<div class="row"><span class="note" style="width:1.6em">R</span>{chips(lv["resistance"], "r")}</div>'
                 f'<div class="row"><span class="note" style="width:1.6em">S</span>{chips(lv["support"], "g")}</div>')
    return f'<div class="card"><h4>Key support &amp; resistance <span>{esc(s["tf"])} · EMA20 grey · ●=strength</span></h4>{body}</div>'


def card_history(s, recent, stats):
    rows = ""
    cls = {"TP2": "g", "TP1": "g", "SL": "r", "EXPIRED": "n", "LLM_VETO": "a", None: "a"}
    for r in recent:
        out = r["outcome"] if r["status"] != "ACTIVE" else None
        label = "ACTIVE" if r["status"] == "ACTIVE" else r["outcome"].replace("LLM_VETO", "VETOED")
        rm = "" if r["r_mult"] is None else "%+.1fR" % r["r_mult"]
        rows += (f'<tr><td class="mut">{pd.Timestamp(r["created"]):%m-%d %H:%M}</td><td>{r["tf"]}</td><td>{r["type"][:5]}</td>'
                 f'<td class="{"up" if r["side"] in ("LONG","BUY") else "dn"}">{r["side"]}</td><td>{r["entry"]:.2f}</td><td>{r["confidence"]:.0f}</td>'
                 f'<td><span class="chip {cls.get(out, "a")}">{label}</span></td><td>{rm}</td></tr>')
    if not rows:
        rows = '<tr><td colspan="8" class="note">No signals yet — the engine is built to stay silent in low-quality conditions.</td></tr>'
    n = stats.get("n_decided", 0)
    if n >= 20:
        st = f'{n} decided · win {stats["overall_win_rate"] * 100:.0f}% · avg {stats["overall_avg_r"]:+.2f}R'
    else:
        st = f'calibrating: {n} decided signals (need 20+ before reading hit-rates)'
    return (f'<div class="card hist"><h4>Recent signal history <span>{st}</span></h4>'
            f'<table class="t"><tr><th>Time</th><th>TF</th><th>Type</th><th>Side</th><th>Entry</th><th>Conf</th><th>Result</th><th>R</th></tr>{rows}</table></div>')


def card_llm(s, llm_state, store):
    items = [(sid, st) for sid, st in llm_state.items()]
    if not items:
        return ""
    sid, st = items[-1]
    row = store.get(sid)
    head = f'{esc(row["type"])} {esc(row["side"])} @ {row["entry"]:.2f}' if row else esc(sid)
    if st["status"] == "pending":
        body = '<div class="empty"><div class="big amb" style="font-size:clamp(14px,2.6vh,22px)">VALIDATING…</div><div class="note">Second opinion requested for this signal only.</div></div>'
    elif st["status"] == "error":
        body = f'<div class="note dn">LLM call failed: {esc(st["error"])}</div><div class="note">The deterministic signal is unaffected. One retry is allowed; failures never loop.</div>'
    else:
        r = st["result"]
        cl = {"CONFIRM": "up", "DOWNGRADE": "amb", "REJECT": "dn"}[r["verdict"]]
        risks = "".join(f"<div>• {esc(x)}</div>" for x in r["risks"])
        body = (f'<div class="row"><div class="big {cl}" style="font-size:clamp(15px,2.8vh,25px)">{r["verdict"]}</div>'
                f'<span class="chip n">conf {r["confidence_adjustment"]:+d}</span></div><div class="note" style="color:var(--txt)">{esc(r["rationale"])}</div>'
                f'<div class="note">{risks}</div>')
    return f'<div class="card"><h4>LLM validation <span>{esc(st.get("provider", ""))} · {head}</span></h4>{body}</div>'


def bar(s, mon_info):
    p = s.get("price")
    demo = '<span class="aq-demo">DEMO · SYNTHETIC DATA</span>' if s.get("is_demo") else ""
    px = f'<b>{p["bid"]:.2f}</b><span class="m">/</span><b>{p["ask"]:.2f}</b> <span class="m">sp {p["spread"]:.2f}</span>' if p else '<span class="m">no quote</span>'
    bt = s.get("bar_time")
    cyc = (s.get("timing_ms") or {}).get("total")
    return (f'<div class="aq-bar">{demo}<span class="m">XAUUSD</span>{px}<span class="m">bar</span><b>{pd.Timestamp(bt):%H:%M}Z</b>'
            f'<span class="m">monitor</span><b class="{"up" if mon_info["enabled"] else "amb"}">{"LIVE" if mon_info["enabled"] else "PAUSED"}</b>'
            f'<span class="m">LLM calls</span><b>{mon_info["llm_calls"]}</b><span class="m">cycle</span><b>{cyc if cyc is not None else "—"} ms</b>'
            f'<span class="grow">{esc(s.get("last_change") or "no changes yet")}</span></div>') if bt is not None else \
        f'<div class="aq-bar">{demo}<span class="m">XAUUSD</span>{px}<span class="grow">{esc(str(s.get("feed_error") or s.get("block_reason") or "waiting for first closed candle"))}</span></div>'


def render(s, cfg, mon_info, recent, stats, store):
    if s is None:
        return '<div class="aq-wrap"><div class="aq-bar"><span class="grow">Starting monitor…</span></div></div>'
    ls = s.get("llm_state") or {}
    llm_html = card_llm(s, ls, store) if mon_info["llm_mode"] != "off" and ls else ""
    grid = "aq-grid" + ("" if llm_html else " nollm")
    return (f'<div class="aq-wrap">{bar(s, mon_info)}<div class="{grid}">'
            f'{card_bias(s, cfg)}{card_signal(s, cfg, ls)}{card_range(s, cfg)}'
            f'{card_levels(s)}{card_history(s, recent, stats)}{llm_html}</div></div>')
