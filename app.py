"""IPO Radar v4 — insight-first recent-IPO alpha platform."""
import json
import os

import numpy as np
import pandas as pd
import streamlit as st

DATA = os.path.join(os.path.dirname(__file__), "data")
st.set_page_config(page_title="IPO Radar", page_icon="🎯", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.1rem; max-width: 1450px;}
.hero {background: linear-gradient(120deg,#0f2027,#203a43,#2c5364); border-radius: 14px;
  padding: 18px 26px; color: white; margin-bottom: 10px;}
.hero h1 {margin: 0; font-size: 1.7rem;} .hero p {margin: 4px 0 0; opacity: .85; font-size: .9rem;}
.badge {display:inline-block; padding:3px 12px; border-radius:12px; font-weight:700; font-size:.78rem;}
.b-TRIGGER {background:#16a34a; color:white;} .b-SETUP {background:#f59e0b; color:#1a1a1a;}
.b-RIDE {background:#0ea5e9; color:white;} .b-AVOID {background:#dc2626; color:white;}
.b-NEUTRAL {background:#6b7280; color:white;}
.card {border:1px solid #e5e7eb; border-radius:14px; padding:16px 20px; margin-bottom:12px;
  box-shadow:0 1px 4px rgba(0,0,0,.06);}
.card h3 {margin:0 0 2px; font-size:1.12rem;} .card .sub {color:#6b7280; font-size:.8rem; margin-bottom:6px;}
.card ul {margin:6px 0 0 2px; padding-left:18px;} .card li {margin-bottom:4px; font-size:.88rem; line-height:1.45;}
.plan {display:flex; gap:14px; margin-top:8px; flex-wrap:wrap;}
.plan div {background:#f3f4f6; border-radius:10px; padding:7px 14px; font-size:.82rem;}
.plan b {display:block; font-size:1rem;}
.lnk {display:inline-block; margin:4px 8px 0 0; padding:4px 12px; border-radius:8px;
  font-size:.8rem; font-weight:600; text-decoration:none; border:1px solid #d1d5db;}
.lnk.f {background:#eef6ff; color:#1d4ed8;} .lnk.t {background:#f0fdf4; color:#15803d;}
.metricrow {display:flex; gap:12px; flex-wrap:wrap; margin-bottom:4px;}
.metricrow .m {flex:1; min-width:130px; background:#f8fafc; border:1px solid #e2e8f0;
  border-radius:12px; padding:10px 14px; text-align:center;}
.m b {font-size:1.35rem; display:block;} .m span {font-size:.74rem; color:#64748b;}
.insight {background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:12px 18px;
  margin:10px 0; font-size:.9rem; line-height:1.55;}
.insight b {color:#92400e;}
[data-testid="stDataFrame"] {border:1px solid #e5e7eb; border-radius:12px;}
</style>
""", unsafe_allow_html=True)

H = {
    "reco": "The ACTION: FRESH BUY = pivot just reclaimed, enterable now. BUY-SETUP = basing within 10% of pivot, watch for the close above it. RIDE = already above pivot, manage only. EXIT = lost pivot and 20-EMA. WATCH = too early / middling. AVOID = failed pivot >25 sessions or broken base.",
    "score": "CONVICTION (0–100): structure 35, base 20, liquidity 15, institutions 15, lock-in 5, LM 5, momentum 5. Compare scores WITHIN a reco, not across recos — a RIDE can outscore a FRESH BUY because it has had more time to prove itself.",
    "pivot": "The listing-day HIGH — the study's dividing line. First close above it within 25 sessions is the entry with edge.",
    "cmp": "Latest close from official NSE/BSE bhavcopy (primary = higher-turnover exchange).",
    "dist": "How far CMP sits below (+) or above (−) the pivot.",
    "qib": "QIB subscription multiple. Scoring input (high-QIB names had the biggest tails); no longer a hard filter — the backtest showed the stop manages risk better than exclusion.",
    "adv": "Average daily turnover, last 20 sessions (₹ crore).",
    "ff": "Average daily VOLUME as % of free float (float = shares × (1 − promoter %), from Screener). >4%: crowded/manipulable. 0.8–4%: healthy churn. <0.8%: sleepy.",
    "base": "Lowest low since listing vs listing close. > −10% (the grid-search optimum) = accumulation.",
    "bo_day": "Session when price first closed above the pivot. ≤25 valid; later reclaims historically failed.",
    "entry": "= the pivot. Buy the first daily close above it.",
    "stop": "Higher of base low (setup falsification level) or entry −8% (O'Neil cap) — whichever risks less.",
    "target": "Entry +15% → take partial, trail the rest (winners run ~9 months median).",
    "rr": "(Target − Entry) / (Entry − Stop).",
    "vs_issue": "CMP vs IPO issue price (%).",
    "peak": "Lifetime high vs issue (%).",
    "maxdd": "Worst close-to-close drawdown since listing.",
    "thrust": "Volume-thrust day: volume ≥5× the trailing 20-day average — the institutional footprint. 100% of the big winners printed at least one.",
    "thrust_last": "Most recent volume-thrust date. A thrust in the last 5 sessions is flagged 🔥 on the Today tab.",
    "lm_score": "0–100 on POST-listing outcomes: median now-vs-issue 35%, share above issue 25%, pivot-reclaim rate 20%, drawdown control 20%.",
    "d1gain": "Listing-day close vs issue (%).",
    "a90": "Anchor 90-day lock-in expiry — the worse supply window (−2.4% median drift into it).",
    "mcap": "Market cap (₹ cr, Screener).", "prom": "Promoter holding % (Screener).",
}


def _data_version():
    return max(os.path.getmtime(os.path.join(DATA, f))
               for f in os.listdir(DATA) if f.endswith((".csv", ".json", ".parquet")))


@st.cache_data(ttl=900)
def load(_v=None):
    sig = pd.read_csv(os.path.join(DATA, "signals.csv"))
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    stats = json.load(open(os.path.join(DATA, "study_stats.json")))
    ladder = pd.read_csv(os.path.join(DATA, "rule_ladder.csv"))
    sc = pd.read_csv(os.path.join(DATA, "lm_scorecard.csv"))
    win = pd.read_csv(os.path.join(DATA, "winners.csv"))
    return sig, ana, panel, stats, ladder, sc, win


sig, ana, panel, stats, ladder, scorecard, winners = load(_data_version())
last_date = pd.Timestamp(panel["date"].max()).date()

st.markdown(f"""
<div class="hero"><h1>🎯 IPO Radar</h1>
<p>Every NSE + BSE IPO (mainboard + SME) since <b>{stats.get('universe_start','2023-07-01')}</b> ·
{len(sig)} tracked ({int((sig['board']=='Mainboard').sum())} mainboard, {int((sig['board']=='SME').sum())} SME) ·
prices to <b>{last_date}</b> · self-updating daily · strategy: <b>Pivot Reclaim</b>
(walk-forward validated: PF 1.95 out-of-sample)</p></div>
""", unsafe_allow_html=True)

n = sig["reco"].value_counts()
st.markdown(f"""
<div class="metricrow">
<div class="m"><b style="color:#16a34a">{n.get('FRESH BUY',0)}</b><span>FRESH BUY</span></div>
<div class="m"><b style="color:#f59e0b">{n.get('BUY-SETUP',0)}</b><span>BUY-SETUP</span></div>
<div class="m"><b style="color:#0ea5e9">{n.get('RIDE',0)}</b><span>RIDE</span></div>
<div class="m"><b style="color:#8b5cf6">{n.get('EXIT',0)}</b><span>EXIT</span></div>
<div class="m"><b style="color:#dc2626">{n.get('AVOID',0)}</b><span>AVOID</span></div>
<div class="m"><b style="color:#6b7280">{n.get('WATCH',0)}</b><span>WATCH</span></div>
</div>
""", unsafe_allow_html=True)

T = st.tabs(["📌 Today", "🎯 Opportunities", "🧾 Stock Dossier",
             "🏆 Winners Lab", "🏦 Lead Managers", "📊 Study & Method"])

LINKCOLS = {
    "screener_url": st.column_config.LinkColumn("Fundamentals", display_text="Screener ↗"),
    "tradingview_url": st.column_config.LinkColumn("Chart", display_text="TV ↗"),
}


def card(r):
    reasons = "".join(f"<li>{x.strip()}</li>" for x in str(r["reasons"]).split("•") if x.strip())
    plan = ""
    if pd.notna(r["entry"]):
        plan = f"""<div class="plan">
          <div><span>Entry (pivot)</span><b>₹{r['entry']:,.2f}</b></div>
          <div><span>Stop — {r['stop_basis']}</span><b>₹{r['stop']:,.2f}</b></div>
          <div><span>Target-1 (+15%, then trail)</span><b>₹{r['target']:,.2f}</b></div>
          <div><span>Risk:Reward</span><b>{r['rr'] if pd.notna(r['rr']) else '—'}</b></div>
          <div><span>Time stop</span><b>60 sessions</b></div></div>"""
    analog_html = ""
    if isinstance(r.get("analogs"), str) and r["analogs"]:
        items = "".join(f"<li>{x.strip()}</li>" for x in r["analogs"].split("|"))
        analog_html = (f'<div style="margin-top:8px;font-size:.82rem"><b>🧬 Closest historical analogs</b> '
                       f'<span style="color:#6b7280">(pattern recognition, not prophecy)</span><ul>{items}</ul></div>')
    links = ""
    if isinstance(r["screener_url"], str) and r["screener_url"]:
        links += f'<a class="lnk f" href="{r["screener_url"]}" target="_blank">📊 Fundamentals — Screener</a>'
    if isinstance(r["tradingview_url"], str) and r["tradingview_url"]:
        links += f'<a class="lnk t" href="{r["tradingview_url"]}" target="_blank">📈 Chart — TradingView</a>'
    st.markdown(f"""
    <div class="card">
      <span class="badge b-{r['state']}">{r['reco']}</span>
      <span style="margin-left:8px;font-weight:700;color:#334155">Score {int(r['score'])}/100</span>
      <h3>{r['company']} <span style="font-weight:400;color:#6b7280">({r['symbol']} · {r['board']})</span></h3>
      <div class="sub">Listed {r['listing_date']} · {int(r['days_listed'])} sessions · CMP ₹{r['cmp']:,.2f} · pivot ₹{r['pivot']:,.2f}</div>
      <ul>{reasons}</ul>{plan}{analog_html}{links}
    </div>""", unsafe_allow_html=True)


# ============================================================ TODAY
with T[0]:
    st.markdown(f"""<div class="insight">
    <b>How to read this platform:</b> <b>RECO is the action</b> (what to do), <b>SCORE is conviction</b>
    (quality of the situation, 0–100). Compare scores <i>within</i> a reco — a RIDE often outscores a
    FRESH BUY simply because it has already proven itself; that does not make it a better fresh entry.
    Buy candidates live in FRESH BUY (act) and BUY-SETUP (stalk). Everything self-updates each trading day.
    </div>""", unsafe_allow_html=True)

    thr = sig[sig["thrust_recent"] == True]  # noqa: E712
    upcoming = []
    for k, label in (("anchor_30d", "30-day"), ("anchor_90d", "90-day")):
        s2 = sig[pd.to_datetime(sig[k], errors="coerce").between(
            pd.Timestamp(last_date), pd.Timestamp(last_date) + pd.Timedelta(days=10))]
        for _, r in s2.iterrows():
            upcoming.append({"company": r["company"], "reco": r["reco"], "window": label,
                             "expiry": r[k], "cmp_vs_issue_pct": r["cmp_vs_issue_pct"]})
    fresh, setup = sig[sig["reco"] == "FRESH BUY"], sig[sig["reco"] == "BUY-SETUP"]
    exits = sig[(sig["reco"] == "EXIT") & (sig["dist_to_pivot_pct"].abs() <= 8)]
    st.markdown(f"""<div class="insight"><b>Today's radar:</b>
    {len(fresh)} fresh buy{'s' if len(fresh)!=1 else ''} · {len(setup)} setups stalking the pivot ·
    🔥 {len(thr)} volume thrusts in the last 5 sessions (the winners' footprint) ·
    ⏳ {len(upcoming)} anchor lock-ins expiring within 10 days ·
    🚪 {len(exits)} names that just lost their pivot.</div>""", unsafe_allow_html=True)

    if len(fresh) == 0 and len(setup) == 0:
        st.info("No fresh entries today — the edge is in the waiting. Check 🔥 thrusts below for early footprints.")
    for _, r in pd.concat([fresh, setup]).iterrows():
        card(r)

    st.markdown("##### 🔥 Recent volume thrusts (last 5 sessions) — institutional footprints")
    st.caption("100% of historical big winners printed a ≥5× volume day. A thrust is not a buy signal by itself — it earns a place on your watchlist. Sort any column.")
    tt = thr.sort_values("last_thrust_date", ascending=False)
    st.dataframe(tt[["reco", "score", "company", "board", "last_thrust_date", "thrust_count",
                     "cmp", "cmp_vs_issue_pct", "dist_to_pivot_pct", "adv_cr", "ff_vol_pct",
                     "screener_url", "tradingview_url"]],
                 use_container_width=True, hide_index=True, height=320, column_config={
            "reco": st.column_config.TextColumn("Reco", help=H["reco"]),
            "score": st.column_config.NumberColumn("Score", help=H["score"]),
            "company": "Company", "board": "Board",
            "last_thrust_date": st.column_config.TextColumn("Last thrust", help=H["thrust_last"]),
            "thrust_count": st.column_config.NumberColumn("# thrusts", help=H["thrust"]),
            "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
            "cmp_vs_issue_pct": st.column_config.NumberColumn("vs Issue %", format="%.1f%%", help=H["vs_issue"]),
            "dist_to_pivot_pct": st.column_config.NumberColumn("To pivot %", format="%.1f%%", help=H["dist"]),
            "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.2f", help=H["adv"]),
            "ff_vol_pct": st.column_config.NumberColumn("Vol/Float %", format="%.2f%%", help=H["ff"]),
            **LINKCOLS})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### ⏳ Anchor lock-ins expiring ≤10 days")
        st.caption("Median drift −2.4% into the 90-day expiry. No fresh entries into these windows.")
        if upcoming:
            st.dataframe(pd.DataFrame(upcoming), use_container_width=True, hide_index=True)
        else:
            st.write("None in the next 10 days.")
    with c2:
        st.markdown("##### 🚪 Just lost the pivot (EXIT flags near the level)")
        st.caption("Names that had broken out but now closed below pivot AND 20-EMA — the exit rule.")
        if len(exits):
            st.dataframe(exits[["company", "board", "cmp", "pivot", "cmp_vs_issue_pct", "score"]],
                         use_container_width=True, hide_index=True)
        else:
            st.write("None flagged today.")

# ============================================================ OPPORTUNITIES
with T[1]:
    c1, c2, c3, c4, c5, c6 = st.columns([2, 1.8, 1.2, 1.2, 1.2, 1.2])
    q = c1.text_input("🔎 Search any stock", placeholder="Company / symbol…")
    f_reco = c2.multiselect("Reco", ["FRESH BUY", "BUY-SETUP", "RIDE", "WATCH", "EXIT", "AVOID"],
                            default=["FRESH BUY", "BUY-SETUP", "RIDE", "WATCH", "EXIT", "AVOID"],
                            help=H["reco"])
    f_board = c3.multiselect("Board", ["Mainboard", "SME"], default=["Mainboard", "SME"])
    f_score = c4.slider("Min score", 0, 100, 0, help=H["score"])
    f_adv = c5.slider("Min ADV ₹cr", 0.0, 25.0, 0.0, 0.5, help=H["adv"])
    f_year = c6.multiselect("Listed", sorted(sig["listing_date"].str[:4].unique()),
                            default=sorted(sig["listing_date"].str[:4].unique()))
    e = sig[sig["reco"].isin(f_reco) & sig["board"].isin(f_board) & (sig["score"] >= f_score) &
            (sig["adv_cr"].fillna(0) >= f_adv) & sig["listing_date"].str[:4].isin(f_year)]
    if q:
        e = sig[sig["company"].str.contains(q, case=False, na=False) |
                sig["symbol"].astype(str).str.contains(q, case=False, na=False)]
    st.caption(f"{len(e)} stocks. Every tracked IPO is here — filter by reco to see EXIT / AVOID / WATCH cohorts. Hover ⓘ on any column.")
    merged = e.merge(ana[["company", "life_high_vs_issue_pct", "max_dd_pct", "open_pop_pct",
                          "d1_close_vs_issue_pct"]], on="company", how="left")
    st.dataframe(
        merged[["reco", "score", "company", "board", "symbol", "listing_date", "cmp",
                "cmp_vs_issue_pct", "dist_to_pivot_pct", "base_low_pct", "qib_x", "adv_cr",
                "ff_vol_pct", "mcap_cr", "last_thrust_date", "life_high_vs_issue_pct",
                "max_dd_pct", "entry", "stop", "target", "rr", "lead_manager", "anchor_90d",
                "screener_url", "tradingview_url"]],
        use_container_width=True, hide_index=True, height=620, column_config={
            "reco": st.column_config.TextColumn("Reco", help=H["reco"]),
            "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100,
                                                     format="%d", help=H["score"]),
            "company": "Company", "board": "Board", "symbol": "Symbol", "listing_date": "Listed",
            "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f", help=H["cmp"]),
            "cmp_vs_issue_pct": st.column_config.NumberColumn("vs Issue %", format="%.1f%%", help=H["vs_issue"]),
            "dist_to_pivot_pct": st.column_config.NumberColumn("To pivot %", format="%.1f%%", help=H["dist"]),
            "base_low_pct": st.column_config.NumberColumn("Base low %", format="%.1f%%", help=H["base"]),
            "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f", help=H["qib"]),
            "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.2f", help=H["adv"]),
            "ff_vol_pct": st.column_config.NumberColumn("Vol/Float %", format="%.2f%%", help=H["ff"]),
            "mcap_cr": st.column_config.NumberColumn("MCap ₹cr", format="%.0f", help=H["mcap"]),
            "last_thrust_date": st.column_config.TextColumn("Last thrust", help=H["thrust_last"]),
            "life_high_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.1f%%", help=H["peak"]),
            "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%", help=H["maxdd"]),
            "entry": st.column_config.NumberColumn("Entry", format="%.2f", help=H["entry"]),
            "stop": st.column_config.NumberColumn("Stop", format="%.2f", help=H["stop"]),
            "target": st.column_config.NumberColumn("Target-1", format="%.2f", help=H["target"]),
            "rr": st.column_config.NumberColumn("R:R", format="%.1f", help=H["rr"]),
            "lead_manager": "Lead Manager",
            "anchor_90d": st.column_config.TextColumn("90d lock-in", help=H["a90"]),
            **LINKCOLS})
    st.download_button("⬇ Download filtered CSV", merged.to_csv(index=False), "ipo_radar_export.csv")

# ============================================================ DOSSIER
with T[2]:
    pick = st.selectbox("Select or type a stock — the full picture in one place",
                        sig["company"].tolist(), index=None,
                        placeholder="Start typing… e.g. Ather, Knack, Aditya Infotech")
    if pick:
        s = sig[sig["company"] == pick].iloc[0]
        a = ana[ana["company"] == pick].iloc[0]
        links = ""
        if isinstance(s["screener_url"], str) and s["screener_url"]:
            links += f'<a class="lnk f" href="{s["screener_url"]}" target="_blank">📊 Fundamentals — Screener</a>'
        if isinstance(s["tradingview_url"], str) and s["tradingview_url"]:
            links += f'<a class="lnk t" href="{s["tradingview_url"]}" target="_blank">📈 Chart — TradingView</a>'
        st.markdown(f"""<div class="card"><span class="badge b-{s['state']}">{s['reco']}</span>
          <span style="margin-left:8px;font-weight:700;color:#334155">Score {int(s['score'])}/100</span>
          <h3>{pick} <span style="font-weight:400;color:#6b7280">({s['symbol']} · {s['board']} · {s['exchange']})</span></h3>
          <div class="sub">Listed {s['listing_date']} · lead manager: {s['lead_manager'] or '—'}</div>{links}</div>""",
          unsafe_allow_html=True)

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("CMP", f"₹{s['cmp']:,.2f}", f"{a['cmp_vs_issue_pct']:+.1f}% vs issue")
        c2.metric("Pivot (D1 high)", f"₹{s['pivot']:,.2f}", f"{-s['dist_to_pivot_pct']:+.1f}% vs CMP", help=H["pivot"])
        c3.metric("Lifetime high", f"₹{a['life_high']:,.2f}", f"{a['dd_from_life_high_pct']:+.1f}% off high")
        c4.metric("Max drawdown", f"{a['max_dd_pct']:.1f}%", help=H["maxdd"])
        c5.metric("ADV (20d)", f"₹{a['avg_turnover_cr_20d']:.1f}cr", help=H["adv"])
        c6.metric("Vol/Float", f"{s['ff_vol_pct']:.2f}%" if pd.notna(s["ff_vol_pct"]) else "—",
                  f"promoter {s['promoter_pct']:.0f}%" if pd.notna(s["promoter_pct"]) else "", help=H["ff"])

        p = panel[panel["isin"] == s["isin"]].sort_values("date")
        p = p[p["date"] >= pd.Timestamp(s["listing_date"])]
        best_exch = p.groupby("exch")["turnover"].median().idxmax()
        p = p[p["exch"] == best_exch].set_index("date")
        chart = pd.DataFrame({"Close": p["close"], "EMA20": p["close"].ewm(span=20).mean(),
                              "Pivot (D1 high)": s["pivot"], "Issue price": a["issue_price"]})
        st.line_chart(chart, height=320)
        st.bar_chart(p["volume"], height=110)
        if pd.notna(a.get("first_thrust_date")) and isinstance(a.get("first_thrust_date"), str):
            st.caption(f"🔥 Volume thrusts (≥5× avg): {int(a['thrust_count'])} total · first {a['first_thrust_date']} · last {a['last_thrust_date']}"
                       + (f" · +{a['ret60_after_thrust_pct']:.0f}% in the 60 sessions after the first thrust" if pd.notna(a.get("ret60_after_thrust_pct")) else ""))

        cL, cR = st.columns(2)
        with cL:
            st.markdown("##### 📋 Pre-listing dossier")
            pre = pd.DataFrame({
                "Metric": ["Issue price", "Issue size", "Total subscription", "QIB", "NII", "Retail",
                           "Anchor allocation", "Anchor 30d lock-in", "Anchor 90d lock-in",
                           "Open pop", "Listing-day close", "Market cap (Screener)", "Promoter holding"],
                "Value": [f"₹{a['issue_price']:,.0f}", f"₹{a['issue_amount_cr']:,.0f} cr",
                          f"{a['subscription_total_x']:.1f}x" if pd.notna(a['subscription_total_x']) else "—",
                          f"{a['qib_x']:.1f}x" if pd.notna(a['qib_x']) else "—",
                          f"{a['nii_x']:.1f}x" if pd.notna(a['nii_x']) else "—",
                          f"{a['retail_x']:.1f}x" if pd.notna(a['retail_x']) else "—",
                          f"{a['anchor_pct_of_issue']:.0f}% of issue" if pd.notna(a['anchor_pct_of_issue']) else "—",
                          a['anchor_lockin_30d'] if isinstance(a['anchor_lockin_30d'], str) else "—",
                          a['anchor_lockin_90d'] if isinstance(a['anchor_lockin_90d'], str) else "—",
                          f"{a['open_pop_pct']:+.1f}%" if pd.notna(a['open_pop_pct']) else "—",
                          f"{a['d1_close_vs_issue_pct']:+.1f}% vs issue",
                          f"₹{s['mcap_cr']:,.0f} cr" if pd.notna(s['mcap_cr']) else "—",
                          f"{s['promoter_pct']:.1f}%" if pd.notna(s['promoter_pct']) else "—"]})
            st.dataframe(pre, hide_index=True, use_container_width=True)
        with cR:
            st.markdown("##### ⚖️ The verdict")
            bull, bear = [], []
            for x in str(s["reasons"]).split("•"):
                x = x.strip()
                if not x or x.startswith("Score"):
                    continue
                neg = any(w in x.lower() for w in ["weak", "deep", "illiquid", "avoid", "discount",
                                                   "mega-pop", "lost", "never reclaimed", "⚠",
                                                   "broken", "crowded", "thin institutional"])
                (bear if neg else bull).append(x)
            if pd.notna(a["dd_from_life_high_pct"]) and a["dd_from_life_high_pct"] < -30:
                bear.append(f"Sitting {a['dd_from_life_high_pct']:.0f}% below its lifetime high — broken trend until proven otherwise")
            if a["cmp_vs_issue_pct"] > 50:
                bull.append(f"Proven winner: +{a['cmp_vs_issue_pct']:.0f}% over issue, peak on session {int(a['days_to_high'])}")
            st.markdown("**Why you might buy:**")
            st.markdown("\n".join(f"- ✅ {b}" for b in bull) or "- (nothing constructive right now)")
            st.markdown("**Why you might not:**")
            st.markdown("\n".join(f"- ⛔ {b}" for b in bear) or "- (no red flags in our data)")
            if pd.notna(s["entry"]):
                st.markdown(f"**If entering:** close above ₹{s['entry']:,.2f} → stop ₹{s['stop']:,.2f} ({s['stop_basis']}) → partial at ₹{s['target']:,.2f}, trail the rest. Risk 1–2% of capital.")
            if isinstance(s.get("analogs"), str) and s["analogs"]:
                st.markdown("**🧬 Closest historical analogs:**")
                for x in s["analogs"].split("|"):
                    st.markdown(f"- {x.strip()}")
            st.caption("Fundamentals (results, news, shareholding changes) → Screener link above.")

# ============================================================ WINNERS LAB
with T[3]:
    L = stats.get("winner_lessons", {})
    fm = lambda k, suf="": (f"{L[k]:.0f}{suf}" if isinstance(L.get(k), (int, float)) else "–")
    st.markdown(f"""<div class="insight"><b>What the top-{L.get('n_winners','?')} winners teach (recomputed daily):</b><br>
    1️⃣ <b>{fm('pct_reclaimed_pivot_within25','%')}</b> reclaimed their listing-day high within 25 sessions → <i>the pivot IS the tell — trade it, don't wait for comfort.</i><br>
    2️⃣ <b>{fm('pct_with_volume_thrust','%')}</b> printed a ≥5× volume-thrust day (median <b>{fm('median_ret60_after_spike','%')}</b> in the next 60 sessions) → <i>thrust dates are in the table below and on the Today tab — that's your early-warning scanner.</i><br>
    3️⃣ Median <b>{fm('median_days_to_peak')}</b> sessions to peak → <i>winners run ~9 months; take partial at +15% and trail the rest instead of capping.</i><br>
    4️⃣ Median max drawdown <b>{fm('median_max_dd','%')}</b> → <i>even the best names had violent shakeouts — defined stops, not hope.</i></div>""",
    unsafe_allow_html=True)
    st.dataframe(winners.drop(columns=["isin"], errors="ignore"), use_container_width=True,
                 hide_index=True, height=520, column_config={
            "company": "Company", "board": "Board", "symbol": "Symbol", "listing_date": "Listed",
            "issue_price": st.column_config.NumberColumn("Issue ₹", format="%.0f"),
            "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
            "now_vs_issue_pct": st.column_config.NumberColumn("Now vs issue %", format="%.0f%%"),
            "peak_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.0f%%"),
            "days_to_peak": st.column_config.NumberColumn("Days→peak"),
            "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%", help=H["maxdd"]),
            "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f", help=H["qib"]),
            "sub_x": st.column_config.NumberColumn("Sub x", format="%.1f"),
            "d1_gain_pct": st.column_config.NumberColumn("D1 gain %", format="%.1f%%", help=H["d1gain"]),
            "breakout_day": st.column_config.NumberColumn("Pivot day", help=H["bo_day"]),
            "base30_low_pct": st.column_config.NumberColumn("Base low %", format="%.1f%%", help=H["base"]),
            "first_vol_spike_day": st.column_config.NumberColumn("Thrust day #", help=H["thrust"]),
            "first_thrust_date": st.column_config.TextColumn("First thrust", help=H["thrust"]),
            "last_thrust_date": st.column_config.TextColumn("Last thrust", help=H["thrust_last"]),
            "ret60_after_vol_spike_pct": st.column_config.NumberColumn("+60d after thrust %", format="%.1f%%"),
            "green_weeks_pct": st.column_config.NumberColumn("Green weeks %"),
            "pattern": st.column_config.TextColumn("Pattern", width="large")})

# ============================================================ LEAD MANAGERS
with T[4]:
    st.markdown("""<div class="insight"><b>How to use:</b> LMs are ranked on what happens
    <b>after</b> listing (not the pop): median return over issue today, % of issues still above issue,
    pivot-reclaim rate, drawdown control. Pick any LM below to see every stock it brought to market.</div>""",
    unsafe_allow_html=True)
    st.markdown("##### 🔎 Pick a lead manager — every issue it managed")
    lm_pick = st.selectbox("Lead manager", scorecard["lead_manager"].tolist(), index=None,
                           placeholder="Select or type… e.g. Kotak Mahindra Capital")
    if lm_pick:
        issues = sig[sig["lead_manager"] == lm_pick].merge(
            ana[["company", "life_high_vs_issue_pct", "max_dd_pct", "d1_close_vs_issue_pct"]],
            on="company", how="left")
        st.dataframe(issues[["reco", "score", "company", "board", "listing_date", "cmp",
                             "cmp_vs_issue_pct", "d1_close_vs_issue_pct", "life_high_vs_issue_pct",
                             "max_dd_pct", "qib_x", "adv_cr", "screener_url", "tradingview_url"]],
                     use_container_width=True, hide_index=True, column_config={
                "reco": "Reco", "score": "Score", "company": "Company", "board": "Board",
                "listing_date": "Listed",
                "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
                "cmp_vs_issue_pct": st.column_config.NumberColumn("Now vs issue %", format="%.1f%%"),
                "d1_close_vs_issue_pct": st.column_config.NumberColumn("D1 gain %", format="%.1f%%"),
                "life_high_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.1f%%"),
                "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%"),
                "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f"),
                "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.2f"),
                **LINKCOLS})
    st.markdown("##### 🏦 Full scorecard (min 3 issues)")
    st.dataframe(scorecard, use_container_width=True, hide_index=True, height=480, column_config={
        "lead_manager": "Lead Manager", "issues": "Issues", "mainboard": "MB", "sme": "SME",
        "median_listing_gain_pct": st.column_config.NumberColumn("Med. D1 %", format="%.1f%%", help=H["d1gain"]),
        "median_now_vs_issue_pct": st.column_config.NumberColumn("Med. now vs issue %", format="%.1f%%"),
        "pct_above_issue_today": st.column_config.NumberColumn("% above issue", format="%.0f%%"),
        "median_max_dd_pct": st.column_config.NumberColumn("Med. max DD %", format="%.1f%%"),
        "median_peak_vs_issue_pct": st.column_config.NumberColumn("Med. peak %", format="%.1f%%"),
        "pivot_reclaim_rate_pct": st.column_config.NumberColumn("Pivot reclaim %", format="%.0f%%"),
        "median_r60_after_breakout_pct": st.column_config.NumberColumn("Med. +60d post-BO %", format="%.1f%%"),
        "median_qib_x": st.column_config.NumberColumn("Med. QIB x", format="%.1f"),
        "median_adv_cr": st.column_config.NumberColumn("Med. ADV ₹cr", format="%.2f"),
        "lm_score": st.column_config.ProgressColumn("LM Score", min_value=0, max_value=100,
                                                    format="%.0f", help=H["lm_score"])})

# ============================================================ STUDY & METHOD
with T[5]:
    st.markdown("""<div class="insight"><b>The one-paragraph strategy:</b> buy the first daily close above
    the listing-day high within 25 sessions of listing, in names whose base held above −10%; stop at the
    base low (max −8%); partial at +15%, trail the rest; out by 60 sessions or before the 90-day anchor
    lock-in. Validated walk-forward: optimized on 2023–24 listings, tested untouched on 2025–26 →
    <b>PF 1.95, +5.4% mean/trade net of costs, ~45% win rate</b> — small losses, big tails.
    Volume-thrust and 20-day-high entries were tested head-to-head and lost.</div>""",
    unsafe_allow_html=True)
    st.subheader("Rule ladder & cohort stability")
    st.dataframe(ladder, hide_index=True, use_container_width=True)
    st.subheader("Backtest grid (walk-forward: tr = 2023–24 listings, te = 2025–26)")
    bt = pd.read_csv(os.path.join(DATA, "backtest_grid.csv")) if os.path.exists(
        os.path.join(DATA, "backtest_grid.csv")) else pd.DataFrame()
    if len(bt):
        st.dataframe(bt, hide_index=True, use_container_width=True, height=300)
    c1, c2 = st.columns(2)
    with c1:
        if "qib_quartiles" in stats:
            st.subheader("QIB quartiles (median)")
            st.dataframe(pd.DataFrame(stats["qib_quartiles"]).rename(columns={
                "d1_close_vs_issue_pct": "D1 vs issue %", "cmp_vs_d1close_pct": "Now vs D1 %",
                "life_high_vs_issue_pct": "Peak vs issue %"}), use_container_width=True)
        if "lockin30" in stats:
            st.subheader("Anchor lock-in event study")
            st.dataframe(pd.DataFrame({"30-day": stats["lockin30"],
                                       "90-day": stats["lockin90"]}).T, use_container_width=True)
    with c2:
        st.subheader("Open-pop buckets (median)")
        st.dataframe(pd.DataFrame(stats["open_pop"]).rename(columns={
            "cmp_vs_d1close_pct": "Now vs D1 %", "max_dd_pct": "Max DD %",
            "life_high_vs_issue_pct": "Peak vs issue %"}), use_container_width=True)
        st.subheader("Monthly regime — median listing gain")
        st.bar_chart(pd.Series(stats["monthly_d1"]).rename("median D1 gain %"))
    st.markdown(f"""
### Score vs Reco — the exact rules
**RECO is a state machine** (the action): FRESH BUY (pivot reclaimed ≤3 sessions ago, score ≥65) ·
BUY-SETUP (within 10% below pivot, ≤40 sessions, score ≥60) · RIDE (above pivot, trend intact) ·
EXIT (lost pivot AND 20-EMA after having broken out) · AVOID (never reclaimed pivot in 25 sessions,
or base broke −25%, or score <35) · WATCH (everything else).

**SCORE is conviction** within the state: structure 35 + base 20 + liquidity 15 + institutions 15 +
lock-in 5 + LM 5 + momentum 5. Weights follow what the backtest rewarded. Compare within a reco.

**Trade plan math:** Entry = pivot · Stop = max(base low, −8%) — the shown basis tells you which bound ·
Target-1 = +15% (historical median band), then trail · time-stop 60 sessions · position size =
(capital × 1–2%) / (entry − stop), capped at 5% of daily volume for SME.

**Data:** NSE/BSE official bhavcopies (both format generations, units continuity-checked) ·
Chittorgarh (issue, subscription, anchor lock-ins, lead managers) · Screener (market cap, promoter
holding → free float). Everything refreshes every trading day via GitHub Actions.
*Research tool — not investment advice.*
""")
