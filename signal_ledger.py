#!/usr/bin/env python3
"""Live forward-test ledger for the IPO Radar 'app' signals.
Logs score>75 BUY triggers from data/signals.csv to Supabase lmr_signal_ledger, then tracks
each to target / -8% stop / 120-session timeout using real prices (nse_all.csv). Idempotent."""
import os, csv, json, datetime as dt, urllib.request, urllib.parse
SUPA="https://aiebaqvclyzxajigvkfd.supabase.co"
SK=os.environ.get("SUPA_KEY") or ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFpZWJhcXZjbHl6eGFqaWd2a2ZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5NTg1MDQsImV4cCI6MjA5MDUzNDUwNH0.m_WLKdaKwEw82RRepHYhXp3tg-g0pwMiDKM2S7Y7XdY")
PRICE_FILE=os.environ.get("PRICE_FILE","lmradar/nse_all.csv")
SIGNALS=os.environ.get("SIGNALS","data/signals.csv")
APP_DATA=os.environ.get("APP_DATA","lmradar/app_data.json")
def hdr(x=None):
    h={"apikey":SK,"Authorization":"Bearer "+SK,"Content-Type":"application/json"}
    if x: h.update(x)
    return h
def sget(path):
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{SUPA}/rest/v1/{path}",headers=hdr()),timeout=30) as f: return json.load(f)
    except Exception as e: print("get err",e); return []
def sinsert(rows):
    if not rows: return
    r=urllib.request.Request(f"{SUPA}/rest/v1/lmr_signal_ledger",data=json.dumps(rows).encode(),
        headers=hdr({"Prefer":"resolution=ignore-duplicates"}),method="POST")
    try:
        urllib.request.urlopen(r,timeout=40); print("inserted",len(rows),"new signals")
    except urllib.error.HTTPError as e: print("insert err",e.code,e.read()[:120])
def spatch(sym,sdate,body):
    q=urllib.parse.urlencode({"symbol":f"eq.{sym}","signal_date":f"eq.{sdate}"})
    r=urllib.request.Request(f"{SUPA}/rest/v1/lmr_signal_ledger?{q}",data=json.dumps(body).encode(),
        headers=hdr({"Prefer":"return=minimal"}),method="PATCH")
    try: urllib.request.urlopen(r,timeout=30)
    except Exception as e: print("patch err",sym,e)
def num(x):
    try: return float(str(x).replace(",",""))
    except: return None
# price series
series={}
if os.path.exists(PRICE_FILE):
    for r in csv.reader(open(PRICE_FILE)):
        if len(r)<8: continue
        try: series.setdefault(r[1].upper(),[]).append((r[0],float(r[5]),float(r[6]),float(r[7])))
        except: pass
    for k in series: series[k].sort()
today=dt.date.today().isoformat()
# 1) log new triggers
cands=[r for r in csv.DictReader(open(SIGNALS)) if r.get("score") and num(r["score"])>=65 and (r.get("reco") or "").strip()=="FRESH BUY"]
open_syms={r["symbol"].upper() for r in sget("lmr_signal_ledger?status=eq.open&select=symbol")}
new=[]
for r in cands:
    sym=(r.get("symbol") or "").upper()
    if not sym or sym in open_syms: continue
    new.append({"symbol":sym,"company":r.get("company"),"board":r.get("board"),"lead_manager":r.get("lead_manager"),
        "signal_date":today,"entry":num(r.get("entry")),"stop":num(r.get("stop")),"target":num(r.get("target")),
        "score":num(r.get("score")),"status":"open","entry_close":num(r.get("cmp")) or num(r.get("entry"))})
sinsert(new)
# 2) update all open rows
for row in sget("lmr_signal_ledger?status=eq.open&select=symbol,signal_date,entry,stop,target,entry_close"):
    sym=row["symbol"].upper(); entry=row.get("entry") or row.get("entry_close"); 
    if not entry: continue
    s=series.get(sym,[]); bars=[b for b in s if b[0]>=row["signal_date"]]
    ec=row.get("entry_close") or entry
    if not bars:
        # day-0: no price bar after signal yet -> mark at signal-time close
        pnl0=round((ec/entry-1)*100,1)
        spatch(sym,row["signal_date"],{"status":"open","current_price":round(ec,2),"peak_pct":pnl0,
            "pnl_pct":pnl0,"days_held":0,"updated_at":dt.datetime.utcnow().isoformat()+"Z"})
        continue
    peak=max(b[1] for b in bars); latest=bars[-1][3]; days=len(bars)
    tg=row.get("target"); sp=row.get("stop"); ex=None
    for b in bars:
        if tg and b[1]>=tg: ex=(b[0],"target",tg); break
        if sp and b[2]<=sp: ex=(b[0],"stop",sp); break
    if not ex and days>=120: ex=(bars[-1][0],"timeout",latest)
    status=ex[1] if ex else "open"; exit_price=ex[2] if ex else latest
    pnl=round((exit_price/entry-1)*100,1)
    spatch(sym,row["signal_date"],{"status":status,"current_price":round(latest,2),"peak_pct":round((peak/entry-1)*100,1),
        "pnl_pct":pnl,"days_held":days,"exit_date":(ex[0] if ex else None),"exit_reason":(ex[1] if ex else None),
        "updated_at":dt.datetime.utcnow().isoformat()+"Z"})

# 3) alerts: recently-listed IPOs the banker self-anchored + recent own-LM bulk buys
try:
    ad=json.load(open(APP_DATA)); cut=(dt.date.today()-dt.timedelta(days=90)).isoformat()
    al=[]
    _ld={ (r.get("nse_symbol") or "").upper(): r.get("listing_date") for r in ad.get("rows",[]) if r.get("nse_symbol") }
    for r in ad.get("rows",[]):
        if r.get("self_anchor") and (r.get("listing_date") or "")>=cut:
            sa=r["self_anchor"]
            al.append({"kind":"anchor","symbol":r.get("nse_symbol") or r.get("company"),"company":r.get("company"),
                "lead_manager":r.get("lead_manager"),"listing_date":r.get("listing_date"),
                "alert_date":r.get("listing_date"),   # dated by the event, not the run day -> no daily repeats
                "detail":f"{sa.get('fund')} anchored {int(sa.get('shares') or 0)} sh @Rs{sa.get('issue_price')}; now {sa.get('market_gain_pct')}% vs issue"})
    for sg in ad.get("today_signals_strict",[])[:40]:
        if (sg.get("date") or "")>=cut:
            al.append({"kind":"bulk_buy","symbol":sg.get("symbol"),"company":sg.get("company"),
                "lead_manager":sg.get("lead_manager"),"listing_date":_ld.get((sg.get("symbol") or "").upper()),
                "alert_date":sg.get("date"),          # dated by the deal date -> repeats impossible
                "detail":f"own LM {sg.get('client')} bought {sg.get('qty')} @Rs{sg.get('price')} on {sg.get('date')}"})
    if al:
        r=urllib.request.Request(f"{SUPA}/rest/v1/lmr_alerts",data=json.dumps(al).encode(),
            headers=hdr({"Prefer":"resolution=ignore-duplicates"}),method="POST")
        try: urllib.request.urlopen(r,timeout=30); print("alerts upserted",len(al))
        except urllib.error.HTTPError as e: print("alerts err",e.code)
except Exception as e: print("alerts skip",e)
print("ledger update done. candidates:",len(cands),"new:",len(new))
