"""IPO Radar — recent-IPO breakout platform. Streamlit dashboard."""
import json
import os

import numpy as np
import pandas as pd
import streamlit as st

DATA = os.path.join(os.path.dirname(__file__), "data")

st.set_page_config(page_title="IPO Radar", page_icon="🎯", layout="wide")

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
.hero {background: linear-gradient(120deg,#0f2027,#203a43,#2c5364); border-radius: 14px;
  padding: 22px 30px; color: white; margin-bottom: 14px;}
.hero h1 {margin: 0; font-size: 1.9rem;} .hero p {margin: 4px 0 0; opacity: .85; font-size: .95rem;}
.badge {display:inline-block; padding:3px 12px; border-radius:12px; font-weight:700; font-size:.78rem; letter-spacing:.5px;}
.b-TRIGGER {background:#16a34a; color:white;} .b-SETUP {background:#f59e0b; color:#1a1a1a;}
.b-RIDE {background:#0ea5e9; color:white;} .b-AVOID {background:#dc2626; color:white;}
.b-NEUTRAL {background:#6b7280; color:white;}
.card {border:1px solid #e5e7eb; border-radius:14px; padding:18px 22px; margin-bottom:14px;
  box-shadow:0 1px 4px rgba(0,0,0,.06); background:var(--background-color, white);}
.card h3 {margin:0 0 2px; font-size:1.15rem;}
.card .sub {color:#6b7280; font-size:.82rem; margin-bottom:8px;}
.card ul {margin:8px 0 0 2px; padding-left:20px;}
.card li {margin-bottom:5px; font-size:.9rem; line-height:1.45;}
.plan {display:flex; gap:22px; margin-top:10px; flex-wrap:wrap;}
.plan div {background:#f3f4f6; border-radius:10px; padding:8px 16px; font-size:.85rem;}
.plan b {display:block; font-size:1.05rem;}
.metricrow {display:flex; gap:14px; flex-wrap:wrap; margin-bottom:6px;}
.metricrow .m {flex:1; min-width:150px; background:#f8fafc; border:1px solid #e2e8f0;
  border-radius:12px; padding:12px 16px; text-align:center;}
.m b {font-size:1.5rem; display:block;} .m span {font-size:.78rem; color:#64748b;}
[data-testid="stDataFrame"] {border:1px solid #e5e7eb; border-radius:12px;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load():
    sig = pd.read_csv(os.path.join(DATA, "signals.csv"))
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    stats = json.load(open(os.path.join(DATA, "study_stats.json")))
    ladder = pd.read_csv(os.path.join(DATA, "rule_ladder.csv"))
    return sig, ana, panel, stats, ladder


sig, ana, panel, stats, ladder = load()
last_date = pd.Timestamp(panel["date"].max()).date()

st.markdown(f"""
<div class="hero"><h1>🎯 IPO Radar</h1>
<p>Every NSE + BSE IPO (mainboard + SME) listed since July 2025 · {len(sig)} tracked ·
prices to <b>{last_date}</b> · strategy: <b>Pivot Reclaim</b> — first close above the
listing-day high within 25 sessions, quality-gated (backtest: +8.8% median / 62% win @60d; SME +14.3% / 75%)</p></div>
""", unsafe_allow_html=True)

n = sig["state"].value_counts()
st.markdown(f"""
<div class="metricrow">
<div class="m"><b style="color:#16a34a">{n.get('TRIGGER',0)}</b><span>TRIGGER — enter now</span></div>
<div class="m"><b style="color:#f59e0b">{n.get('SETUP',0)}</b><span>SETUP — basing near pivot</span></div>
<div class="m"><b style="color:#0ea5e9">{n.get('RIDE',0)}</b><span>RIDE — holding above pivot</span></div>
<div class="m"><b style="color:#dc2626">{n.get('AVOID',0)}</b><span>AVOID — failed pivot / broken base</span></div>
<div class="m"><b style="color:#6b7280">{n.get('NEUTRAL',0)}</b><span>NEUTRAL — waiting</span></div>
</div>
""", unsafe_allow_html=True)

tab_sig, tab_watch, tab_exp, tab_study, tab_method = st.tabs(
    ["🚨 Live Signals", "⭐ Watchlist (why & how)", "🔍 Explorer", "📊 The Study", "📖 Method"])

# ---------------------------------------------------------------- signals tab
with tab_sig:
    fmt = {"cmp": "₹{:,.2f}", "pivot": "₹{:,.2f}", "entry": "₹{:,.2f}",
           "stop": "₹{:,.2f}", "target": "₹{:,.2f}"}
    act = sig[sig["state"].isin(["TRIGGER", "SETUP", "RIDE"])].copy()
    show = act[["state", "company", "board", "symbol", "listing_date", "cmp", "pivot",
                "dist_to_pivot_pct", "qib_x", "adv_cr", "days_listed", "entry", "stop",
                "target", "rr", "lead_manager"]]
    st.dataframe(
        show, use_container_width=True, hide_index=True, height=560,
        column_config={
            "state": st.column_config.TextColumn("Signal", width="small"),
            "company": st.column_config.TextColumn("Company", width="medium"),
            "board": "Board", "symbol": "Symbol", "listing_date": "Listed",
            "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
            "pivot": st.column_config.NumberColumn("Pivot ₹ (D1 high)", format="%.2f"),
            "dist_to_pivot_pct": st.column_config.NumberColumn("To pivot %", format="%.1f%%"),
            "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f"),
            "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.1f"),
            "days_listed": "Sessions",
            "entry": st.column_config.NumberColumn("Entry", format="%.2f"),
            "stop": st.column_config.NumberColumn("Stop", format="%.2f"),
            "target": st.column_config.NumberColumn("Target", format="%.2f"),
            "rr": st.column_config.NumberColumn("R:R", format="%.1f"),
            "lead_manager": "Lead Manager",
        })
    st.caption("TRIGGER = fresh close above pivot (≤3 sessions ago). SETUP = gates passed, basing within 15% of pivot. RIDE = above pivot, manage the trend. All plans assume 1–2% account risk per trade.")

# ---------------------------------------------------------------- watchlist tab
with tab_watch:
    focus = sig[sig["state"].isin(["TRIGGER", "SETUP"])].copy()
    ride = sig[sig["state"] == "RIDE"].nlargest(6, "score")
    if focus.empty:
        st.info("No TRIGGER/SETUP names right now — the radar refreshes daily after market close.")
    for _, r in pd.concat([focus, ride]).iterrows():
        reasons = "".join(f"<li>{x.strip()}</li>" for x in str(r["reasons"]).split("•") if x.strip())
        plan = ""
        if pd.notna(r["entry"]):
            plan = f"""<div class="plan">
              <div><span>Entry (pivot)</span><b>₹{r['entry']:,.2f}</b></div>
              <div><span>Stop</span><b>₹{r['stop']:,.2f}</b></div>
              <div><span>Target-1 (+15%)</span><b>₹{r['target']:,.2f}</b></div>
              <div><span>Risk : Reward</span><b>{r['rr'] if pd.notna(r['rr']) else '—'}</b></div>
              <div><span>Timeframe</span><b>≤60 sessions</b></div></div>"""
        st.markdown(f"""
        <div class="card">
          <span class="badge b-{r['state']}">{r['state']}</span>
          <h3>{r['company']} <span style="font-weight:400;color:#6b7280">({r['symbol']} · {r['board']} · {r['exchange']})</span></h3>
          <div class="sub">Listed {r['listing_date']} · {int(r['days_listed'])} sessions · CMP ₹{r['cmp']:,.2f} · pivot ₹{r['pivot']:,.2f}</div>
          <ul>{reasons}</ul>
          {plan}
        </div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- explorer tab
with tab_exp:
    c1, c2, c3, c4 = st.columns(4)
    f_board = c1.multiselect("Board", ["Mainboard", "SME"], default=["Mainboard", "SME"])
    f_state = c2.multiselect("Signal", list(sig["state"].unique()), default=list(sig["state"].unique()))
    f_liq = c3.slider("Min ADV (₹cr)", 0.0, 25.0, 0.0, 0.5)
    f_q = c4.slider("Min QIB (x)", 0.0, 100.0, 0.0, 1.0)
    e = sig[sig["board"].isin(f_board) & sig["state"].isin(f_state) &
            (sig["adv_cr"].fillna(0) >= f_liq) & (sig["qib_x"].fillna(0) >= f_q)]
    merged = e.merge(
        ana[["company", "life_high_vs_issue_pct", "max_dd_pct", "dd_from_life_high_pct",
             "open_pop_pct", "d1_close_vs_issue_pct"]], on="company", how="left")
    st.dataframe(
        merged[["state", "company", "board", "symbol", "listing_date", "cmp",
                "cmp_vs_issue_pct", "open_pop_pct", "life_high_vs_issue_pct",
                "dd_from_life_high_pct", "max_dd_pct", "qib_x", "sub_x", "adv_cr",
                "lead_manager", "anchor_90d"]],
        use_container_width=True, hide_index=True, height=620,
        column_config={
            "state": "Signal", "company": "Company", "board": "Board", "symbol": "Symbol",
            "listing_date": "Listed", "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
            "cmp_vs_issue_pct": st.column_config.NumberColumn("vs Issue %", format="%.1f%%"),
            "open_pop_pct": st.column_config.NumberColumn("Open pop %", format="%.1f%%"),
            "life_high_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.1f%%"),
            "dd_from_life_high_pct": st.column_config.NumberColumn("Off high %", format="%.1f%%"),
            "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%"),
            "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f"),
            "sub_x": st.column_config.NumberColumn("Sub x", format="%.1f"),
            "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.2f"),
            "lead_manager": "Lead Manager", "anchor_90d": "90d lock-in",
        })
    st.download_button("⬇ Download filtered CSV", merged.to_csv(index=False), "ipo_radar_export.csv")

# ---------------------------------------------------------------- study tab
with tab_study:
    st.subheader("The rule ladder — where the edge comes from")
    st.dataframe(ladder, hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("QIB quartiles (median outcomes)")
        q = pd.DataFrame(stats["qib_quartiles"]).rename(columns={
            "d1_close_vs_issue_pct": "D1 vs issue %", "cmp_vs_d1close_pct": "Now vs D1 %",
            "life_high_vs_issue_pct": "Peak vs issue %"})
        st.dataframe(q, use_container_width=True)
        st.subheader("Anchor lock-in event study")
        st.dataframe(pd.DataFrame({
            "30-day": {"n": stats["lockin30"]["n"], "5d into expiry %": round(stats["lockin30"]["pre5_median"], 2),
                       "expiry→+10d %": round(stats["lockin30"]["post10_median"], 2), "win % after": round(stats["lockin30"]["post10_win"], 1)},
            "90-day": {"n": stats["lockin90"]["n"], "5d into expiry %": round(stats["lockin90"]["pre5_median"], 2),
                       "expiry→+10d %": round(stats["lockin90"]["post10_median"], 2), "win % after": round(stats["lockin90"]["post10_win"], 1)},
        }).T, use_container_width=True)
    with c2:
        st.subheader("Open-pop buckets (median)")
        st.dataframe(pd.DataFrame(stats["open_pop"]).rename(columns={
            "cmp_vs_d1close_pct": "Now vs D1 %", "max_dd_pct": "Max DD %",
            "life_high_vs_issue_pct": "Peak vs issue %"}), use_container_width=True)
        st.subheader("Monthly regime (median listing gain)")
        m = pd.Series(stats["monthly_d1"]).rename("median D1 gain %")
        st.bar_chart(m)
    st.info(f"IPOs that never reclaimed their listing-day high: **{stats['never_broke']['n']}** — now at **{stats['never_broke']['cmp_vs_d1close_median']}%** median vs listing close. The pivot is the dividing line between winners and dead money.")

# ---------------------------------------------------------------- method tab
with tab_method:
    st.markdown("""
### The Pivot Reclaim playbook
**Universe** — every mainboard + SME IPO on NSE/BSE listed in the last 12 months, refreshed daily from exchange bhavcopies and Chittorgarh.

**Quality gates** (need 3 of 4): QIB ≥ 15x · first-30-session low above −15% vs listing close · ADV ≥ ₹5cr (mainboard) / ₹2cr (SME) · listing pop 0–50%.

**Entry** — first daily close above the listing-day high (the pivot), within 25 sessions of listing.
**Stop** — base low, capped at −8% from entry. **Manage** — trail after +15%; time-stop 60 sessions; trim into the 90-day anchor lock-in.

**Why it works** — recent IPOs carry no overhead supply (Minervini), institutions accumulate for weeks after strong debuts (Qullamaggie's EP logic), and sub-₹500cr issues sit outside index funds and analyst coverage — the under-owned pocket where the study found the entire edge (SME composite: +14.3% median, 75% win @60d).

**Backtest caveat** — one year (Jul-2025→Jul-2026), one regime, no slippage. SME spreads can run 1–2%. This is a research tool, not investment advice.

**Data** — NSE/BSE official bhavcopy (prices, volumes) · Chittorgarh (issue, subscription, anchor lock-ins, lead managers) · cross-verified (CMP 100% agreement, listing close 99.5%).
""")
