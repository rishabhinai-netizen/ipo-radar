# -*- coding: utf-8 -*-
"""Lead-Manager Radar — added page for the IPO Radar app.
Which bankers' IPOs perform, whether their own fund anchored, anchor-fund track records,
and a bulk/block-deal UPLOAD that recomputes the 'banker is buying' signal live."""
import streamlit as st, pandas as pd, json, io, csv, re, os, datetime as dt

st.set_page_config(page_title="Lead-Manager Radar", page_icon="🎯", layout="wide")
BASE = os.path.join(os.path.dirname(__file__), "..", "lmradar")

@st.cache_data(show_spinner=False)
def load_db():
    with open(os.path.join(BASE, "app_data.json"), encoding="utf-8") as f: return json.load(f)

@st.cache_data(show_spinner=True)
def load_prices():
    """symbol -> sorted list of (date, high, low, close) from lmradar/ipo_prices.csv"""
    p = os.path.join(BASE, "nse_all.csv"); s = {}
    if not os.path.exists(p): return s
    with open(p) as f:
        for r in csv.reader(f):
            if len(r) < 8: continue
            try: d, h, l, c = r[0], float(r[5]), float(r[6]), float(r[7])
            except: continue
            s.setdefault(r[1].upper(), []).append((d, h, l, c))
    for k in s: s[k].sort()
    return s

DB = load_db(); rows = DB["rows"]
by_sym = {r["nse_symbol"].upper(): r for r in rows if r.get("nse_symbol")}
def norm(n):
    n = (n or "").lower()
    for w in ["private","limited","ltd.","ltd","pvt.","pvt","advisors","advisory","capital","securities",
              "services","financial","finance","(india)","india","corporate","markets","&","and","the"]:
        n = n.replace(w, " ")
    return re.sub(r"\s+", " ", n).strip()
def pct(v): return "—" if v is None else f"{'+' if v>=0 else ''}{v}%"

st.title("🎯 Lead-Manager Radar")
e = DB["edge_selfanchor"]["SME"]; se, ne = e["self_anchored"], e["not_anchored"]
bf = (DB.get("backtest") or {}).get("buy_fwd", {})
st.info(f"**Verdict:** League & Anchor-Fund tables are reliable screens (exact prices). "
        f"Self-anchoring edge is unproven — SME self-anchored (n={se['n']}) **{pct(se['avg_since_listing'])}** "
        f"since listing vs **{pct(ne['avg_since_listing'])}** for the rest. Bulk-buy signal **{pct(bf.get('d30'))}** at +30d "
        f"(includes market-makers). Research screen, not an auto-trade.")
c = st.columns(6)
sme = [r for r in rows if r["segment"]=="SME"]; mb=[r for r in rows if r["segment"]=="Mainboard"]
for col,(lbl,val) in zip(c, [("IPOs",len(rows)),("SME",len(sme)),("Mainboard",len(mb)),
        ("Self-anchored",sum(1 for r in rows if r.get("self_anchor"))),
        ("Bulk-buy +30d",pct(bf.get("d30"))),("Updated",DB["generated"])]):
    col.metric(lbl, val)

T = st.tabs(["🏆 Lead-Manager League","📋 All IPOs","🎯 Advisor Signals","⚓ Anchor Funds","📡 Entering Now","⬆️ Upload daily deals"])

with T[0]:
    seg = st.radio("Segment", ["SME","Mainboard","All"], horizontal=True, key="lseg")
    df = pd.DataFrame(DB["league"][seg])
    df = df[df["n"]>=3] if st.checkbox("Only ≥3 IPOs", True) else df
    df = df[["lead_manager","n","self_anchor_n","avg_listing_gain","avg_ret_since_listing","med_ret_since_listing","pct_since_pos","avg_d30","best","best_ret","worst","worst_ret","issue_cr"]]
    df.columns = ["Lead Manager","#IPOs","Self-anch","Avg List Gain%","Avg Since List%","Med Since%","Win%","Avg +30d%","Best","Best%","Worst","Worst%","₹cr"]
    st.dataframe(df.sort_values("Avg Since List%", ascending=False), use_container_width=True, height=560, hide_index=True)

with T[1]:
    seg2 = st.radio("Segment", ["All","SME","Mainboard"], horizontal=True, key="s2")
    only = st.checkbox("Self-anchored only", False)
    d = [r for r in rows if (seg2=="All" or r["segment"]==seg2) and (not only or r.get("self_anchor"))]
    df = pd.DataFrame([{"Company":r["company"],"⚓":"✓" if r.get("self_anchor") else "","Seg":r["segment"],
        "Lead Manager":r.get("lead_manager"),"Issue":r.get("issue_price"),"Listed":r.get("listing_date"),
        "List Gain%":r.get("listing_gain_pct"),"Now":r.get("current_price"),"ATH":r.get("all_time_high"),
        "Since List%":r.get("ret_from_listing_pct"),"From ATH%":r.get("drawdown_from_ath_pct"),
        "+30d%":(r.get("fwd_from_listing") or {}).get("d30")} for r in d])
    st.dataframe(df.sort_values("Since List%", ascending=False), use_container_width=True, height=560, hide_index=True)

