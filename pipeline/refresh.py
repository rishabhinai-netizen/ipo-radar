"""IPO Radar — unified refresh engine (daily incremental AND cold-start backfill).

- Chittorgarh cloud reports (125 performance, 21 subscription, 156 anchor lock-ins)
  for every year in the universe window, mainboard + SME, paged, parallel.
- Lead-manager scrape from IPO detail pages (only for IPOs not yet mapped).
- NSE + BSE bhavcopies for every missing trading date since UNIVERSE_START,
  handling BOTH generations of file formats:
    NSE new (UDIFF, ≥ 2024-07-08): BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
    NSE old (< 2024-07-08):        cmDDMONYYYYbhav.csv.zip  (TOTTRDVAL in ₹ lakh)
    BSE new:                        BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV
    BSE old fallback:               EQ_ISINCODE_DDMMYY.zip   (NET_TURNOV in ₹)
  All turnover normalised to ₹ (rupees). Volume in shares.
- Rebuilds analytics, signals and the study artifacts.

Runs in GitHub Actions daily; cold start (~3y) takes ~15 min there.
"""
import datetime as dt
import io
import json
import os
import re
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import config

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.chittorgarh.com/"}
NSE_UDIFF_START = dt.date(2024, 7, 8)
PANEL_COLS = ["exch", "date", "isin", "symbol", "series", "open", "high", "low",
              "close", "volume", "turnover", "trades"]


def _get(url, timeout=30, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


# ------------------------------------------------------------- chittorgarh
def fetch_report(rep, year, cat):
    fy = f"{year}-{str(year + 1)[2:]}"
    key = lambda r: r.get("~id") or r.get("~URLRewrite_Folder_Name")
    datef = lambda r: r.get("~issue_open_date_plan") or (r.get("~IssueCloseDate") or "9999")[:10]
    rows_all, prev_first = {}, None
    for page in range(1, 120):
        url = (f"https://webnodejs.chittorgarh.com/cloud/report/data-read/"
               f"{rep}/{page}/10/{year}/{fy}/0/{cat}?v=16-14")
        try:
            d = json.loads(_get(url).decode())
        except Exception as e:
            print(f"  rep{rep} {year} {cat} p{page}: {e}")
            break
        rows = d.get("reportTableData") or []
        if not rows or key(rows[0]) == prev_first:
            break
        prev_first = key(rows[0])
        for r in rows:
            rows_all[key(r)] = r
        if any(datef(r) < config.CHITT_STOP for r in rows):
            break
        time.sleep(0.15)
    return rep, list(rows_all.values())


def refresh_chittorgarh():
    today = dt.date.today()
    y0 = int(config.UNIVERSE_START[:4])
    jobs = [(rep, y, cat) for rep in (125, 21, 156)
            for y in range(y0, today.year + 1) for cat in ("mainboard", "sme")]
    store = {125: [], 21: [], 156: []}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_report, *j) for j in jobs]
        for f in as_completed(futs):
            rep, rows = f.result()
            store[rep] += rows
    # dedupe (same IPO can appear in two years' reports)
    for rep in store:
        k = lambda r: r.get("~id") or r.get("~URLRewrite_Folder_Name")
        store[rep] = list({k(r): r for r in store[rep]}.values())
        print(f"rep{rep}: {len(store[rep])} rows")
    return store


def build_master(store):
    strip = lambda s: re.sub(r"<[^>]+>", "", str(s)).strip()
    num = lambda s: (float(re.sub(r"[^\d.\-]", "", str(s)))
                     if s not in ("", None) and re.search(r"\d", str(s)) else None)
    subs = {r["~id"]: r for r in store[21]}
    anchor = {r["~URLRewrite_Folder_Name"]: r for r in store[156]}
    out = []
    for r in store[125]:
        ld = (r.get("~IPO_listing_date") or "")[:10]
        if not ld or ld < config.UNIVERSE_START:
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


