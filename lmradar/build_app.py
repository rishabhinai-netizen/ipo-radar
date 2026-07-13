#!/usr/bin/env python3
"""Integrator: combine prices + LM league + anchor self-backing + bulk-deal backtest +
anchor-fund league + strict Entering-Now -> app_data.json (for build_html.py)."""
import json, csv, re, os, datetime as dt, statistics as st
FWD=[5,10,15,30,60,90]
full=json.load(open("ipo_full.json")); rows=full["rows"]
anchor_ev=json.load(open("anchor_events.json"))
anchor_funds=json.load(open("anchor_funds.json"))
trades=json.load(open("advisor_trades.json"))["trades"] if os.path.exists("advisor_trades.json") else []
def norm(n):
    n=(n or "").lower()
    for w in ["private","limited","ltd.","ltd","pvt.","pvt","advisors","advisory","advisers","capital",
              "securities","services","financial","finance","(india)","india","corporate","markets","&","and","the"]:
        n=n.replace(w," ")
    return re.sub(r"\s+"," ",n).strip()
def avg(a): a=[x for x in a if x is not None]; return round(sum(a)/len(a),1) if a else None
def med(a): a=[x for x in a if x is not None]; return round(st.median(a),1) if a else None
def pctpos(a): a=[x for x in a if x is not None]; return round(100*sum(1 for x in a if x>0)/len(a)) if a else None

# index IPO rows
by_sym={r["nse_symbol"].upper():r for r in rows if r.get("nse_symbol")}
by_isin={r["isin"]:r for r in rows if r.get("isin")}
def find_row(ev):
    if ev.get("nse_symbol") and ev["nse_symbol"].upper() in by_sym: return by_sym[ev["nse_symbol"].upper()]
    if ev.get("isin") and ev["isin"] in by_isin: return by_isin[ev["isin"]]
    return None

# ---- attach anchor self-backing to IPO rows ----
for r in rows: r["self_anchor"]=None; r["anchor_funds_all"]=[]
self_events=[]
for ev in anchor_ev:
    r=find_row(ev)
    lm_ipo=(r["lead_manager"] if r else ev.get("lead_manager")) or ""
    is_self = ev.get("brand_lm") and norm(ev["brand_lm"]).split() and norm(ev["brand_lm"]).split()[0] in norm(lm_ipo)
    rec={"fund":ev["scheme"] or ev["group"],"shares":ev["shares"],"amount_cr":ev["amount_cr"],
         "issue_price":ev["issue_price"],"market_gain_pct":ev["market_gain_pct"],"listing_gain_pct":ev["listing_gain_pct"]}
    if r is not None:
        r["anchor_funds_all"].append({**rec,"brand_lm":ev.get("brand_lm")})
        if is_self:
            r["self_anchor"]={**rec,"lead_manager":lm_ipo}
    if is_self:
        self_events.append({"company":ev["company"],"segment":ev["segment"],"nse_symbol":ev.get("nse_symbol"),
            "lead_manager":lm_ipo,"fund":ev["scheme"] or ev["group"],"shares":ev["shares"],"amount_cr":ev["amount_cr"],
            "issue_price":ev["issue_price"],"listing_gain_pct":ev["listing_gain_pct"],"market_gain_pct":ev["market_gain_pct"],
            "ret_from_listing_pct":(r["ret_from_listing_pct"] if r else None),
            "drawdown_from_ath_pct":(r["drawdown_from_ath_pct"] if r else None)})

# ---- LM league (with self-anchor rate) ----
def league(scope):
    g={}
    for r in rows:
        if scope!="All" and r["segment"]!=scope: continue
        if not r.get("lead_manager"): continue
        g.setdefault(norm(r["lead_manager"]),{"disp":{}, "rows":[]})
        g[norm(r["lead_manager"])]["rows"].append(r)
        g[norm(r["lead_manager"])]["disp"][r["lead_manager"]]=g[norm(r["lead_manager"])]["disp"].get(r["lead_manager"],0)+1
    out=[]
    for k,v in g.items():
        rs=v["rows"]; disp=max(v["disp"],key=v["disp"].get)
        best=max(rs,key=lambda r:(r["ret_from_listing_pct"] or -1e9)); worst=min(rs,key=lambda r:(r["ret_from_listing_pct"] or 1e9))
        out.append({"lead_manager":disp,"n":len(rs),
            "avg_listing_gain":avg([r["listing_gain_pct"] for r in rs]),"med_listing_gain":med([r["listing_gain_pct"] for r in rs]),
            "avg_ret_since_listing":avg([r["ret_from_listing_pct"] for r in rs]),"med_ret_since_listing":med([r["ret_from_listing_pct"] for r in rs]),
            "pct_since_pos":pctpos([r["ret_from_listing_pct"] for r in rs]),"avg_d30":avg([(r["fwd_from_listing"] or {}).get("d30") for r in rs]),
            "self_anchor_n":sum(1 for r in rs if r.get("self_anchor")),
            "best":best["company"],"best_ret":best["ret_from_listing_pct"],"worst":worst["company"],"worst_ret":worst["ret_from_listing_pct"],
            "issue_cr":round(sum(r.get("issue_amount_cr") or 0 for r in rs),1)})
    out.sort(key=lambda x:(-(x["n"]>=3),-(x["avg_ret_since_listing"] or -1e9)))
    return out
