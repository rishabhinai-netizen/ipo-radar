#!/usr/bin/env python3
"""Pull anchor-investor data from Chittorgarh. Resumable, time-bounded (~40s/run).
Phase 1: paginate report 133 (anchor fund league) sme+mainboard -> anchor_funds.json
Phase 2: for LM-brand-matched + top-N active funds, pull report 134 (fund's IPO picks) -> anchor_events.json
Re-run until it prints ALL_DONE."""
import json, re, time, os, urllib.request
BASE="https://webnodejs.chittorgarh.com/cloud/report/data-read"
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Accept":"application/json","Referer":"https://www.chittorgarh.com/"}
MAXS=40; t0=time.time()
def strip(x): return re.sub("<[^>]+>","",str(x or "")).strip()
def num(s):
    m=re.search(r"-?\d[\d,]*\.?\d*", str(s or "").replace(",",""))
    try: return float(m.group()) if m else None
    except: return None
def pctval(s):  # "116.55 (20.15%)" -> (116.55, 20.15)
    s=str(s or ""); a=re.search(r"^-?\d[\d,]*\.?\d*", s.replace(",","")); b=re.search(r"\(([-\d.]+)%\)", s)
    return (float(a.group()) if a else None, float(b.group(1)) if b else None)
def get(url,tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:
                return json.loads(r.read().decode("utf-8","ignore"))
        except Exception: time.sleep(0.4*(i+1))
    return None

# ---- LM brand tokens from master ----
master=json.load(open("cg_master.json"))
def core(n):
    n=(n or "").lower()
    for w in ["private","limited","ltd.","ltd","pvt.","pvt","advisors","advisory","advisers","capital",
              "securities","services","financial","finance","(india)","india","corporate","markets","&","and"]:
        n=n.replace(w," ")
    return re.sub(r"\s+"," ",n).strip()
lm_tokens={}
for m in master:
    lm=m.get("lead_manager")
    if not lm: continue
    c=core(lm)
    tok=c.split()[0] if c else ""
    if len(tok)>=4: lm_tokens.setdefault(tok, lm)

def phase1():
    funds={}
    if os.path.exists("anchor_funds.json"): funds={f["id"]:f for f in json.load(open("anchor_funds.json"))}
    for seg,cat in [("SME","sme"),("Mainboard","mainboard")]:
        page = 1 + max([f.get("_pg",0) for f in funds.values() if f["segment"]==seg]+[0])
        empty=0
        while page<=400:
            if time.time()-t0>MAXS:
                json.dump(list(funds.values()),open('anchor_funds.json','w')); return False
            d=get(f"{BASE}/133/{page}/1/2025/2026-27/0/{cat}/0?search=&v=1-1")
            if d is None: break
            rows=d.get("reportTableData",[])
            if not rows: break
            new=0
            for r in rows:
                fid=str(r.get("~id"))
                if fid in funds: continue
                funds[fid]={"id":fid,"name":strip(r.get("Anchor Investor")),"segment":seg,"_pg":page,
                    "n_issues":num(r.get("No. of Issues")),
                    "avg_listing_gain":num(r.get("Average Listing gain (%)")),
                    "avg_current_gain":num(r.get("Average Current gains / Loss (%)")),
                    "total_inv_cr":num(r.get("Total investment (Rs.cr.)"))}
                new+=1
            empty=empty+1 if new==0 else 0
            if empty>=3: break
            page+=1; time.sleep(0.03)
    json.dump(list(funds.values()),open("anchor_funds.json","w"))
    return True

def select_funds(funds):
    sel={}
    for f in funds:
        nm=f["name"].lower()
        matched=None
        for tok,lm in lm_tokens.items():
            if tok in nm.split() or (len(tok)>=5 and tok in nm): matched=lm; break
        f["brand_lm"]=matched
        if matched: sel[f["id"]]=f
    # also top active SME funds (to catch non-brand affiliations empirically + fund drilldowns)
    for f in sorted([x for x in funds if x["segment"]=="SME"], key=lambda x:-(x["n_issues"] or 0))[:80]:
        sel[f["id"]]=f
    return list(sel.values())

def phase2():
    funds=json.load(open("anchor_funds.json"))
    sel=select_funds(funds)
    events=[]
    if os.path.exists("anchor_events.json"): events=json.load(open("anchor_events.json"))
    done={e["fund_id"] for e in events}
    for f in sel:
        if f["id"] in done: continue
        if time.time()-t0>MAXS: json.dump(events,open("anchor_events.json","w")); return False
        d=get(f"{BASE}/134/1/1/2025/2026-27/0/all/{f['id']}?search=&v=1-1")
        done.add(f["id"])
        if d is None: continue
        for r in d.get("reportTableData",[]):
            lc,lcp=pctval(r.get("Close Price on Listing (Rs.)")); mp,mpp=pctval(r.get("Market Price (Rs.)"))
            events.append({"fund_id":f["id"],"fund":f["name"],"brand_lm":f.get("brand_lm"),
                "company":strip(r.get("Company")),"segment":strip(r.get("Issue Category")),
                "nse_symbol":strip(r.get("~nse_symbol")),"isin":strip(r.get("~isin")),
                "listing_date":strip(r.get("Listing Date")),"issue_price":num(r.get("Issue Price (Rs.)")),
                "shares":num(r.get("Shares Alloted")),"amount_cr":num(r.get("Amount Invested (Rs.cr.)")),
                "listing_close":lc,"listing_gain_pct":lcp,"market_price":mp,"market_gain_pct":mpp,
                "lead_manager":strip(r.get("Lead Manager"))})
        time.sleep(0.03)
    json.dump(events,open("anchor_events.json","w"))
    return True

if not phase1():
    print(f"phase1 in progress: funds={len(json.load(open('anchor_funds.json')))} -> MORE"); raise SystemExit
funds=json.load(open("anchor_funds.json"))
sme=sum(1 for f in funds if f["segment"]=="SME")
print(f"phase1 done: {len(funds)} funds (SME {sme})")
if not phase2():
    print(f"phase2 in progress: events={len(json.load(open('anchor_events.json')))} -> MORE"); raise SystemExit
ev=json.load(open("anchor_events.json"))
print(f"phase2 done: {len(ev)} anchor events")
print("ALL_DONE")