# ------------------------------------------------------------- lead managers
def _scrape_lm(r):
    cid = str(r["chittorgarh_id"])
    url = f"https://www.chittorgarh.com/ipo/{r['slug']}/{cid}/"
    try:
        html = _get(url, retries=2).decode("utf-8", errors="ignore")
        lms = re.findall(r'ipo-lead-manager-review/\d+/\d+/"[^>]*>([^<]+)</a>', html)
        seen = []
        for l in (x.strip() for x in lms):
            if len(l) > 3 and l not in seen:
                seen.append(l)
        return cid, seen
    except Exception as e:
        return cid, None


def scrape_lead_managers(master, lm_map):
    todo = [r for r in master if not lm_map.get(str(r["chittorgarh_id"]))]
    print(f"LM scrape: {len(todo)} pending")
    with ThreadPoolExecutor(max_workers=4) as ex:
        for cid, lms in ex.map(_scrape_lm, todo):
            if lms is not None:
                lm_map[cid] = lms
    return lm_map


# ------------------------------------------------------------- bhavcopies
def _parse_nse_new(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    df = df[df["SctySrs"].isin(["EQ", "SM", "BE", "ST", "BZ"])]
    return pd.DataFrame({
        "exch": "NSE", "date": df["TradDt"], "isin": df["ISIN"], "symbol": df["TckrSymb"],
        "series": df["SctySrs"], "open": df["OpnPric"], "high": df["HghPric"],
        "low": df["LwPric"], "close": df["ClsPric"], "volume": df["TtlTradgVol"],
        "turnover": df["TtlTrfVal"], "trades": df["TtlNbOfTxsExctd"]})


def _parse_nse_old(raw, date):
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    df = df[df["SERIES"].isin(["EQ", "SM", "BE", "ST", "BZ"])]
    return pd.DataFrame({
        "exch": "NSE", "date": date.isoformat(), "isin": df["ISIN"], "symbol": df["SYMBOL"],
        "series": df["SERIES"], "open": df["OPEN"], "high": df["HIGH"], "low": df["LOW"],
        "close": df["CLOSE"], "volume": df["TOTTRDQTY"],
        "turnover": df["TOTTRDVAL"] * 1e5,  # ₹ lakh → ₹
        "trades": df["TOTALTRADES"]})


def _parse_bse_new(raw):
    df = pd.read_csv(io.BytesIO(raw))
    return pd.DataFrame({
        "exch": "BSE", "date": df["TradDt"], "isin": df["ISIN"], "symbol": df["TckrSymb"],
        "series": df.get("SctySrs", ""), "open": df["OpnPric"], "high": df["HghPric"],
        "low": df["LwPric"], "close": df["ClsPric"], "volume": df["TtlTradgVol"],
        "turnover": df["TtlTrfVal"], "trades": df["TtlNbOfTxsExctd"]})


def _parse_bse_old(raw, date):
    z = zipfile.ZipFile(io.BytesIO(raw))
    df = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    icol = "ISIN_CODE" if "ISIN_CODE" in df.columns else "ISIN"
    return pd.DataFrame({
        "exch": "BSE", "date": date.isoformat(), "isin": df[icol], "symbol": df["SC_CODE"].astype(str),
        "series": df.get("SC_GROUP", ""), "open": df["OPEN"], "high": df["HIGH"],
        "low": df["LOW"], "close": df["CLOSE"], "volume": df["NO_OF_SHRS"],
        "turnover": df["NET_TURNOV"], "trades": df["NO_TRADES"]})


def fetch_day(date):
    """Return list of normalised dataframes for one trading date (NSE + BSE)."""
    frames = []
    ds = date.strftime("%Y%m%d")
    # NSE
    try:
        if date >= NSE_UDIFF_START:
            raw = _get(f"https://nsearchives.nseindia.com/content/cm/"
                       f"BhavCopy_NSE_CM_0_0_0_{ds}_F_0000.csv.zip", retries=1)
            frames.append(_parse_nse_new(raw))
        else:
            mon = date.strftime("%b").upper()
            raw = _get(f"https://nsearchives.nseindia.com/content/historical/EQUITIES/"
                       f"{date.year}/{mon}/cm{date.strftime('%d')}{mon}{date.year}bhav.csv.zip",
                       retries=1)
            frames.append(_parse_nse_old(raw, date))
    except Exception:
        pass  # holiday / missing
    # BSE — try new, fall back to old
    try:
        raw = _get(f"https://www.bseindia.com/download/BhavCopy/Equity/"
                   f"BhavCopy_BSE_CM_0_0_0_{ds}_F_0000.CSV", retries=1)
        if raw[:6] == b"TradDt":
            frames.append(_parse_bse_new(raw))
        else:
            raise ValueError("not new format")
    except Exception:
        try:
            raw = _get(f"https://www.bseindia.com/download/BhavCopy/Equity/"
                       f"EQ_ISINCODE_{date.strftime('%d%m%y')}.zip", retries=1)
            frames.append(_parse_bse_old(raw, date))
        except Exception:
            pass
    return frames


def refresh_bhavcopy(master):
    path = os.path.join(DATA, "prices_panel.parquet")
    isins = {m["isin"] for m in master if m.get("isin")}
    if os.path.exists(path):
        panel = pd.read_parquet(path)
        have = set(pd.to_datetime(panel["date"]).dt.date.unique())
    else:
        panel = pd.DataFrame(columns=PANEL_COLS)
        have = set()
    today = dt.date.today()
    start = dt.date.fromisoformat(config.UNIVERSE_START)
    want = [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]
    missing = [d for d in want if d.weekday() < 5 and d not in have]
    print(f"bhavcopy: {len(missing)} missing dates")
    new_frames = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for frames in ex.map(fetch_day, missing):
            new_frames += frames
    if new_frames:
        add = pd.concat(new_frames, ignore_index=True)
        add = add[add["isin"].isin(isins)]
        for c in ["open", "high", "low", "close", "volume", "turnover", "trades"]:
            add[c] = pd.to_numeric(add[c], errors="coerce")
        add["date"] = pd.to_datetime(add["date"])
        panel = pd.concat([panel, add], ignore_index=True)
        panel["date"] = pd.to_datetime(panel["date"])
        panel = panel.drop_duplicates(["exch", "date", "isin"])
    panel = panel[panel["isin"].isin(isins)].sort_values("date")
    panel.to_parquet(path)
    print(f"panel: {len(panel)} rows, {panel['isin'].nunique()} isins, "
          f"{panel['date'].min().date()} → {panel['date'].max().date()}")
    # QC: turnover continuity across format boundary (should be same magnitude)
    p = panel.copy()
    p["ym"] = p["date"].dt.to_period("M")
    med = p[p["exch"] == "NSE"].groupby("ym")["turnover"].median()
    if len(med) > 14:
        jun24, aug24 = med.get(pd.Period("2024-06")), med.get(pd.Period("2024-08"))
        if jun24 and aug24 and not (0.05 < jun24 / aug24 < 20):
            print(f"⚠ QC WARNING: NSE turnover discontinuity across UDIFF boundary "
                  f"({jun24:.0f} vs {aug24:.0f})")


def main():
    store = refresh_chittorgarh()
    master = build_master(store)
    print(f"master: {len(master)} IPOs since {config.UNIVERSE_START}")
    lm_path = os.path.join(DATA, "lm_map.json")
    lm_map = json.load(open(lm_path)) if os.path.exists(lm_path) else {}
    lm_map = scrape_lead_managers(master, lm_map)
    json.dump(lm_map, open(lm_path, "w"))
    json.dump(master, open(os.path.join(DATA, "master_ipo.json"), "w"), indent=1)
    refresh_bhavcopy(master)
    import analytics
    analytics.run()
    import study
    study.run()
    try:
        import freefloat
        freefloat.run()          # uses previous signals.csv for priority
    except Exception as e:
        print("freefloat skipped:", e)
    import signals
    s = signals.compute_signals()
    print(s["reco"].value_counts().to_string())


if __name__ == "__main__":
    main()
