#!/usr/bin/env python3
"""
advisor_backtest.py  —  THE CORE BACKTEST.

For every IPO, find bulk/block-deal BUYS by that IPO's own lead manager / market maker,
pair them FIFO with later SELLS to get realised holding-period returns, and for anything
still open show high-since-entry, drawdown, and current return. Aggregate per lead manager.

Inputs (same folder):
  cg_master.json                          (IPO -> lead_manager, nse_symbol, segment)
  nse_all.csv [, bse_all.csv]             (daily prices; produced by bhav_dl.py/bse_dl.py)
  bulk_deals.csv [, block_deals.csv]      (produced by fetch_bulk_deals.py on your PC)

Output: advisor_trades.json, and merges a 'backtest' block into app_data.json + re-injects HTML.
"""
import json, csv, re, datetime as dt, os
FWD=[5,10,15,30]
# SME market-maker / prop brokers often used alongside the banker (extend freely):
MARKET_MAKERS=["nikunj stock","ss corporate","giriraj","gretex","black fox","nnm securities",
  "spread x","aftertrade","alacrity","raghunath","rikhav","aequitas","precision share",
  "share india","choice equity","bp equities","prabhat financial","kunvarji"]

def norm(n):
    n=(n or "").lower()
    for w in ["private","limited","ltd.","ltd","pvt.","pvt","llp","advisors","advisory","advisers",
              "capital","securities","services","broking","brokers","(india)","india","financial",
              "finance","markets","market","and","&","the"," - "]:
        n=n.replace(w," ")
    return re.sub(r"\s+"," ",n).strip()
def core(lead):
    t=norm(lead)
    return t if len(t)>=4 else ""
def pdate(s):
    s=s.strip()
    for f in ("%Y-%m-%d","%d-%b-%Y","%d-%B-%Y","%d-%m-%Y"):
        try: return dt.datetime.strptime(s[:11].strip(),f).date()
        except: pass
    return None

master=json.load(open("cg_master.json"))
bysym={m["nse_symbol"].upper():m for m in master if m.get("nse_symbol")}

# ---- price series by symbol ----
series={}
def load_prices(path):
    if not os.path.exists(path): return
    with open(path) as f:
        for row in csv.reader(f):
            if len(row)<8: continue
            sym=(row[1] or "").upper()
            if sym not in bysym: continue
            try: d=row[0]; h=float(row[5]); l=float(row[6]); c=float(row[7])
            except: continue
            series.setdefault(sym,[]).append((d,h,l,c))
load_prices("ipo_prices.csv"); load_prices("nse_all.csv"); load_prices("bse_all.csv")
for s in series: series[s].sort(key=lambda x:x[0])

def idx_on_or_after(sym,d):
    s=series.get(sym) or []; iso=d.isoformat()
    for i,(dd,_,_,_) in enumerate(s):
        if dd>=iso: return i
    return None
def fwd_from(sym,i):
    s=series[sym]; base=s[i][3]; o={}
    for n in FWD:
        o["d%d"%n]=round((s[i+n][3]/base-1)*100,1) if i+n<len(s) else None
    return o
def open_stats(sym,i,entry_px):
    s=series[sym]; seg=s[i:]
    if not seg: return {}
    highs=[x[1] for x in seg]; closes=[x[3] for x in seg]
    hi=max(highs); cur=closes[-1]
    peak=-1; dd=0
    for x in seg:
        peak=max(peak,x[1]); dd=min(dd,(x[2]/peak-1)*100)
    return {"high_since":round(hi,2),"high_ret":round((hi/entry_px-1)*100,1),
            "current":round(cur,2),"cur_ret":round((cur/entry_px-1)*100,1),
            "max_drawdown":round(dd,1),"days":len(seg)}

