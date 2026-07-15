# -*- coding: utf-8 -*-
"""Lead-Manager Radar — page for the IPO Radar app.
Bankers' IPO performance, anchor self-backing, anchor-fund track records, and a bulk/block
UPLOAD that stores deals in Supabase and recomputes the 'banker is buying' signal live."""
import streamlit as st, pandas as pd, json, csv, re, os, datetime as dt, urllib.request, urllib.parse

st.set_page_config(page_title="Lead-Manager Radar", page_icon="🎯", layout="wide")
BASE = os.path.join(os.path.dirname(__file__), "..", "lmradar")

# ---- Supabase (anon key is public by design; RLS-guarded) ----
SUPA_URL = st.secrets.get("SUPABASE_URL", "https://aiebaqvclyzxajigvkfd.supabase.co")
SUPA_KEY = st.secrets.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFpZWJhcXZjbHl6eGFqaWd2a2ZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5NTg1MDQsImV4cCI6MjA5MDUzNDUwNH0.m_WLKdaKwEw82RRepHYhXp3tg-g0pwMiDKM2S7Y7XdY")
def _hdr(extra=None):
    h={"apikey":SUPA_KEY,"Authorization":f"Bearer {SUPA_KEY}","Content-Type":"application/json"}
    if extra: h.update(extra)
    return h
def supa_get(path):
    try:
        r=urllib.request.Request(f"{SUPA_URL}/rest/v1/{path}", headers=_hdr())
        with urllib.request.urlopen(r,timeout=20) as f: return json.load(f)
    except Exception as e: return {"_err":str(e)}
def supa_insert(table, rows, ignore=True):
    try:
        pref="resolution=ignore-duplicates" if ignore else "resolution=merge-duplicates"
        r=urllib.request.Request(f"{SUPA_URL}/rest/v1/{table}", data=json.dumps(rows).encode(),
            headers=_hdr({"Prefer":f"{pref},return=representation"}), method="POST")
        with urllib.request.urlopen(r,timeout=40) as f: return json.load(f)
    except urllib.error.HTTPError as e: return {"_err":f"{e.code} {e.read()[:120]}"}
    except Exception as e: return {"_err":str(e)}

@st.cache_data(show_spinner=False)
def load_db():
    with open(os.path.join(BASE,"app_data.json"),encoding="utf-8") as f: return json.load(f)
@st.cache_data(show_spinner=True)
def load_prices():
    p=os.path.join(BASE,"nse_all.csv"); s={}
    if not os.path.exists(p): return s
    with open(p) as f:
        for r in csv.reader(f):
            if len(r)<8: continue
            try: s.setdefault(r[1].upper(),[]).append((r[0],float(r[7])))
            except: pass
    for k in s: s[k].sort()
    return s
@st.cache_data(ttl=120, show_spinner=False)
def load_deals_from_supa():
    d=supa_get("lmr_deals?select=deal_date,symbol,client_name,side,qty,price,deal_type&limit=200000")
    return d if isinstance(d,list) else []

DB=load_db(); rows=DB["rows"]; by_sym={r["nse_symbol"].upper():r for r in rows if r.get("nse_symbol")}
def norm(n):
    n=(n or "").lower()
    for w in ["private","limited","ltd.","ltd","pvt.","pvt","advisors","advisory","capital","securities",
              "services","financial","finance","(india)","india","corporate","markets","&","and","the"]:
        n=n.replace(w," ")
    return re.sub(r"\s+"," ",n).strip()
def core(lm):
    t=norm(lm).split(); return t[0] if t and len(t[0])>=4 else None
def pctf(v): return "—" if v is None else f"{'+' if v>=0 else ''}{v}%"
def pdate(s):
    for f in ("%d-%b-%Y","%d-%B-%Y","%Y-%m-%d","%d-%m-%Y"):
        try: return dt.datetime.strptime(str(s).strip()[:11],f).date().isoformat()
        except: pass
    return None

# ---------- STATUS BAR (two-part: auto vs upload) ----------
stt=supa_get("lmr_status?component=eq.lmradar_data&select=data_date,deals_date,last_run_utc,ipo_count")
def _stale(dstr, days):
    return not (dstr and dstr >= (dt.date.today()-dt.timedelta(days=days)).isoformat())
