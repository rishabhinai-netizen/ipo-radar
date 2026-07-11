"""IPO Radar v2 — recent-IPO alpha platform. Streamlit dashboard."""
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
  padding: 20px 28px; color: white; margin-bottom: 12px;}
.hero h1 {margin: 0; font-size: 1.8rem;} .hero p {margin: 4px 0 0; opacity: .85; font-size: .92rem;}
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
.metricrow .m {flex:1; min-width:140px; background:#f8fafc; border:1px solid #e2e8f0;
  border-radius:12px; padding:10px 14px; text-align:center;}
.m b {font-size:1.4rem; display:block;} .m span {font-size:.75rem; color:#64748b;}
[data-testid="stDataFrame"] {border:1px solid #e5e7eb; border-radius:12px;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- tooltips
H = {
    "state": "Signal state. TRIGGER: fresh close above the listing-day high (pivot) within 25 sessions — the study's entry. SETUP: quality gates passed, basing within 15% of pivot. RIDE: above pivot, trend on. AVOID: failed pivot >25 sessions / broken base. NEUTRAL: waiting.",
    "pivot": "The listing-day HIGH. The study's dividing line: names that closed above it within 25 sessions massively outperformed; names that never did sit deeply negative.",
    "cmp": "Latest close from official NSE/BSE bhavcopy (primary = higher-turnover exchange).",
    "dist": "How far CMP is below the pivot (+) or above it (−). The trigger is a daily CLOSE above the pivot.",
    "qib": "Qualified Institutional Buyer subscription multiple. ≥15x is the quality bar — high-QIB names had the biggest lifetime gains.",
    "sub": "Total subscription across all investor categories.",
    "adv": "Average daily turnover, last 20 sessions (₹ crore). Liquidity gate: ≥₹5cr mainboard / ≥₹2cr SME. Illiquid names bled −17% median.",
    "base": "Lowest low in the first 30 sessions vs listing close. Shallow (> −15%) = accumulation; deep flush = distribution.",
    "sessions": "Trading sessions since listing.",
    "bo_day": "Session number on which price FIRST closed above the pivot. ≤25 = valid; later reclaims historically failed.",
    "entry": "= the pivot (listing-day high). Buy the first daily close above it.",
    "stop": "The HIGHER of: base low (level whose break kills the setup) or entry −8% (O'Neil hard cap). See 'stop basis'.",
    "stop_basis": "Which rule set the stop — the base low, or the −8% hard cap when the base low is too far.",
    "target": "Entry +15% — the historical median 60-session gain band of qualifying breakouts. Take partial, trail the rest.",
    "rr": "(Target − Entry) / (Entry − Stop). Reward per unit of risk.",
    "vs_issue": "CMP vs IPO issue price (%).",
    "pop": "Listing-day OPEN vs issue price. +5–50% was the sweet spot; discounts and mega-pops both underperformed.",
    "peak": "Lifetime high vs issue price (%).",
    "off_high": "CMP vs lifetime high — current drawdown from peak.",
    "maxdd": "Worst close-to-close drawdown since listing.",
    "lm": "Lead manager (book-running). See the Lead Managers tab for its full post-listing scorecard.",
    "a30": "Anchor investors' 30-day lock-in expiry (50% of anchor shares become sellable). Mild supply headwind.",
    "a90": "Anchor investors' 90-day lock-in expiry (remaining 50%). The worse of the two windows: −2.4% median drift into it.",
    "d1gain": "Listing-day close vs issue price (%).",
    "days_peak": "Sessions from listing to the lifetime high — winners' median is ~3 months, not 3 days.",
    "green_wk": "% of weeks closing higher — consistency of the advance (compounder fingerprint).",
    "spike": "First session (after day 5) with volume ≥5× the trailing 20-day average — the institutional footprint.",
    "spike_ret": "Return in the 60 sessions AFTER that first volume spike — did the footprint pay?",
    "pattern": "Data-derived classification of how the winner made its move.",
    "lm_score": "Composite 0–100: 35% median now-vs-issue + 25% share above issue + 20% pivot-reclaim rate + 20% drawdown control. Judges what happens AFTER listing, not the listing pop.",
    "above_issue": "% of this LM's issues trading ABOVE issue price today — the cleanest 'did investors actually make money' test.",
    "reclaim": "% of this LM's issues that closed above their listing-day high within 25 sessions.",
    "screener": "Open the company's fundamentals on Screener.in.",
    "tv": "Open the live chart on TradingView.",
}

@st.cache_data(ttl=1800)
def load():
    sig = pd.read_csv(os.path.join(DATA, "signals.csv"))
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    stats = json.load(open(os.path.join(DATA, "study_stats.json")))
    ladder = pd.read_csv(os.path.join(DATA, "rule_ladder.csv"))
    sc = (pd.read_csv(os.path.join(DATA, "lm_scorecard.csv"))
          if os.path.exists(os.path.join(DATA, "lm_scorecard.csv")) else pd.DataFrame())
    win = (pd.read_csv(os.path.join(DATA, "winners.csv"))
           if os.path.exists(os.path.join(DATA, "winners.csv")) else pd.DataFrame())
    return sig, ana, panel, stats, ladder, sc, win

sig, ana, panel, stats, ladder, scorecard, winners = load()
last_date = pd.Timestamp(panel["date"].max()).date()

st.markdown(f"""
<div class="hero"><h1>🎯 IPO Radar</h1>
<p>Every NSE + BSE IPO (mainboard + SME) listed since <b>{stats.get('universe_start','2023-07-01')}</b> ·
{stats.get('n_ipos', len(sig))} tracked ({stats.get('n_mainboard','?')} mainboard, {stats.get('n_sme','?')} SME) ·
prices to <b>{last_date}</b> · auto-refreshes every trading day · strategy: <b>Pivot Reclaim</b></p></div>
""", unsafe_allow_html=True)

n = sig["state"].value_counts()
st.markdown(f"""
<div class="metricrow">
<div class="m"><b style="color:#16a34a">{n.get('TRIGGER',0)}</b><span>TRIGGER — enter now</span></div>
<div class="m"><b style="color:#f59e0b">{n.get('SETUP',0)}</b><span>SETUP — basing near pivot</span></div>
<div class="m"><b style="color:#0ea5e9">{n.get('RIDE',0)}</b><span>RIDE — above pivot</span></div>
<div class="m"><b style="color:#dc2626">{n.get('AVOID',0)}</b><span>AVOID — failed / broken</span></div>
<div class="m"><b style="color:#6b7280">{n.get('NEUTRAL',0)}</b><span>NEUTRAL — waiting</span></div>
</div>
""", unsafe_allow_html=True)

T = st.tabs(["🚨 Signals", "⭐ Watchlist", "🧾 Stock Dossier", "🔍 Explorer",
             "🏆 Winners Lab", "🏦 Lead Managers", "📊 Study", "📖 Method"])

# ---------------------------------------------------------------- 1 signals
with T[0]:
    q = st.text_input("🔎 Search any stock", key="s1", placeholder="Type a company or symbol…")
    act = sig[sig["state"].isin(["TRIGGER", "SETUP", "RIDE"])].copy()
    if q:
        act = act[act["company"].str.contains(q, case=False, na=False) |
                  act["symbol"].astype(str).str.contains(q, case=False, na=False)]
    show = act[["state", "company", "board", "symbol", "listing_date", "cmp", "pivot",
                "dist_to_pivot_pct", "qib_x", "adv_cr", "days_listed", "entry", "stop",
                "stop_basis", "target", "rr", "screener_url", "tradingview_url"]]
    st.dataframe(show, use_container_width=True, hide_index=True, height=540, column_config={
        "state": st.column_config.TextColumn("Signal", help=H["state"], width="small"),
        "company": st.column_config.TextColumn("Company", width="medium"),
        "board": st.column_config.TextColumn("Board", help="Mainboard or SME platform"),
        "symbol": "Symbol",
        "listing_date": st.column_config.TextColumn("Listed", help="Listing date on exchange"),
        "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f", help=H["cmp"]),
        "pivot": st.column_config.NumberColumn("Pivot ₹", format="%.2f", help=H["pivot"]),
        "dist_to_pivot_pct": st.column_config.NumberColumn("To pivot %", format="%.1f%%", help=H["dist"]),
        "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f", help=H["qib"]),
        "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.1f", help=H["adv"]),
        "days_listed": st.column_config.NumberColumn("Sessions", help=H["sessions"]),
        "entry": st.column_config.NumberColumn("Entry", format="%.2f", help=H["entry"]),
        "stop": st.column_config.NumberColumn("Stop", format="%.2f", help=H["stop"]),
        "stop_basis": st.column_config.TextColumn("Stop basis", help=H["stop_basis"]),
        "target": st.column_config.NumberColumn("Target-1", format="%.2f", help=H["target"]),
        "rr": st.column_config.NumberColumn("R:R", format="%.1f", help=H["rr"]),
        "screener_url": st.column_config.LinkColumn("Fundamentals", display_text="Screener ↗", help=H["screener"]),
        "tradingview_url": st.column_config.LinkColumn("Chart", display_text="TradingView ↗", help=H["tv"]),
    })
    st.caption("Hover any column header's ⓘ for its meaning. Entry/Stop/Target math is documented in the Method tab — nothing is arbitrary.")

