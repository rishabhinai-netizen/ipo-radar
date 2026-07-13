#!/usr/bin/env python3
"""BSE bhavcopy (UDiFF 2024+), keep SME series M/MT/MS -> bse_parts/DATE.csv. Time-bounded, resumable."""
import os, csv, time, datetime as dt, urllib.request, concurrent.futures as cf
START, END = dt.date(2024,1,1), dt.date.today(); MAX_SECONDS=40
KEEP={"M","MT","MS"}; OUT="bse_parts"; os.makedirs(OUT,exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120","Referer":"https://www.bseindia.com/"}
def url_for(d): return f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.CSV"
def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r: return r.read().decode("utf-8","ignore")
def do(d):
    out=os.path.join(OUT,d.strftime("%Y-%m-%d")+".csv")
    if os.path.exists(out): return
    tmp=out+".tmp"
    try: txt=fetch(url_for(d)).splitlines()
    except:
        open(tmp,"w").close(); os.replace(tmp,out); return
    rd=csv.DictReader(txt); rows=[]
    for r in rd:
        r={k.strip():(v.strip() if isinstance(v,str) else v) for k,v in r.items()}
        if r.get("SctySrs","") not in KEEP: continue
        rows.append([d.isoformat(),r.get("TckrSymb"),r.get("SctySrs"),r.get("ISIN"),r.get("OpnPric"),r.get("HghPric"),r.get("LwPric"),r.get("ClsPric"),r.get("TtlTradgVol"),r.get("NewBrdLotQty"),r.get("FinInstrmNm")])
    with open(tmp,"w",newline="") as f:
        w=csv.writer(f)
        for x in rows: w.writerow(x)
    os.replace(tmp,out)
def main():
    days=[]; d=START
    while d<=END:
        if d.weekday()<5: days.append(d)
        d+=dt.timedelta(days=1)
    todo=[d for d in days if not os.path.exists(os.path.join(OUT,d.strftime("%Y-%m-%d")+".csv"))]
    t0=time.time()
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs=[]
        for d in todo:
            if time.time()-t0>MAX_SECONDS: break
            futs.append(ex.submit(do,d))
        for _ in cf.as_completed(futs): pass
    rem=sum(1 for d in days if not os.path.exists(os.path.join(OUT,d.strftime("%Y-%m-%d")+".csv")))
    print(f"progress {len(days)-rem}/{len(days)} remaining={rem}"); print("ALL_DONE" if rem==0 else "MORE")
main()