if isinstance(stt,list) and stt:
    s0=stt[0]
    c1,c2=st.columns(2)
    pfresh=not _stale(s0.get("data_date"),3)
    c1.success(f"{'🟢' if pfresh else '🟠'} **Prices & IPOs — AUTO** · latest {s0.get('data_date')} · {s0.get('ipo_count')} IPOs · runs daily")
    dfresh=not _stale(s0.get("deals_date"),3)
    c2.warning(f"{'🟢' if dfresh else '🟠'} **Bulk/Block deals — UPLOAD** · current through {s0.get('deals_date') or '—'} · "
               f"{'up to date' if dfresh else 'upload today’s file for live buy signals'}")
    st.caption(f"Auto pipeline last ran {str(s0.get('last_run_utc'))[:16].replace('T',' ')} UTC. "
               f"Prices/IPO-master/anchor refresh on their own; NSE blocks deal downloads from the cloud, so deals come from your uploads (▶ Upload daily deals).")
else:
    st.warning("Status unavailable (Supabase not reachable yet).")

st.title("🎯 Lead-Manager Radar")
e=DB["edge_selfanchor"]["SME"]; se,ne=e["self_anchored"],e["not_anchored"]; bf=(DB.get("backtest") or {}).get("buy_fwd",{})
st.caption(f"Verdict: League & Anchor-Fund tables are reliable screens. Self-anchor edge unproven "
           f"(SME self-anchored {pctf(se['avg_since_listing'])} vs {pctf(ne['avg_since_listing'])} since listing). Research tool, not advice.")

T=st.tabs(["🏆 League","📋 All IPOs","🎯 Advisor Signals","⚓ Anchor Funds","📡 Entering Now","⬆️ Upload daily deals"])
with T[0]:
    seg=st.radio("Segment",["SME","Mainboard","All"],horizontal=True,key="lseg")
    df=pd.DataFrame(DB["league"][seg]); df=df[df["n"]>=3] if st.checkbox("Only ≥3 IPOs",True) else df
    df=df[["lead_manager","n","self_anchor_n","avg_listing_gain","avg_ret_since_listing","pct_since_pos","avg_d30","best","best_ret","worst","worst_ret","issue_cr"]]
    df.columns=["Lead Manager","#IPOs","Self-anch","Avg List Gain%","Avg Since List%","Win%","Avg +30d%","Best","Best%","Worst","Worst%","₹cr"]
    st.dataframe(df.sort_values("Avg Since List%",ascending=False),use_container_width=True,height=560,hide_index=True)
with T[1]:
    seg2=st.radio("Segment",["All","SME","Mainboard"],horizontal=True,key="s2"); only=st.checkbox("Self-anchored only",False)
    d=[r for r in rows if (seg2=="All" or r["segment"]==seg2) and (not only or r.get("self_anchor"))]
    st.dataframe(pd.DataFrame([{"Company":r["company"],"⚓":"✓" if r.get("self_anchor") else "","Seg":r["segment"],
        "Lead Manager":r.get("lead_manager"),"Issue":r.get("issue_price"),"Listed":r.get("listing_date"),
        "List Gain%":r.get("listing_gain_pct"),"Now":r.get("current_price"),"Since List%":r.get("ret_from_listing_pct"),
        "From ATH%":r.get("drawdown_from_ath_pct"),"+30d%":(r.get("fwd_from_listing") or {}).get("d30")} for r in d]).sort_values("Since List%",ascending=False),
        use_container_width=True,height=560,hide_index=True)
with T[2]:
    a,b=st.columns(2)
    a.metric(f"SME self-anchored (n={se['n']})",pctf(se["avg_since_listing"]),f"+30d {pctf(se['avg_d30'])}")
    b.metric(f"SME no self-anchor (n={ne['n']})",pctf(ne["avg_since_listing"]),f"+30d {pctf(ne['avg_d30'])}")
    st.dataframe(pd.DataFrame(DB["self_anchor_events"]),use_container_width=True,height=320,hide_index=True)
    st.write("Bulk-deal buy edge:", {f"+{k[1:]}d":pctf(v) for k,v in bf.items()} if bf else "—")
    st.dataframe(pd.DataFrame((DB.get("backtest") or {}).get("by_manager",[])),use_container_width=True,height=300,hide_index=True)