# ---------------------------------------------------------------- 2 watchlist
with T[1]:
    focus = sig[sig["state"].isin(["TRIGGER", "SETUP"])]
    ride = sig[sig["state"] == "RIDE"].nlargest(6, "score")
    if focus.empty and ride.empty:
        st.info("No actionable names right now — refreshes daily after market close.")
    for _, r in pd.concat([focus, ride]).iterrows():
        reasons = "".join(f"<li>{x.strip()}</li>" for x in str(r["reasons"]).split("•") if x.strip())
        plan = ""
        if pd.notna(r["entry"]):
            plan = f"""<div class="plan">
              <div><span>Entry (pivot)</span><b>₹{r['entry']:,.2f}</b></div>
              <div><span>Stop — {r['stop_basis']}</span><b>₹{r['stop']:,.2f}</b></div>
              <div><span>Target-1 (+15%, then trail)</span><b>₹{r['target']:,.2f}</b></div>
              <div><span>Risk:Reward</span><b>{r['rr'] if pd.notna(r['rr']) else '—'}</b></div>
              <div><span>Time stop</span><b>60 sessions</b></div></div>"""
        links = ""
        if isinstance(r["screener_url"], str) and r["screener_url"]:
            links += f'<a class="lnk f" href="{r["screener_url"]}" target="_blank">📊 Fundamentals — Screener</a>'
        if isinstance(r["tradingview_url"], str) and r["tradingview_url"]:
            links += f'<a class="lnk t" href="{r["tradingview_url"]}" target="_blank">📈 Chart — TradingView</a>'
        st.markdown(f"""
        <div class="card">
          <span class="badge b-{r['state']}">{r['state']}</span>
          <h3>{r['company']} <span style="font-weight:400;color:#6b7280">({r['symbol']} · {r['board']})</span></h3>
          <div class="sub">Listed {r['listing_date']} · {int(r['days_listed'])} sessions · CMP ₹{r['cmp']:,.2f} · pivot ₹{r['pivot']:,.2f}</div>
          <ul>{reasons}</ul>{plan}{links}
        </div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------- 3 dossier
with T[2]:
    pick = st.selectbox("Select or type a stock — everything you need in one place",
                        sig["company"].tolist(), index=None,
                        placeholder="Start typing… e.g. Knack, Meesho, Aditya Infotech")
    if pick:
        s = sig[sig["company"] == pick].iloc[0]
        a = ana[ana["company"] == pick].iloc[0]
        links = ""
        if isinstance(s["screener_url"], str) and s["screener_url"]:
            links += f'<a class="lnk f" href="{s["screener_url"]}" target="_blank">📊 Fundamentals — Screener</a>'
        if isinstance(s["tradingview_url"], str) and s["tradingview_url"]:
            links += f'<a class="lnk t" href="{s["tradingview_url"]}" target="_blank">📈 Chart — TradingView</a>'
        st.markdown(f"""<div class="card"><span class="badge b-{s['state']}">{s['state']}</span>
          <h3>{pick} <span style="font-weight:400;color:#6b7280">({s['symbol']} · {s['board']} · {s['exchange']})</span></h3>
          <div class="sub">Listed {s['listing_date']} · lead manager: {s['lead_manager'] or '—'}</div>{links}</div>""",
          unsafe_allow_html=True)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("CMP", f"₹{s['cmp']:,.2f}", f"{a['cmp_vs_issue_pct']:+.1f}% vs issue")
        c2.metric("Pivot (D1 high)", f"₹{s['pivot']:,.2f}", f"{-s['dist_to_pivot_pct']:+.1f}% vs CMP", help=H["pivot"])
        c3.metric("Lifetime high", f"₹{a['life_high']:,.2f}", f"{a['dd_from_life_high_pct']:+.1f}% off high")
        c4.metric("Max drawdown", f"{a['max_dd_pct']:.1f}%", help=H["maxdd"])
        c5.metric("ADV (20d)", f"₹{a['avg_turnover_cr_20d']:.1f}cr", help=H["adv"])

        # price chart with pivot & issue lines
        p = panel[panel["isin"] == s["isin"]].sort_values("date")
        p = p[p["date"] >= pd.Timestamp(s["listing_date"])]
        best_exch = p.groupby("exch")["turnover"].median().idxmax()
        p = p[p["exch"] == best_exch].set_index("date")
        chart = pd.DataFrame({"Close": p["close"],
                              "EMA20": p["close"].ewm(span=20).mean(),
                              "Pivot (D1 high)": s["pivot"],
                              "Issue price": a["issue_price"]})
        st.line_chart(chart, height=320)
        st.bar_chart(p["volume"], height=110)

        cL, cR = st.columns(2)
        with cL:
            st.markdown("##### 📋 Pre-listing dossier")
            pre = pd.DataFrame({
                "Metric": ["Issue price", "Issue size", "Total subscription", "QIB", "NII", "Retail",
                           "Anchor allocation", "Anchor 30d lock-in ends", "Anchor 90d lock-in ends",
                           "Listing-day open pop", "Listing-day close"],
                "Value": [f"₹{a['issue_price']:,.0f}", f"₹{a['issue_amount_cr']:,.0f} cr",
                          f"{a['subscription_total_x']:.1f}x" if pd.notna(a['subscription_total_x']) else "—",
                          f"{a['qib_x']:.1f}x" if pd.notna(a['qib_x']) else "—",
                          f"{a['nii_x']:.1f}x" if pd.notna(a['nii_x']) else "—",
                          f"{a['retail_x']:.1f}x" if pd.notna(a['retail_x']) else "—",
                          f"{a['anchor_pct_of_issue']:.0f}% of issue" if pd.notna(a['anchor_pct_of_issue']) else "—",
                          a['anchor_lockin_30d'] if isinstance(a['anchor_lockin_30d'], str) else "—",
                          a['anchor_lockin_90d'] if isinstance(a['anchor_lockin_90d'], str) else "—",
                          f"{a['open_pop_pct']:+.1f}%" if pd.notna(a['open_pop_pct']) else "—",
                          f"{a['d1_close_vs_issue_pct']:+.1f}% vs issue"]})
            st.dataframe(pre, hide_index=True, use_container_width=True)
        with cR:
            st.markdown("##### ⚖️ The verdict")
            bull, bear = [], []
            for x in str(s["reasons"]).split("•"):
                x = x.strip()
                if not x:
                    continue
                neg = any(w in x.lower() for w in ["weak", "deep", "illiquid", "avoid", "discount",
                                                   "mega-pop", "lost the pivot", "still below", "⚠", "bled"])
                (bear if neg else bull).append(x)
            if pd.notna(a["dd_from_life_high_pct"]) and a["dd_from_life_high_pct"] < -30:
                bear.append(f"Sitting {a['dd_from_life_high_pct']:.0f}% below its lifetime high — broken trend until proven otherwise")
            if pd.notna(a["days_to_high"]) and a["cmp_vs_issue_pct"] > 50:
                bull.append(f"Already a proven winner: +{a['cmp_vs_issue_pct']:.0f}% over issue with peak on session {int(a['days_to_high'])}")
            st.markdown("**Why you might buy:**")
            st.markdown("\n".join(f"- ✅ {b}" for b in bull) or "- (nothing constructive right now)")
            st.markdown("**Why you might not:**")
            st.markdown("\n".join(f"- ⛔ {b}" for b in bear) or "- (no red flags in our data)")
            if pd.notna(s["entry"]):
                st.markdown(f"**If entering:** buy a daily close above ₹{s['entry']:,.2f}, stop ₹{s['stop']:,.2f} ({s['stop_basis']}), target-1 ₹{s['target']:,.2f} then trail. Risk 1–2% of capital.")
            st.caption("Fundamental triggers (results, news, shareholding) → use the Screener link above; this platform covers price, volume, flow and structure.")

# ---------------------------------------------------------------- 4 explorer
with T[3]:
    c1, c2, c3, c4, c5 = st.columns([2, 1.5, 1.5, 1.5, 1.5])
    q2 = c1.text_input("🔎 Search", key="s2", placeholder="Company / symbol…")
    f_board = c2.multiselect("Board", ["Mainboard", "SME"], default=["Mainboard", "SME"])
    f_state = c3.multiselect("Signal", sorted(sig["state"].unique()), default=sorted(sig["state"].unique()))
    f_liq = c4.slider("Min ADV ₹cr", 0.0, 25.0, 0.0, 0.5, help=H["adv"])
    f_year = c5.multiselect("Listing year", sorted(sig["listing_date"].str[:4].unique()),
                            default=sorted(sig["listing_date"].str[:4].unique()))
    e = sig[sig["board"].isin(f_board) & sig["state"].isin(f_state) &
            (sig["adv_cr"].fillna(0) >= f_liq) & sig["listing_date"].str[:4].isin(f_year)]
    if q2:
        e = e[e["company"].str.contains(q2, case=False, na=False) |
              e["symbol"].astype(str).str.contains(q2, case=False, na=False)]
    merged = e.merge(ana[["company", "life_high_vs_issue_pct", "max_dd_pct",
                          "dd_from_life_high_pct", "open_pop_pct", "d1_close_vs_issue_pct"]],
                     on="company", how="left")
    st.dataframe(
        merged[["state", "company", "board", "symbol", "listing_date", "cmp", "cmp_vs_issue_pct",
                "open_pop_pct", "d1_close_vs_issue_pct", "life_high_vs_issue_pct",
                "dd_from_life_high_pct", "max_dd_pct", "qib_x", "sub_x", "adv_cr",
                "lead_manager", "anchor_90d", "screener_url", "tradingview_url"]],
        use_container_width=True, hide_index=True, height=600, column_config={
            "state": st.column_config.TextColumn("Signal", help=H["state"]),
            "company": "Company", "board": "Board", "symbol": "Symbol", "listing_date": "Listed",
            "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f", help=H["cmp"]),
            "cmp_vs_issue_pct": st.column_config.NumberColumn("vs Issue %", format="%.1f%%", help=H["vs_issue"]),
            "open_pop_pct": st.column_config.NumberColumn("Open pop %", format="%.1f%%", help=H["pop"]),
            "d1_close_vs_issue_pct": st.column_config.NumberColumn("D1 gain %", format="%.1f%%", help=H["d1gain"]),
            "life_high_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.1f%%", help=H["peak"]),
            "dd_from_life_high_pct": st.column_config.NumberColumn("Off high %", format="%.1f%%", help=H["off_high"]),
            "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%", help=H["maxdd"]),
            "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f", help=H["qib"]),
            "sub_x": st.column_config.NumberColumn("Sub x", format="%.1f", help=H["sub"]),
            "adv_cr": st.column_config.NumberColumn("ADV ₹cr", format="%.2f", help=H["adv"]),
            "lead_manager": st.column_config.TextColumn("Lead Manager", help=H["lm"]),
            "anchor_90d": st.column_config.TextColumn("90d lock-in", help=H["a90"]),
            "screener_url": st.column_config.LinkColumn("Fundamentals", display_text="Screener ↗", help=H["screener"]),
            "tradingview_url": st.column_config.LinkColumn("Chart", display_text="TV ↗", help=H["tv"]),
        })
    st.download_button("⬇ Download filtered CSV", merged.to_csv(index=False), "ipo_radar_export.csv")

# ---------------------------------------------------------------- 5 winners lab
with T[4]:
    L = stats.get("winner_lessons", {})
    if L:
        fm = lambda k, suf="": (f"{L[k]:.0f}{suf}" if isinstance(L.get(k), (int, float)) and L.get(k) is not None else "–")
        st.markdown(f"""
        <div class="metricrow">
        <div class="m"><b>{fm('pct_reclaimed_pivot_within25','%')}</b><span>of big winners reclaimed the pivot ≤25 sessions</span></div>
        <div class="m"><b>{fm('median_days_to_peak')}</b><span>median sessions to their peak</span></div>
        <div class="m"><b>{fm('pct_with_volume_thrust','%')}</b><span>showed a ≥5× volume thrust day</span></div>
        <div class="m"><b>{fm('median_ret60_after_spike','%')}</b><span>median 60-session return AFTER that thrust</span></div>
        <div class="m"><b>{fm('median_green_weeks','%')}</b><span>median green weeks (consistency)</span></div>
        </div>""", unsafe_allow_html=True)
    st.caption("Lessons are recomputed daily from the top-30 performers (by current AND peak return). The pattern column classifies HOW each winner made its move — most are pivot-reclaims with a volume thrust, not lottery tickets.")
    if len(winners):
        st.dataframe(winners.drop(columns=["isin"]), use_container_width=True, hide_index=True, height=560,
            column_config={
                "company": "Company", "board": "Board", "symbol": "Symbol", "listing_date": "Listed",
                "issue_price": st.column_config.NumberColumn("Issue ₹", format="%.0f"),
                "cmp": st.column_config.NumberColumn("CMP ₹", format="%.2f"),
                "now_vs_issue_pct": st.column_config.NumberColumn("Now vs issue %", format="%.0f%%", help=H["vs_issue"]),
                "peak_vs_issue_pct": st.column_config.NumberColumn("Peak vs issue %", format="%.0f%%", help=H["peak"]),
                "days_to_peak": st.column_config.NumberColumn("Days→peak", help=H["days_peak"]),
                "max_dd_pct": st.column_config.NumberColumn("Max DD %", format="%.1f%%", help=H["maxdd"]),
                "qib_x": st.column_config.NumberColumn("QIB x", format="%.1f", help=H["qib"]),
                "sub_x": st.column_config.NumberColumn("Sub x", format="%.1f", help=H["sub"]),
                "d1_gain_pct": st.column_config.NumberColumn("D1 gain %", format="%.1f%%", help=H["d1gain"]),
                "breakout_day": st.column_config.NumberColumn("Pivot reclaim day", help=H["bo_day"]),
                "base30_low_pct": st.column_config.NumberColumn("Base low %", format="%.1f%%", help=H["base"]),
                "first_vol_spike_day": st.column_config.NumberColumn("Vol-thrust day", help=H["spike"]),
                "ret60_after_vol_spike_pct": st.column_config.NumberColumn("+60d after thrust %", format="%.1f%%", help=H["spike_ret"]),
                "green_weeks_pct": st.column_config.NumberColumn("Green weeks %", help=H["green_wk"]),
                "pattern": st.column_config.TextColumn("Pattern", help=H["pattern"], width="large"),
            })

# ---------------------------------------------------------------- 6 lead managers
with T[5]:
    st.caption("Lead managers judged on what happens AFTER listing — not the listing-day pop. Hover column headers for definitions. Minimum 3 issues in the window.")
    if len(scorecard):
        st.dataframe(scorecard, use_container_width=True, hide_index=True, height=600, column_config={
            "lead_manager": "Lead Manager",
            "issues": st.column_config.NumberColumn("Issues", help="IPOs managed in the tracked window"),
            "mainboard": "Mainboard", "sme": "SME",
            "median_listing_gain_pct": st.column_config.NumberColumn("Med. D1 gain %", format="%.1f%%", help=H["d1gain"]),
            "median_now_vs_issue_pct": st.column_config.NumberColumn("Med. now vs issue %", format="%.1f%%",
                help="Median of its issues' CURRENT return over issue price — the as-of-today report card."),
            "pct_above_issue_today": st.column_config.NumberColumn("% above issue", format="%.0f%%", help=H["above_issue"]),
            "median_max_dd_pct": st.column_config.NumberColumn("Med. max DD %", format="%.1f%%",
                help="Median worst drawdown across its issues — pain investors endured."),
            "median_peak_vs_issue_pct": st.column_config.NumberColumn("Med. peak %", format="%.1f%%", help=H["peak"]),
            "pivot_reclaim_rate_pct": st.column_config.NumberColumn("Pivot reclaim %", format="%.0f%%", help=H["reclaim"]),
            "median_r60_after_breakout_pct": st.column_config.NumberColumn("Med. +60d post-BO %", format="%.1f%%",
                help="Median 60-session return after its issues' pivot breakouts."),
            "median_qib_x": st.column_config.NumberColumn("Med. QIB x", format="%.1f", help=H["qib"]),
            "median_adv_cr": st.column_config.NumberColumn("Med. ADV ₹cr", format="%.2f", help=H["adv"]),
            "lm_score": st.column_config.ProgressColumn("LM Score", min_value=0, max_value=100, format="%.0f", help=H["lm_score"]),
        })
    st.caption("Volume-vs-free-float and fundamental news triggers need shareholding data — on the roadmap via Screener integration; use the per-stock Screener links meanwhile.")

# ---------------------------------------------------------------- 7 study
with T[6]:
    st.subheader("The rule ladder — where the edge comes from")
    st.caption("Each row adds one filter. Watch n shrink and expectancy rise. Year-cohort rows test whether the rule survives across regimes.")
    st.dataframe(ladder, hide_index=True, use_container_width=True, column_config={
        "rule": "Filter (cumulative)", "n": st.column_config.NumberColumn("n", help="Qualifying breakouts"),
        "r20_med": st.column_config.NumberColumn("+20d median %", help="Median return 20 sessions after the breakout close"),
        "r20_win": st.column_config.NumberColumn("+20d win %", help="% positive after 20 sessions"),
        "r60_med": st.column_config.NumberColumn("+60d median %", help="Median return 60 sessions after the breakout close"),
        "r60_win": st.column_config.NumberColumn("+60d win %", help="% positive after 60 sessions"),
        "r60_mean": st.column_config.NumberColumn("+60d mean %", help="Average (includes the big tails)"),
        "r60_p90": st.column_config.NumberColumn("+60d p90 %", help="90th percentile — the tail you're fishing for")})
    c1, c2 = st.columns(2)
    with c1:
        if "qib_quartiles" in stats:
            st.subheader("QIB quartiles (median)")
            st.dataframe(pd.DataFrame(stats["qib_quartiles"]).rename(columns={
                "d1_close_vs_issue_pct": "D1 vs issue %", "cmp_vs_d1close_pct": "Now vs D1 %",
                "life_high_vs_issue_pct": "Peak vs issue %"}), use_container_width=True)
        if "lockin30" in stats:
            st.subheader("Anchor lock-in event study")
            st.dataframe(pd.DataFrame({
                "30-day": stats["lockin30"], "90-day": stats["lockin90"]}).T, use_container_width=True)
    with c2:
        st.subheader("Open-pop buckets (median)")
        st.dataframe(pd.DataFrame(stats["open_pop"]).rename(columns={
            "cmp_vs_d1close_pct": "Now vs D1 %", "max_dd_pct": "Max DD %",
            "life_high_vs_issue_pct": "Peak vs issue %"}), use_container_width=True)
        st.subheader("Monthly regime — median listing gain")
        st.bar_chart(pd.Series(stats["monthly_d1"]).rename("median D1 gain %"))
    st.info(f"IPOs that never reclaimed their listing-day high: **{stats['never_broke']['n']}** — now at "
            f"**{stats['never_broke']['cmp_vs_d1close_median']}%** median vs listing close.")

# ---------------------------------------------------------------- 8 method
with T[7]:
    st.markdown(f"""
### The Pivot Reclaim playbook — and why every number is what it is

**Universe** — every mainboard + SME IPO on NSE/BSE listed since {stats.get('universe_start','2023-07-01')}, auto-refreshed every trading day (new IPOs are picked up automatically; prices, subscription, anchor dates, lead managers all update daily — nothing on this site goes stale).

**Quality gates** (need 3 of 4) — each threshold came out of the data, not intuition:
- **QIB ≥ 15x** — institutional demand is the only subscription number that predicted post-listing performance
- **Base low > −15%** vs listing close in the first 30 sessions — shallow base = accumulation
- **ADV ≥ ₹5cr** (mainboard) / **₹2cr** (SME) — below this, exits destroy the theoretical edge
- **Open pop 0–50%** — discounts kept falling; mega-pops had already spent the move

**Entry = the pivot (listing-day high).** Why: it's the price every listing-day buyer paid at the top. A close back above it means all of them are in profit and supply is absorbed — the same logic as O'Neil's base pivot, applied to the only base a new listing has (Minervini's "primary base"). Late reclaims (>25 sessions) failed historically, so the window is hard.

