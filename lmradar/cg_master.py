#!/usr/bin/env python3
"""Full IPO master WITH LEAD MANAGER from Chittorgarh. Resumable per (fy,cat) slice.
Run repeatedly until it prints ALL_DONE, then it writes cg_master.json."""
import json, re, time, os, urllib.request, datetime as dt
BASE="https://webnodejs.chittorgarh.com/cloud/report/data-read/82"
FYS=[("2023","2023-24"),("2024","2024-25"),("2025","2025-26"),("2026","2026-27")]
CATS=["mainboard","sme"]
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept":"application/json","Referer":"https://www.chittorgarh.com/"}
WS,WE=dt.date(2023,7,1),dt.date.today()
os.makedirs("cg_pairs",exist_ok=True)
MAX_SECONDS=38
def strip(x): return re.sub("<[^>]+>","",str(x or "")).strip()
def num(s):
    try: return float(str(s).replace(",",""))
    except: return None
def pdate(s):
    for f in ("%d-%b-%Y","%Y-%m-%d"):
        try: return dt.datetime.strptime(s[:11],f).date()
        except: pass
    return None
def get(url,tries=6):
    for i in range(tries):
        try:
            req=urllib.request.Request(url,headers=UA)
            with urllib.request.urlopen(req,timeout=25) as r: return json.loads(r.read().decode("utf-8","ignore"))
        except Exception:
            time.sleep(0.5*(i+1))
    return None
def pair(year,fy,cat):
    o,page,empty,fails={},1,0,0
    while page<=250:
        d=get(f"{BASE}/{page}/1/{year}/{fy}/0/{cat}/0?search=&v=1-1")
        if d is None:
            fails+=1
            if fails>=6: break
            page+=1; continue
        fails=0
        rows=d.get("reportTableData",[])
        if not rows:
            empty+=1
            if empty>=2: break
            page+=1; continue
        new=0
        for r in rows:
            key=(strip(r.get("~isin")) or strip(r.get("Company")),strip(r.get("Listing Date")))
            if key in o: continue
            ld=pdate(strip(r.get("Listing Date")))
            o[key]={"company":strip(r.get("Company")),"segment":"SME" if cat=="sme" else "Mainboard",
                "listing_at":strip(r.get("Listing at")),"listing_date":ld.isoformat() if ld else None,
                "issue_price":num(strip(r.get("Issue Price (Rs.)"))),
                "issue_amount_cr":num(strip(r.get("Total Issue Amount (Incl.Firm reservations) (Rs.cr.)"))),
                "lead_manager":strip(r.get("Left Lead Manager")),"isin":strip(r.get("~isin")),
                "nse_symbol":strip(r.get("~nse_symbol")),"bse_code":strip(r.get("~bse_script_code"))}
            new+=1
        empty=empty+1 if new==0 else 0
        if empty>=3: break
        page+=1; time.sleep(0.04)
    return list(o.values())
def main():
    jobs=[(y,fy,c) for (y,fy) in FYS for c in CATS]
    t0=time.time()
    for (y,fy,c) in jobs:
        pf=f"cg_pairs/{fy}_{c}.json"
        if os.path.exists(pf): continue
        if time.time()-t0>MAX_SECONDS: break
        res=pair(y,fy,c)
        json.dump(res,open(pf,"w"))
        print(f"{c} {fy}: {len(res)}")
    done=[f"cg_pairs/{fy}_{c}.json" for (y,fy) in FYS for c in CATS if os.path.exists(f"cg_pairs/{fy}_{c}.json")]
    if len(done)==len(jobs):
        allrows={}
        for pf in done:
            for v in json.load(open(pf)): allrows[(v["isin"] or v["company"],v["listing_date"])]=v
        out=[v for v in allrows.values() if v["listing_date"] and WS<=dt.date.fromisoformat(v["listing_date"])<=WE]
        out.sort(key=lambda x:x["listing_date"],reverse=True)
        json.dump(out,open("cg_master.json","w"),indent=1)
        sme=sum(1 for x in out if x["segment"]=="SME")
        print(f"TOTAL in window: {len(out)} (SME {sme}, Mainboard {len(out)-sme}) with_lead_mgr={sum(1 for x in out if x['lead_manager'])}")
        print("ALL_DONE")
    else:
        print(f"slices done {len(done)}/{len(jobs)} -> MORE")
main()
