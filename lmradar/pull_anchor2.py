#!/usr/bin/env python3
"""Phase 2: LM-brand-matched funds -> chain 133-id -> 190 (schemes) -> 134 (per-IPO anchor events).
Resumable, time-bounded. Re-run until ALL_DONE."""
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
def pctval(s):
    s=str(s or ""); a=re.search(r"^-?\d[\d,]*\.?\d*", s.replace(",","")); b=re.search(r"\(([-\d.]+)%\)", s)
    return (float(a.group()) if a else None, float(b.group(1)) if b else None)
def get(url,tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:
                return json.loads(r.read().decode("utf-8","ignore"))
        except Exception: time.sleep(0.4*(i+1))
    return None
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
    tok=(core(lm).split() or [""])[0]
    if len(tok)>=4: lm_tokens.setdefault(tok, lm)
funds=json.load(open("anchor_funds.json"))
def brand(nm):
    nm=nm.lower()
    for tok,lm in lm_tokens.items():
        if tok in nm.split() or (len(tok)>=5 and tok in nm): return lm
    return None
sel={}
for f in funds:
    b=brand(f["name"])
    if b: f["brand_lm"]=b; sel[f["id"]]=f
for f in sorted([x for x in funds if x["segment"]=="SME"],key=lambda x:-(x["n_issues"] or 0))[:25]:
    sel.setdefault(f["id"],f); f["brand_lm"]=f.get("brand_lm") or brand(f["name"])
sel=list(sel.values())
try: events=json.load(open("anchor_events.json"))
except Exception: events=[]
events=[e for e in events if "group_id" in e]
done={e["group_id"] for e in events}
for f in sel:
    if f["id"] in done: continue
    if time.time()-t0>MAXS: break
    seg="sme" if f["segment"]=="SME" else "mainboard"
    d190=get(f"{BASE}/190/1/1/2025/2026-27/0/{seg}/{f['id']}?search=&v=1-1")
    done.add(f["id"])
    if d190 is None: continue
    for sch in d190.get("reportTableData",[]):
        sid=str(sch.get("~id")); sname=strip(sch.get("Anchor Investor"))
        d134=get(f"{BASE}/134/1/1/2025/2026-27/0/all/{sid}?search=&v=1-1")
        if d134 is None: continue
        for r in d134.get("reportTableData",[]):
            lc,lcp=pctval(r.get("Close Price on Listing (Rs.)")); mp,mpp=pctval(r.get("Market Price (Rs.)"))
            events.append({"group_id":f["id"],"group":f["name"],"scheme":sname,"brand_lm":f.get("brand_lm"),
                "company":strip(r.get("Company")),"segment":strip(r.get("Issue Category")),
                "nse_symbol":strip(r.get("~nse_symbol")),"isin":strip(r.get("~isin")),
                "listing_date":strip(r.get("Listing Date")),"issue_price":num(r.get("Issue Price (Rs.)")),
                "shares":num(r.get("Shares Alloted")),"amount_cr":num(r.get("Amount Invested (Rs.cr.)")),
                "listing_close":lc,"listing_gain_pct":lcp,"market_price":mp,"market_gain_pct":mpp,
                "lead_manager":strip(r.get("Lead Manager"))})
        time.sleep(0.03)
json.dump(events,open("anchor_events.json","w"))
rem=[f for f in sel if f["id"] not in done]
print(f"selected={len(sel)} processed={len(done)} events={len(events)} remaining={len(rem)}")
print("ALL_DONE" if not rem else "MORE")
