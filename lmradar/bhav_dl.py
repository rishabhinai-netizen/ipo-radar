#!/usr/bin/env python3
"""Download NSE bhavcopy (old 2023 + UDiFF 2024+), parse EQ/BE/BZ/SM/ST -> bhav_parts/DATE.csv
Resumable, threaded, time-bounded (~40s/run). Re-run until it prints ALL_DONE."""
import os, io, csv, zipfile, time, datetime as dt, urllib.request, concurrent.futures as cf
START, END = dt.date(2023,7,1), dt.date.today(); MAX_SECONDS=40
KEEP={"EQ","BE","BZ","SM","ST"}; OUT="bhav_parts"; os.makedirs(OUT,exist_ok=True)
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120","Referer":"https://www.nseindia.com/"}
MON=["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
def urls_for(d):
    ymd=d.strftime("%Y%m%d")
    u=f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    o=(f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/{MON[d.month-1]}/"
       f"cm{d.strftime('%d')}{MON[d.month-1]}{d.year}bhav.csv.zip")
    return [u,o] if d.year>=2024 else [o,u]
def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=30) as r: return r.read()
def parse(raw):
    z=zipfile.ZipFile(io.BytesIO(raw)); txt=z.read(z.namelist()[0]).decode("utf-8","ignore").splitlines()
    rd=csv.DictReader(txt); cols=[c.strip() for c in rd.fieldnames]; ud="TckrSymb" in cols; rows=[]
    for r in rd:
        r={k.strip():(v.strip() if isinstance(v,str) else v) for k,v in r.items()}
        if ud:
            s=r.get("SctySrs","")
            if s not in KEEP: continue
            rows.append([r.get("TckrSymb"),s,r.get("ISIN"),r.get("OpnPric"),r.get("HghPric"),r.get("LwPric"),r.get("ClsPric"),r.get("TtlTradgVol"),r.get("NewBrdLotQty"),r.get("FinInstrmNm")])
        else:
            s=r.get("SERIES","")
            if s not in KEEP: continue
            rows.append([r.get("SYMBOL"),s,r.get("ISIN"),r.get("OPEN"),r.get("HIGH"),r.get("LOW"),r.get("CLOSE"),r.get("TOTTRDQTY"),"",""])
    return rows
def do(d):
    out=os.path.join(OUT,d.strftime("%Y-%m-%d")+".csv")
    if os.path.exists(out): return
    tmp=out+".tmp"
    for url in urls_for(d):
        try: rows=parse(fetch(url))
        except: continue
        if rows:
            with open(tmp,"w",newline="") as f:
                w=csv.writer(f)
                for r in rows: w.writerow([d.isoformat()]+r)
            os.replace(tmp,out); return
    open(tmp,"w").close(); os.replace(tmp,out)
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
    print(f"progress {len(days)-rem}/{len(days)} remaining={rem}")
    print("ALL_DONE" if rem==0 else "MORE")
main()
