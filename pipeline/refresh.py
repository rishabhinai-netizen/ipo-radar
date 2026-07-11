"""IPO Radar — daily refresh.

1. Pull latest Chittorgarh reports (125 performance, 21 subscription, 156 anchor
   lock-ins) for the current + previous calendar year → detect new IPOs.
2. Scrape lead managers for any new IPO detail pages.
3. Download missing NSE + BSE bhavcopies since the last panel date and append
   rows for tracked ISINs.
4. Rebuild master, analytics and signals.

Designed for GitHub Actions (runs in ~2-5 min). Also runnable locally.
"""
import datetime as dt
import io
import json
import os
import re
import time
import urllib.request
import zipfile

import pandas as pd

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.chittorgarh.com/"}
WINDOW_START = None  # set at runtime: today - 366 days


def _get(url, timeout=30, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def _get_json(url):
    return json.loads(_get(url).decode())


def fetch_report(rep: int, year: int, cat: str, stop_before: str) -> list:
    """Page through a Chittorgarh cloud report; stop when rows get older than stop_before."""
    fy = f"{year}-{str(year + 1)[2:]}"
    key = lambda r: r.get("~id") or r.get("~URLRewrite_Folder_Name")
    datef = lambda r: r.get("~issue_open_date_plan") or (r.get("~IssueCloseDate") or "9999")[:10]
    rows_all, prev_first = {}, None
    for page in range(1, 80):
        url = (f"https://webnodejs.chittorgarh.com/cloud/report/data-read/"
               f"{rep}/{page}/10/{year}/{fy}/0/{cat}?v=16-14")
        try:
            d = _get_json(url)
        except Exception as e:
            print(f"  rep{rep} {year} {cat} p{page}: {e}")
            break
        rows = d.get("reportTableData") or []
        if not rows or key(rows[0]) == prev_first:
            break
        prev_first = key(rows[0])
        for r in rows:
            rows_all[key(r)] = r
        if any(datef(r) < stop_before for r in rows):
            break
        time.sleep(0.3)
    return list(rows_all.values())


def refresh_chittorgarh():
    today = dt.date.today()
    stop = (today - dt.timedelta(days=400)).isoformat()
    years = sorted({today.year, (today - dt.timedelta(days=366)).year})
    store = {}
    for rep in (125, 21, 156):
        rows = []
        for y in years:
            for cat in ("mainboard", "sme"):
                rows += fetch_report(rep, y, cat, stop)
        store[rep] = rows
        print(f"rep{rep}: {len(rows)} rows")
    return store


def scrape_lead_managers(new_ipos: list, lm_map: dict) -> dict:
    for r in new_ipos:
        cid = str(r["chittorgarh_id"])
        if cid in lm_map and lm_map[cid]:
            continue
        url = f"https://www.chittorgarh.com/ipo/{r['slug']}/{cid}/"
        try:
            html = _get(url).decode("utf-8", errors="ignore")
            lms = re.findall(r'ipo-lead-manager-review/\d+/\d+/"[^>]*>([^<]+)</a>', html)
            seen = []
            for l in (x.strip() for x in lms):
                if len(l) > 3 and l not in seen:
                    seen.append(l)
            lm_map[cid] = seen
            print(f"  LM {r['company']}: {seen[:2]}")
            time.sleep(0.5)
        except Exception as e:
            print(f"  LM fail {cid}: {e}")
    return lm_map


def build_master(store: dict) -> list:
    strip = lambda s: re.sub(r"<[^>]+>", "", str(s)).strip()
    num = lambda s: (float(re.sub(r"[^\d.\-]", "", str(s)))
                     if s not in ("", None) and re.search(r"\d", str(s)) else None)
    subs = {r["~id"]: r for r in store[21]}
    anchor = {r["~URLRewrite_Folder_Name"]: r for r in store[156]}
    cutoff = (dt.date.today() - dt.timedelta(days=366)).isoformat()
    out = []
    for r in store[125]:
        ld = (r.get("~IPO_listing_date") or "")[:10]
        if not ld or ld < cutoff:
            continue
        s = subs.get(r["~id"], {})
        a = anchor.get(r["~URLRewrite_Folder_Name"], {})
        clean = lambda v: v if v not in ("",) else None
        out.append({
            "company": strip(r["Company"]), "board": r["Issue Category"],
            "slug": r["~URLRewrite_Folder_Name"], "chittorgarh_id": r["~id"],
            "open_date": r.get("~issue_open_date_plan"), "listing_date": ld,
            "issue_amount_cr": num(r.get("Issue Amount (Rs.cr.)")),
            "issue_price": num(r.get("Issue Price (Rs.)")),
            "subscription_total_x": num(r.get("Subscription (x)")),
            "listing_close": r.get("~ILDT_Close_Price") or None,
            "listing_day_pct": r.get("~Change_In_Percentage_Listing_Day"),
            "cmp": num(re.sub(r"\(.*", "", str(r.get("Market Price (Rs.)") or ""))),
            "isin": r.get("~isin"), "nse_symbol": r.get("~nse_symbol") or "",
            "bse_code": str(r.get("~bse_script_code") or ""),
            "qib_x": clean(s.get("QIB (x)")), "nii_x": clean(s.get("NII (x)")),
            "bnii_x": clean(s.get("bNII (x)")), "retail_x": clean(s.get("Retail (x)")),
            "applications": strip(s.get("Applications") or ""),
            "anchor_amount_cr": num(a.get("Total Investment by Anchor Investors (Rs.cr.)")),
            "anchor_pct_of_issue": num(a.get("% of Issue Amount")),
            "anchor_lockin_30d": (a.get("~AnchorDate1") or "")[:10],
            "anchor_lockin_90d": (a.get("~AnchorDate2") or "")[:10],
        })
    out.sort(key=lambda x: x["listing_date"])
    return out


def refresh_bhavcopy(master: list):
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    isins = {m["isin"] for m in master if m.get("isin")}
    last = pd.Timestamp(panel["date"].max()).date()
    today = dt.date.today()
    new_rows = []
    d = last + dt.timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:
            ds = d.strftime("%Y%m%d")
            # NSE
            try:
                raw = _get(f"https://nsearchives.nseindia.com/content/cm/"
                           f"BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip", retries=1)
                z = zipfile.ZipFile(io.BytesIO(raw))
                txt = z.read(z.namelist()[0]).decode()
                for r in pd.read_csv(io.StringIO(txt)).to_dict("records"):
                    if r["ISIN"] in isins and r["SctySrs"] in ("EQ", "SM", "BE", "ST", "BZ"):
                        new_rows.append(("NSE", r["TradDt"], r["ISIN"], r["TckrSymb"], r["SctySrs"],
                                         r["OpnPric"], r["HghPric"], r["LwPric"], r["ClsPric"],
                                         r["TtlTradgVol"], r["TtlTrfVal"], r["TtlNbOfTxsExctd"]))
            except Exception:
                pass  # holiday / not yet published
            # BSE
            try:
                raw = _get(f"https://www.bseindia.com/download/BhavCopy/Equity/"
                           f"BhavCopy_BSE_CM_0_0_0_{ds}_F_0000.CSV", retries=1).decode(errors="ignore")
                if raw.startswith("TradDt"):
                    for r in pd.read_csv(io.StringIO(raw)).to_dict("records"):
                        if r["ISIN"] in isins:
                            new_rows.append(("BSE", r["TradDt"], r["ISIN"], r["TckrSymb"],
                                             r.get("SctySrs", ""), r["OpnPric"], r["HghPric"],
                                             r["LwPric"], r["ClsPric"], r["TtlTradgVol"],
                                             r["TtlTrfVal"], r["TtlNbOfTxsExctd"]))
            except Exception:
                pass
        d += dt.timedelta(days=1)
    if new_rows:
        add = pd.DataFrame(new_rows, columns=panel.columns[:12])
        for c in ["open", "high", "low", "close", "volume", "turnover", "trades"]:
            add[c] = pd.to_numeric(add[c], errors="coerce")
        add["date"] = pd.to_datetime(add["date"])
        panel = pd.concat([panel, add]).drop_duplicates(["exch", "date", "isin"])
    # trim to 12-month window universe
    panel = panel[panel["isin"].isin(isins)]
    panel.to_parquet(os.path.join(DATA, "prices_panel.parquet"))
    print(f"panel: +{len(new_rows)} rows, now {len(panel)} total, "
          f"last date {panel['date'].max().date()}")


def main():
    store = refresh_chittorgarh()
    master = build_master(store)
    print(f"master: {len(master)} IPOs in 12-month window")
    lm_path = os.path.join(DATA, "lm_map.json")
    lm_map = json.load(open(lm_path)) if os.path.exists(lm_path) else {}
    lm_map = scrape_lead_managers(master, lm_map)
    json.dump(lm_map, open(lm_path, "w"))
    json.dump(master, open(os.path.join(DATA, "master_ipo.json"), "w"), indent=1)
    refresh_bhavcopy(master)
    # rebuild analytics + signals
    import analytics
    analytics.run()
    import signals
    s = signals.compute_signals()
    print(s["state"].value_counts().to_string())


if __name__ == "__main__":
    main()