with T[2]:
    st.subheader("Signal 1 — Anchor: the banker's own fund invests at IPO (EPW/GetFive mechanism)")
    a,b = st.columns(2)
    a.metric(f"SME · self-anchored (n={se['n']})", pct(se["avg_since_listing"]), f"+30d {pct(se['avg_d30'])}")
    b.metric(f"SME · no self-anchor (n={ne['n']})", pct(ne["avg_since_listing"]), f"+30d {pct(ne['avg_d30'])}")
    st.caption("Small sample; brand-name match. Standout: GetFive→EPW. Most others lagged.")
    st.dataframe(pd.DataFrame(DB["self_anchor_events"]), use_container_width=True, height=320, hide_index=True)
    st.subheader("Signal 2 — Secondary: banker/market-maker buys in bulk deals after listing")
    st.write({f"+{k[1:]}d": pct(v) for k,v in bf.items()} if bf else "Upload deals to compute.")
    st.dataframe(pd.DataFrame((DB.get("backtest") or {}).get("by_manager", [])), use_container_width=True, height=300, hide_index=True)

with T[3]:
    st.caption("Anchor funds ranked by avg CURRENT gain of the IPOs they anchored (SME, ≥3 issues). Follow the ones that pick winners.")
    st.dataframe(pd.DataFrame(DB["anchor_fund_league"]).sort_values("avg_current_gain", ascending=False),
                 use_container_width=True, height=560, hide_index=True)

with T[4]:
    st.caption("Strict: buyer = that stock's OWN lead manager (fixes earlier false positives). From last committed deals.")
    st.dataframe(pd.DataFrame(DB.get("today_signals_strict", [])), use_container_width=True, height=420, hide_index=True)

with T[5]:
    st.subheader("Upload today's NSE Bulk & Block deal CSVs")
    st.caption("Download from NSE → Reports → Bulk/Block Deals, then drop them here. The app finds every deal "
               "where a stock's own lead manager (or its fund) is BUYING, and updates the signal live.")
    up_bulk = st.file_uploader("Bulk deals CSV(s)", type="csv", accept_multiple_files=True, key="ub")
    up_block = st.file_uploader("Block deals CSV(s)", type="csv", accept_multiple_files=True, key="uk")
    def parse(files):
        out=[]
        for f in files or []:
            raw=f.getvalue().decode("utf-8-sig","ignore").splitlines()
            r=list(csv.reader(raw))
            if not r: continue
            h=[c.strip().lower() for c in r[0]]
            def col(*s):
                for i,c in enumerate(h):
                    if any(x in c for x in s): return i
                return None
            ix={"date":col("date"),"sym":col("symbol"),"cli":col("client"),"bs":col("buy / sell","buy/sell","buy"),
                "qty":col("quantity","qty"),"px":col("price","wght","watp")}
            for row in r[1:]:
                if not any(row): continue
                g=lambda k: row[ix[k]].strip() if ix[k] is not None and ix[k]<len(row) else ""
                out.append({"date":g("date"),"sym":g("sym").upper(),"client":g("cli"),
                            "side":g("bs").upper(),"qty":g("qty"),"px":g("px")})
        return out
    if up_bulk or up_block:
        deals = parse(up_bulk)+parse(up_block)
        prices = load_prices()
        def core(lm):
            t=norm(lm).split(); return t[0] if t and len(t[0])>=4 else None
        hits=[]
        for d in deals:
            if not d["side"].startswith("B"): continue
            row = by_sym.get(d["sym"])
            if not row or not row.get("lead_manager"): continue
            c = core(row["lead_manager"])
            if c and c in norm(d["client"]):
                # current stats from price series
                s = prices.get(d["sym"], []); cur = s[-1][3] if s else None
                try: entry=float(str(d["px"]).replace(",",""))
                except: entry=None
                hits.append({"Date":d["date"],"Company":row["company"],"Lead Manager":row["lead_manager"],
                    "Buyer (client)":d["client"],"Qty":d["qty"],"Buy ₹":d["px"],
                    "Now ₹":cur,"Since buy %":(round((cur/entry-1)*100,1) if cur and entry else None)})
        st.success(f"Parsed {len(deals):,} deals → **{len(hits)} where the stock's own lead manager was BUYING**.")
        if hits:
            st.dataframe(pd.DataFrame(hits).sort_values("Date", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("No own-lead-manager buys in these files (this is a rare, high-conviction event).")
        with st.expander("All matched buyers incl. known market-makers (looser)"):
            MM=["nikunj","giriraj","gretex","nnm ","ss corporate","black fox","aftertrade","spread x","rikhav","aequitas"]
            loose=[d for d in deals if d["side"].startswith("B") and d["sym"] in by_sym and any(m in norm(d["client"]) for m in MM)]
            st.dataframe(pd.DataFrame(loose), use_container_width=True, hide_index=True)

st.caption("Data: 985 IPOs (Jul-2023→today), NSE+BSE bhavcopy prices, Chittorgarh lead-manager & anchor allocations, "
           "NSE bulk/block deals. Anchor match is brand-name based; bulk deals capture only trades ≥0.5%/day. Research tool, not advice.")
