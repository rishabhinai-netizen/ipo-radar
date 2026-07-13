#!/usr/bin/env python3
"""Daily rebuild of lmradar/app_data.json (runs in GitHub Actions, cloud-safe).
Re-pulls IPO master (new listings), tops up prices, refreshes anchor data, recomputes.
Bulk/block deals come from committed bulk_deals.csv (updated via the app's Upload page)."""
import os, csv, io, zipfile, urllib.request, datetime as dt, json, subprocess, sys, glob, shutil
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120","Referer":"https://www.nseindia.com/"}
KEEP={"EQ","BE","BZ","SM","ST"}
def run(c):
    print(">>"," ".join(c)); r=subprocess.run([sys.executable]+c,capture_output=True,text=True)
    print((r.stdout or "")[-400:]); print((r.stderr or "")[-300:] if r.returncode else "")
    return r.stdout or ""
def loop(script,n):
    for _ in range(n):
        if "ALL_DONE" in run([script]): return
def fetch(u):
    with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=40) as r: return r.read()
def nse_rows(d):
    try:
        z=zipfile.ZipFile(io.BytesIO(fetch(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")))
        txt=z.read(z.namelist()[0]).decode("utf-8","ignore").splitlines(); out=[]
        for r in csv.DictReader(txt):
            r={k.strip():(v.strip() if isinstance(v,str) else v) for k,v in r.items()}
            if r.get("SctySrs") in KEEP:
                out.append([d.isoformat(),r.get("TckrSymb"),r.get("SctySrs"),r.get("ISIN"),r.get("OpnPric"),r.get("HghPric"),r.get("LwPric"),r.get("ClsPric"),r.get("TtlTradgVol"),r.get("NewBrdLotQty"),r.get("FinInstrmNm")])
        return out
    except Exception: return []
def topup():
    syms={x["nse_symbol"].upper() for x in json.load(open("cg_master.json")) if x.get("nse_symbol")}
    have={ln.split(",",1)[0] for ln in open("nse_all.csv")} if os.path.exists("nse_all.csv") else set()
    d=dt.date.today()-dt.timedelta(days=16); add=0
    with open("nse_all.csv","a",newline="") as f:
        w=csv.writer(f)
        while d<=dt.date.today():
            if d.weekday()<5 and d.isoformat() not in have:
                for row in nse_rows(d):
                    if (row[1] or "").upper() in syms: w.writerow(row); add+=1
            d+=dt.timedelta(days=1)
    print("price rows added",add)
if __name__=="__main__":
    if os.path.isdir("cg_pairs"): shutil.rmtree("cg_pairs")   # force fresh master (new IPOs)
    loop("cg_master.py",12)
    if not os.path.exists("nse_all.csv"):        # first run: build full price history
        loop("bhav_dl.py",60); loop("bse_dl.py",60)
        with open("nse_all.csv","w") as o:
            for p in sorted(glob.glob("bhav_parts/*.csv")): o.write(open(p).read())
        with open("bse_all.csv","w") as o:
            for p in sorted(glob.glob("bse_parts/*.csv")): o.write(open(p).read())
    else:
        topup(); open("bse_all.csv","a").close()
    run(["build_prices.py"])
    loop("pull_anchor.py",12); loop("pull_anchor2.py",20)
    run(["advisor_backtest.py"]); run(["build_app.py"])
    print("refresh complete", dt.date.today())