**Stop = max(base low, entry −8%).** The base low is the setup's falsification point (if it breaks, the accumulation thesis is wrong). The −8% cap is O'Neil's max-loss rule for when the base low is too far to be a sane risk. The stop shown always tells you which rule bound.

**Target-1 = entry +15%, then trail.** Qualifying breakouts' median 60-session gain sat around +9–15%; winners kept running for ~3 months (median days-to-peak ≈ 60). So: take partial at +15%, trail the rest (10-day low or 20-EMA), hard time-stop at 60 sessions, and be trimmed before the 90-day anchor lock-in (−2.4% median drift into it).

**R:R** = (target − entry) / (entry − stop). Skip trades below ~1.5.

**Position size** — risk 1–2% of capital per trade: shares = (capital × risk%) / (entry − stop). SME: cap the position at ~5% of the stock's average daily volume.

**Honesty box** — expectancy comes from this dataset's own history (now spanning multiple listing-year cohorts — see the Study tab's cohort rows for stability). No slippage/impact modelled; SME spreads can run 1–2%. Fundamentals (earnings, news, shareholding) are NOT in the model — use the per-stock Screener links. This is research, not investment advice.

**Data** — NSE/BSE official bhavcopies (both format generations, turnover normalised), Chittorgarh cloud reports (issue, subscription, anchor lock-ins), per-IPO lead-manager scrape. Cross-verified at build: CMP 100% agreement, listing close 99.5%.
""")