LEAGUE={s:league(s) for s in ["All","SME","Mainboard"]}

# ---- refined edge: self-anchored vs not (SME) ----
def edge(seg):
    pool=[r for r in rows if seg=="All" or r["segment"]==seg]
    a=[r for r in pool if r.get("self_anchor")]; b=[r for r in pool if not r.get("self_anchor")]
    f=lambda s:{"n":len(s),"avg_listing_gain":avg([r["listing_gain_pct"] for r in s]),
        "avg_since_listing":avg([r["ret_from_listing_pct"] for r in s]),"win_since":pctpos([r["ret_from_listing_pct"] for r in s]),
        "avg_d30":avg([(r["fwd_from_listing"] or {}).get("d30") for r in s])}
    return {"self_anchored":f(a),"not_anchored":f(b)}
EDGE={"SME":edge("SME"),"All":edge("All")}

# ---- anchor fund league (smart-money follow) ----
afl=sorted([f for f in anchor_funds if f["segment"]=="SME" and (f["n_issues"] or 0)>=3],
           key=lambda x:-(x["avg_current_gain"] or -1e9))
anchor_fund_league=[{"fund":f["name"],"n_issues":f["n_issues"],"avg_listing_gain":f["avg_listing_gain"],
    "avg_current_gain":f["avg_current_gain"],"total_inv_cr":f["total_inv_cr"],"brand_lm":None} for f in afl]

# ---- strict Entering-Now: recent bulk BUYs where buyer == stock's own LM/affiliate ----
def core1(lm): 
    t=norm(lm).split(); return t[0] if t and len(t[0])>=4 else None
signals=[]
if os.path.exists("bulk_deals.csv"):
    allrows=list(csv.DictReader(open("bulk_deals.csv",encoding="utf-8")))
    def pdate(s):
        for f in("%d-%b-%Y","%d-%B-%Y","%Y-%m-%d"):
            try: return dt.datetime.strptime(s.strip()[:11],f).date()
            except: pass
        return None
    dated=[(pdate(r.get("Date","")),r) for r in allrows]; dated=[(d,r) for d,r in dated if d]
    if dated:
        maxd=max(d for d,_ in dated); cutoff=maxd-dt.timedelta(days=45)
        for d,r in dated:
            if d<cutoff: continue
            if not (r.get("Buy/Sell","").strip().upper().startswith("B")): continue
            sym=(r.get("Symbol","") or "").strip().upper()
            row=by_sym.get(sym)
            if not row or not row.get("lead_manager"): continue
            c=core1(row["lead_manager"]); client=norm(r.get("Client Name",""))
            if c and c in client:
                signals.append({"date":d.isoformat(),"symbol":sym,"company":row["company"],"lead_manager":row["lead_manager"],
                    "client":r.get("Client Name","").strip(),"qty":r.get("Quantity Traded"),"price":r.get("Trade Price / Wght. Avg. Price")})
    signals.sort(key=lambda x:x["date"],reverse=True)

payload={"generated":str(dt.date.today()),"window":full["window"],"fwd_windows":FWD,"rows":rows,
  "league":LEAGUE,"edge_selfanchor":EDGE,"anchor_fund_league":anchor_fund_league,
  "self_anchor_events":sorted(self_events,key=lambda x:-(x["market_gain_pct"] or -1e9)),
  "backtest":{"trades":trades,"by_manager":json.load(open("advisor_trades.json")).get("by_manager",[]) if os.path.exists("advisor_trades.json") else [],
              "buy_fwd":json.load(open("advisor_trades.json")).get("buy_fwd",{}) if os.path.exists("advisor_trades.json") else {}},
  "today_signals_strict":signals}
json.dump(payload,open("app_data.json","w"))
print("rows",len(rows),"| self-anchored IPOs",sum(1 for r in rows if r.get("self_anchor")),
      "| self_events",len(self_events),"| anchor_fund_league",len(anchor_fund_league),"| strict signals",len(signals))
print("EDGE SME self-anchored:",EDGE["SME"]["self_anchored"])
print("EDGE SME not-anchored:",EDGE["SME"]["not_anchored"])