# ---- load & filter deals to advisor buys/sells on that stock ----
def load_deals(path):
    out=[]
    if not os.path.exists(path): return out
    with open(path,encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sym=(r.get("Symbol") or "").upper()
            if sym not in bysym: continue
            m=bysym[sym]; c=core(m.get("lead_manager"))
            client=norm(r.get("Client Name"))
            matched=None
            if c and c in client: matched=m["lead_manager"]
            else:
                for mm in MARKET_MAKERS:
                    if mm in client: matched="(market maker) "+ (r.get("Client Name") or "").strip(); break
            if not matched: continue
            d=pdate(r.get("Date") or "")
            try: qty=float((r.get("Quantity Traded") or "0").replace(",",""))
            except: qty=0
            try: px=float((r.get("Trade Price / Wght. Avg. Price") or "0").replace(",",""))
            except: px=0
            out.append({"symbol":sym,"company":m["company"],"segment":m["segment"],
                "lead_manager":m["lead_manager"],"matched":matched,"date":d,
                "side":(r.get("Buy/Sell") or "").strip().upper(),"qty":qty,"price":px})
    return out
deals=load_deals("bulk_deals.csv")+load_deals("block_deals.csv")
# fallback: if user hasn't fetched history yet, use today's snapshot so the tab isn't empty
if not deals and os.path.exists("today_bulk.csv"):
    deals=load_deals("today_bulk.csv")

# ---- FIFO pair per (symbol, matched entity) ----
from collections import defaultdict
grp=defaultdict(lambda:{"buys":[],"sells":[]})
for d in deals:
    if not d["date"]: continue
    (grp[(d["symbol"],d["matched"])]["buys" if d["side"].startswith("B") else "sells"]).append(d)

trades=[]
for (sym,ent),g in grp.items():
    buys=sorted(g["buys"],key=lambda x:x["date"]); sells=sorted(g["sells"],key=lambda x:x["date"])
    lots=[[b["date"],b["qty"],b["price"],b] for b in buys]  # open lots
    si=0
    for s in sells:
        remain=s["qty"]
        for lot in lots:
            if lot[1]<=0 or remain<=0: continue
            if lot[0]>s["date"]: continue
            take=min(lot[1],remain); lot[1]-=take; remain-=take
            ret=round((s["price"]/lot[2]-1)*100,1) if lot[2] else None
            trades.append({"symbol":sym,"company":bysym[sym]["company"],"segment":bysym[sym]["segment"],
                "lead_manager":bysym[sym]["lead_manager"],"buyer":ent,"status":"closed",
                "entry_date":lot[0].isoformat(),"entry_price":lot[2],"exit_date":s["date"].isoformat(),
                "exit_price":s["price"],"holding_days":(s["date"]-lot[0]).days,"realised_ret":ret})
    for lot in lots:
        if lot[1]<=0: continue
        i=idx_on_or_after(sym,lot[0])
        ev={"symbol":sym,"company":bysym[sym]["company"],"segment":bysym[sym]["segment"],
            "lead_manager":bysym[sym]["lead_manager"],"buyer":ent,"status":"open",
            "entry_date":lot[0].isoformat(),"entry_price":lot[2]}
        if i is not None:
            ev.update(open_stats(sym,i,lot[2])); ev["fwd"]=fwd_from(sym,i)
        trades.append(ev)

# ---- aggregates per lead manager ----
def avg(x):
    x=[v for v in x if v is not None]; return round(sum(x)/len(x),1) if x else None
bym=defaultdict(list)
for t in trades: bym[t["lead_manager"]].append(t)
by_manager=[]
for lm,ts in bym.items():
    closed=[t for t in ts if t["status"]=="closed"]; opn=[t for t in ts if t["status"]=="open"]
    by_manager.append({"lead_manager":lm,"buys":len(ts),"closed":len(closed),"open":len(opn),
        "avg_realised":avg([t.get("realised_ret") for t in closed]),
        "win_realised":(round(100*sum(1 for t in closed if (t.get('realised_ret') or 0)>0)/len(closed)) if closed else None),
        "avg_hold_days":avg([t.get("holding_days") for t in closed]),
        "avg_open_ret":avg([t.get("cur_ret") for t in opn]),
        "avg_peak_ret":avg([t.get("high_ret") for t in opn]),
        "avg_fwd30":avg([ (t.get("fwd") or {}).get("d30") for t in opn])})
by_manager.sort(key=lambda x:-(x["buys"]))

# ---- thesis edge: fwd returns after advisor buys vs after plain listing ----
buyfwd={f"d{n}":avg([(t.get('fwd') or {}).get(f'd{n}') for t in trades if t['status']=='open']) for n in FWD}

D=json.load(open("app_data.json")) if os.path.exists("app_data.json") else {"rows":[]}
D["backtest"]={"generated":str(dt.date.today()),"n_trades":len(trades),
   "n_deals_matched":len(deals),"trades":trades,"by_manager":by_manager,"buy_fwd":buyfwd,
   "source":"bulk_deals.csv+block_deals.csv" if os.path.exists("bulk_deals.csv") else "today snapshot only (run fetch_bulk_deals.py for full history)"}
json.dump(D["backtest"],open("advisor_trades.json","w"),indent=1)
json.dump(D,open("app_data.json","w"))
print("matched advisor deals:",len(deals),"| trades:",len(trades),
      "| closed:",sum(1 for t in trades if t['status']=='closed'),
      "| open:",sum(1 for t in trades if t['status']=='open'))
print("buy_fwd:",buyfwd)
for r in by_manager[:8]:
    print(f"  {r['lead_manager'][:24]:25s} buys={r['buys']:3d} closedAvg={r['avg_realised']} openAvg={r['avg_open_ret']} peakAvg={r['avg_peak_ret']}")
