#!/usr/bin/env python3
"""Join cg_master with bhavcopy price data (match by ISIN) -> ipo_full.json with all metrics."""
import json, csv, datetime as dt
FWD=[5,10,15,30,60,90]
import glob
def _concat(parts_dir, out):
    import os
    if os.path.exists(out) or not os.path.isdir(parts_dir): return
    with open(out,"w") as o:
        for p in sorted(glob.glob(parts_dir+"/*.csv")):
            d=open(p).read()
            if d: o.write(d if d.endswith("\n") else d+"\n")
_concat("bhav_parts","nse_all.csv"); _concat("bse_parts","bse_all.csv")
master=json.load(open("cg_master.json"))
# target ISIN -> master row
byisin={}
for m in master:
    if m.get("isin"): byisin.setdefault(m["isin"],m)
targets=set(byisin)
# accumulate series per ISIN: dict isin -> list[(date,high,low,close,lot)]
series={}
def ingest(path):
    with open(path) as f:
        for row in csv.reader(f):
            if len(row)<8: continue
            isin=row[3]
            if isin not in targets: continue
            try:
                d=row[0]; h=float(row[5]); l=float(row[6]); c=float(row[7])
            except: continue
            lot=row[9] if len(row)>9 else ""
            series.setdefault(isin,[]).append((d,h,l,c,lot))
ingest("nse_all.csv"); ingest("bse_all.csv")
def fwd(cl,i):
    o={}; base=cl[i]
    for n in FWD:
        o["d%d"%n]=round((cl[i+n]/base-1)*100,1) if i+n<len(cl) else None
    return o
out=[]
for m in master:
    r=dict(m); isin=m.get("isin"); s=series.get(isin)
    r["data_status"]={}
    if not s:
        r.update(listing_price=None,current_price=None,all_time_high=None,all_time_low=None,
                 ath_date=None,atl_date=None,ret_from_listing_pct=None,drawdown_from_ath_pct=None,
                 listing_gain_pct=None,fwd_from_listing={f"d{n}":None for n in FWD},
                 min_investment=None,traded_days=0)
        r["data_status"]["price"]="no bhavcopy match (likely BSE-SME pre-2024 or symbol/ISIN gap)"
        out.append(r); continue
    s.sort(key=lambda x:x[0])
    dates=[x[0] for x in s]; highs=[x[1] for x in s]; lows=[x[2] for x in s]; cl=[x[3] for x in s]
    lots=[x[4] for x in s if x[4] not in ("","0",None)]
    r["listing_price"]=round(cl[0],2); r["current_price"]=round(cl[-1],2)
    imax=highs.index(max(highs)); imin=lows.index(min(lows))
    r["all_time_high"]=round(max(highs),2); r["all_time_low"]=round(min(lows),2)
    r["ath_date"]=dates[imax]; r["atl_date"]=dates[imin]
    r["ret_from_listing_pct"]=round((cl[-1]/cl[0]-1)*100,1)
    r["drawdown_from_ath_pct"]=round((cl[-1]/max(highs)-1)*100,1)
    r["fwd_from_listing"]=fwd(cl,0)
    r["traded_days"]=len(cl)
    ip=m.get("issue_price")
    r["listing_gain_pct"]=round((cl[0]/ip-1)*100,1) if ip else None
    lot=None
    try: lot=int(float(lots[-1])) if lots else None
    except: lot=None
    r["lot_size"]=lot
    r["min_investment"]=round(lot*ip) if (lot and ip) else None
    r["advisor_buy_events"]=[]
    out.append(r)
matched=sum(1 for r in out if r.get("current_price") is not None)
json.dump({"generated":str(dt.date.today()),"window":"2023-07-01 to 2026-07-10","fwd_windows":FWD,
           "rows":out},open("ipo_full.json","w"))
print("IPOs:",len(out),"| with price data:",matched,"| no match:",len(out)-matched)
sme=[r for r in out if r["segment"]=="SME"]; mb=[r for r in out if r["segment"]=="Mainboard"]
def avg(x):
    x=[v for v in x if v is not None]; return round(sum(x)/len(x),1) if x else None
print("SME listing-gain avg:",avg([r["listing_gain_pct"] for r in sme]),"| MB:",avg([r["listing_gain_pct"] for r in mb]))
print("SME since-listing avg:",avg([r["ret_from_listing_pct"] for r in sme]),"| MB:",avg([r["ret_from_listing_pct"] for r in mb]))
