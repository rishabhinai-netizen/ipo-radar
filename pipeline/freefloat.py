"""IPO Radar — free-float via Screener.in.

For each tracked stock: market cap + current price → shares outstanding;
promoter holding % → free float = shares × (1 − promoter%).
Enables the 'daily volume as % of free float' metric.

Polite scraping: cached in data/freefloat.json, entries refreshed only when
older than 7 days, max N fetches per run, 0.7 s spacing. Prioritises
actionable + recently listed names so the watchlist fills first.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_FETCH = int(os.environ.get("FF_MAX_FETCH", "250"))


def _get(url):
    req = urllib.request.Request(url, headers=HDRS)
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")


def _parse(html):
    """Extract market cap (₹ cr), current price and promoter holding (%)."""
    txt = re.sub(r"\s+", " ", html)
    mcap = price = prom = None
    m = re.search(r"Market Cap.{0,150}?number\">([\d,\.]+)</span>", txt)
    if m:
        mcap = float(m.group(1).replace(",", ""))
    m = re.search(r"Current Price.{0,150}?number\">([\d,\.]+)</span>", txt)
    if m:
        price = float(m.group(1).replace(",", ""))
    m = re.search(r"Promoters&nbsp;.{0,400}?</tr>", txt)
    if m:
        cells = re.findall(r"<td>([\d.]+)%</td>", m.group(0))
        if cells:
            prom = float(cells[-1])
    return mcap, price, prom


def run():
    sig = pd.read_csv(os.path.join(DATA, "signals.csv"))
    path = os.path.join(DATA, "freefloat.json")
    cache = json.load(open(path)) if os.path.exists(path) else {}
    today = dt.date.today().isoformat()
    stale = (dt.date.today() - dt.timedelta(days=7)).isoformat()

    # priority: actionable first, then youngest listings
    order = {"FRESH BUY": 0, "BUY-SETUP": 0, "RIDE": 1, "WATCH": 2, "EXIT": 3, "AVOID": 4}
    sig["prio"] = sig["reco"].map(order).fillna(5)
    sig = sig.sort_values(["prio", "listing_date"], ascending=[True, False])

    done = 0
    for _, r in sig.iterrows():
        if done >= MAX_FETCH:
            break
        isin = str(r["isin"])
        c = cache.get(isin)
        if c and c.get("fetched", "") > stale:
            continue
        url = r.get("screener_url")
        if not isinstance(url, str) or not url:
            continue
        try:
            mcap, price, prom = _parse(_get(url))
            if mcap and price:
                shares = mcap * 1e7 / price
                entry = {"mcap_cr": mcap, "price": price, "promoter_pct": prom,
                         "shares_out": round(shares),
                         "float_shares": round(shares * (1 - (prom or 0) / 100)),
                         "fetched": today}
                cache[isin] = entry
            else:
                cache[isin] = {"fetched": today, "error": "parse"}
            done += 1
            time.sleep(0.5)
        except Exception as e:
            cache[isin] = {"fetched": today, "error": str(e)[:60]}
            done += 1
            time.sleep(0.8)
        if done % 10 == 0:
            json.dump(cache, open(path, "w"))
    json.dump(cache, open(path, "w"))
    ok = sum(1 for v in cache.values() if v.get("float_shares"))
    print(f"freefloat: fetched {done}, cache {len(cache)} ({ok} with float)")


if __name__ == "__main__":
    run()