with T[3]:
    st.caption("Anchor funds ranked by avg CURRENT gain of IPOs they anchored (SME, ≥3 issues).")
    st.dataframe(pd.DataFrame(DB["anchor_fund_league"]).sort_values("avg_current_gain",ascending=False),use_container_width=True,height=560,hide_index=True)
with T[4]:
    st.caption("Strict: buyer = that stock's OWN lead manager. From cumulative deals in Supabase + committed history.")
    st.dataframe(pd.DataFrame(DB.get("today_signals_strict",[])),use_container_width=True,height=360,hide_index=True)

with T[5]:
    st.subheader("Upload today's NSE Bulk & Block deal CSVs → stored in Supabase")
    st.caption("Files are parsed and saved to the `lmr_deals` table (deduped), then the own-lead-manager BUY signal "
               "recomputes over ALL stored deals. Persists across sessions.")
    ub=st.file_uploader("Bulk deals CSV(s)",type="csv",accept_multiple_files=True,key="ub")
    uk=st.file_uploader("Block deals CSV(s)",type="csv",accept_multiple_files=True,key="uk")
    def parse(files,dtype):
        out=[]
        for f in files or []:
            r=list(csv.reader(f.getvalue().decode("utf-8-sig","ignore").splitlines()))
            if not r: continue
            h=[c.strip().lower() for c in r[0]]
            def col(*s):
                for i,c in enumerate(h):
                    if any(x in c for x in s): return i
                return None
            ix={"date":col("date"),"sym":col("symbol"),"nm":col("security","name of"),"cli":col("client"),
                "bs":col("buy / sell","buy/sell","buy"),"qty":col("quantity","qty"),"px":col("price","wght","watp")}
            for row in r[1:]:
                if not any(row): continue
                g=lambda k: (row[ix[k]].strip() if ix[k] is not None and ix[k]<len(row) else "")
                try: qty=float(g("qty").replace(",","")) if g("qty") else None
                except: qty=None
                try: px=float(g("px").replace(",","")) if g("px") else None
                except: px=None
                out.append({"deal_type":dtype,"deal_date":pdate(g("date")),"symbol":g("sym").upper(),
                    "security_name":g("nm"),"client_name":g("cli"),"side":g("bs").upper()[:4],"qty":qty,"price":px,
                    "source":f.name})
        return [x for x in out if x["deal_date"] and x["symbol"]]
    if (ub or uk):
        recs=parse(ub,"bulk")+parse(uk,"block")
        st.write(f"Parsed **{len(recs):,}** rows. Saving to Supabase…")
        # insert in chunks
        saved=0
        for i in range(0,len(recs),500):
            res=supa_insert("lmr_deals",recs[i:i+500],ignore=True)
            if isinstance(res,list): saved+=len(res)
            elif isinstance(res,dict) and res.get("_err"): st.error("Save error: "+res["_err"]); break
        st.success(f"Stored **{saved}** new deals (duplicates skipped). Table: lmr_deals.")
        load_deals_from_supa.clear()
    # cumulative signal from ALL stored deals
    alld=load_deals_from_supa()
    if alld:
        hits=[]
        pser=load_prices()
        for d in alld:
            if not (str(d.get("side","")).upper().startswith("B")): continue
            row=by_sym.get((d.get("symbol") or "").upper())
            if not row or not row.get("lead_manager"): continue
            c=core(row["lead_manager"])
            if c and c in norm(d.get("client_name","")):
                s=pser.get(d["symbol"].upper(),[]); cur=s[-1][1] if s else None; ep=d.get("price")
                hits.append({"Date":d["deal_date"],"Company":row["company"],"Lead Manager":row["lead_manager"],
                    "Buyer":d["client_name"],"Qty":d["qty"],"Buy ₹":ep,"Now ₹":cur,
                    "Since buy %":(round((cur/ep-1)*100,1) if cur and ep else None),"Type":d["deal_type"]})
        st.markdown(f"**{len(alld):,} deals stored** · **{len(hits)} own-lead-manager BUY signals**")
        if hits: st.dataframe(pd.DataFrame(hits).sort_values("Date",ascending=False),use_container_width=True,hide_index=True)
    else:
        st.info("No deals stored yet — upload your first bulk/block files above.")

st.caption("Data: 985 IPOs (Jul-2023→today) · NSE+BSE bhavcopy · Chittorgarh lead-mgr & anchor allocations · deals in Supabase. Not investment advice.")
