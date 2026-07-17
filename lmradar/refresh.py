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
    """(date,symbol)-aware over the last 16 days, so newly-listed symbols backfill even on
    dates already fetched for older stocks (the old date-only check skipped them)."""
    syms={x["nse_symbol"].upper() for x in json.load(open("cg_master.json")) if x.get("nse_symbol")}
    cut=(dt.date.today()-dt.timedelta(days=16)).isoformat()
    have=set()
    if os.path.exists("nse_all.csv"):
        for ln in open("nse_all.csv"):
            pp=ln.split(",",2)
            if len(pp)>1 and pp[0]>=cut: have.add((pp[0],pp[1].upper()))
    d=dt.date.today()-dt.timedelta(days=16); add=0
    with open("nse_all.csv","a",newline="") as f:
        w=csv.writer(f)
        while d<=dt.date.today():
            if d.weekday()<5:
                for row in nse_rows(d):
                    sym=(row[1] or "").upper()
                    if sym in syms and (row[0],sym) not in have: w.writerow(row); add+=1
            d+=dt.timedelta(days=1)
    print("price rows added",add)

def bse_topup():
    """BSE bhavcopy for BSE-only listings (no NSE symbol) -> bse_all.csv, matched by ISIN.
    Fixes blank prices for BSE-SME IPOs (Devson/Sampark class) on the LM Radar page."""
    cg=json.load(open("cg_master.json"))
    isins={x["isin"] for x in cg if x.get("isin") and not x.get("nse_symbol")}
    if not isins: return
    have=set()
    if os.path.exists("bse_all.csv"):
        for ln in open("bse_all.csv"):
            pp=ln.split(",",4)
            if len(pp)>3: have.add((pp[0],pp[3]))
    d=dt.date.today()-dt.timedelta(days=30); add=0
    with open("bse_all.csv","a",newline="") as f:
        w=csv.writer(f)
        while d<=dt.date.today():
            if d.weekday()<5:
                try:
                    raw=fetch(f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV")
                    rows=list(csv.DictReader(raw.decode("utf-8","ignore").splitlines()))
                    for r in rows:
                        isin=(r.get("ISIN") or "").strip()
                        if isin in isins and (d.isoformat(),isin) not in have:
                            w.writerow([d.isoformat(),r.get("TckrSymb") or "",r.get("SctySrs") or "BSE",isin,
                                        r.get("OpnPric"),r.get("HghPric"),r.get("LwPric"),r.get("ClsPric"),
                                        r.get("TtlTradgVol"),"",r.get("FinInstrmNm") or ""]); add+=1
                except Exception: pass
            d+=dt.timedelta(days=1)
    print("BSE price rows added",add)

def merge_supa_deals():
    import urllib.request as ur, csv
    SK=os.environ.get("SUPA_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFpZWJhcXZjbHl6eGFqaWd2a2ZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5NTg1MDQsImV4cCI6MjA5MDUzNDUwNH0.m_WLKdaKwEw82RRepHYhXp3tg-g0pwMiDKM2S7Y7XdY"
    try:
        req=ur.Request("https://aiebaqvclyzxajigvkfd.supabase.co/rest/v1/lmr_deals?select=deal_type,deal_date,symbol,security_name,client_name,side,qty,price&limit=500000",
                       headers={"apikey":SK,"Authorization":"Bearer "+SK})
        rows=json.load(ur.urlopen(req,timeout=60))
    except Exception as e:
        print("supabase deals fetch failed:",e); return
    for dtype,path in [("bulk","bulk_deals.csv"),("block","block_deals.csv")]:
        seen=set()
        if os.path.exists(path):
            for r in csv.reader(open(path)):
                if len(r)>=7: seen.add((r[0],r[1],r[3],r[5],r[6]))
        new=[]
        for d in rows:
            if d.get("deal_type")!=dtype: continue
            row=[d.get("deal_date") or "",(d.get("symbol") or ""),(d.get("security_name") or ""),(d.get("client_name") or ""),(d.get("side") or ""),str(d.get("qty") or ""),str(d.get("price") or ""),""]
            k=(row[0],row[1],row[3],row[5],row[6])
            if k in seen: continue
            seen.add(k); new.append(row)
        if new:
            hdr=not os.path.exists(path)
            with open(path,"a",newline="") as f:
                w=csv.writer(f)
                if hdr: w.writerow(["Date","Symbol","Security Name","Client Name","Buy/Sell","Quantity Traded","Trade Price / Wght. Avg. Price","Remarks"])
                w.writerows(new)
            print("merged",len(new),dtype,"deals from Supabase")

def _deals_max():
    import csv, datetime as _dt
    mx=None
    for path in ("bulk_deals.csv","block_deals.csv"):
        if not os.path.exists(path): continue
        for r in csv.reader(open(path)):
            ss=(r[0] or "").strip().strip('"')
            for fmt in ("%d-%b-%Y","%Y-%m-%d","%d-%B-%Y"):
                try:
                    dd=_dt.datetime.strptime(ss[:11],fmt).date()
                    if not mx or dd>mx: mx=dd
                    break
                except: pass
    return mx.isoformat() if mx else None

if __name__=="__main__":
    if os.path.isdir("cg_pairs"): shutil.rmtree("cg_pairs")   # force fresh master (new IPOs)
    loop("cg_master.py",12)
    syms={x["nse_symbol"].upper() for x in json.load(open("cg_master.json")) if x.get("nse_symbol")}
    if not os.path.exists("nse_all.csv"):        # first run: build price history (UNIVERSE only, <100MB)
        loop("bhav_dl.py",60); loop("bse_dl.py",60)
        with open("nse_all.csv","w",newline="") as o:
            w=csv.writer(o)
            for pp in sorted(glob.glob("bhav_parts/*.csv"))+sorted(glob.glob("bse_parts/*.csv")):
                for row in csv.reader(open(pp)):
                    if len(row)>=8 and (row[1] or "").upper() in syms: w.writerow(row)
        open("bse_all.csv","w").close()
    else:
        topup(); open("bse_all.csv","a").close(); bse_topup()
    run(["build_prices.py"])
    loop("pull_anchor.py",12); loop("pull_anchor2.py",20)
    merge_supa_deals()
    run(["advisor_backtest.py"]); run(["build_app.py"])

    # heartbeat -> Supabase (powers the status bar in the app)
    try:
        import urllib.request as ur
        mx=""
        if os.path.exists("nse_all.csv"):
            for ln in open("nse_all.csv"):
                d=ln.split(",",1)[0]
                if d>mx: mx=d
        n=len(json.load(open("cg_master.json")))
        SK=os.environ.get("SUPA_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFpZWJhcXZjbHl6eGFqaWd2a2ZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5NTg1MDQsImV4cCI6MjA5MDUzNDUwNH0.m_WLKdaKwEw82RRepHYhXp3tg-g0pwMiDKM2S7Y7XdY"
        body=[{"component":"lmradar_data","last_run_utc":dt.datetime.utcnow().isoformat()+"Z","data_date":mx or None,"ipo_count":n,"deals_date":_deals_max(),"note":"daily action"}]
        rq=ur.Request("https://aiebaqvclyzxajigvkfd.supabase.co/rest/v1/lmr_status",data=json.dumps(body).encode(),
            headers={"apikey":SK,"Authorization":"Bearer "+SK,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates"},method="POST")
        ur.urlopen(rq,timeout=20); print("heartbeat posted",mx,n)
    except Exception as ex: print("heartbeat failed",ex)
    print("refresh complete", dt.date.today())
