"""IPO Radar — surveillance risk engine.

Three layers, refreshed daily:
1. OFFICIAL flags — live NSE ASM (long/short), ESM and GSM lists (with stage).
2. PREDICTED risk — rule-based approximations of the entry criteria, so the user
   sees the landmine BEFORE the exchange steps in:
     · ESM candidate: mainboard, mcap < ₹500cr (ESM applies only to that pool);
       elevated when 3-month price change ≥ +75%
     · ST-ASM trigger risk: +25% or more in 5 sessions (both boards)
     · SME LT-ASM risk: close-to-close 3-month move ≥ ±90% (index-beta term
       approximated away; flagged as indicative)
     · high-low variation ≥75% in one month (secondary ST-ASM criterion)
3. BAND-LOCK detector + event study — detects stocks trading pinned to a daily
   price band (repeated ~2% or ~5% limit moves with drying volume, the exact
   Amanta Healthcare situation) and measures, across the full 3-year panel,
   what historically happened after a stock got band-locked.

Notes: criteria are exchange-published but reviewed periodically; treat
predicted flags as indicative, official flags as fact.
"""
import datetime as dt
import json
import os
import urllib.request

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"}


def _get_json(url):
    req = urllib.request.Request(url, headers=HDRS)
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())


def fetch_official():
    flags, raw = {}, {}
    try:
        d = _get_json("https://www.nseindia.com/api/reportASM?json=true")
        for r in (d.get("longterm", {}).get("data") or []):
            flags.setdefault(r["isin"], []).append(f"ASM Long-Term {r.get('asmSurvIndicator','')}".strip())
            raw.setdefault(r["isin"], []).append(f"NSE ASM Long-Term list, {r.get('asmTime','')}")
        for r in (d.get("shortterm", {}).get("data") or []):
            flags.setdefault(r["isin"], []).append(f"ASM Short-Term {r.get('asmSurvIndicator','')}".strip())
            raw.setdefault(r["isin"], []).append(f"NSE ASM Short-Term list, {r.get('asmTime','')}")
    except Exception as e:
        print("ASM fetch fail:", e)
    try:
        for r in _get_json("https://www.nseindia.com/api/reportESM?json=true"):
            flags.setdefault(r["isin"], []).append(f"ESM {r.get('esmSurvIndicator','')}".strip())
            raw.setdefault(r["isin"], []).append(f"{r.get('survDesc','')} (NSE list {r.get('esmTime','')})")
    except Exception as e:
        print("ESM fetch fail:", e)
    try:
        for r in _get_json("https://www.nseindia.com/api/reportGSM?json=true"):
            flags.setdefault(r["isin"], []).append(f"GSM {r.get('gsmStage','')}".strip())
            raw.setdefault(r["isin"], []).append(f"{r.get('survDesc','')} (NSE GSM list {r.get('gsmTime','')})")
    except Exception as e:
        print("GSM fetch fail:", e)
    return ({k: "; ".join(sorted(set(v))) for k, v in flags.items()},
            {k: " | ".join(sorted(set(v))) for k, v in raw.items()})


def _series(panel):
    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    return panel.merge(pref, on=["isin", "exch"]).sort_values("date")


def band_lock_state(p):
    """Return '2%' / '5%' if the last 8 sessions look band-pinned, else None."""
    if len(p) < 10:
        return None
    ret = p["close"].pct_change().abs().tail(8) * 100
    n2 = ((ret >= 1.7) & (ret <= 2.05)).sum()
    n5 = ((ret >= 4.4) & (ret <= 5.05)).sum()
    if n2 >= 5:
        return "2%"
    if n5 >= 5:
        return "5%"
    return None


def risk_rules(p, board, mcap_cr):
    risks = []
    c = p["close"]
    if len(c) >= 6:
        r5 = (c.iloc[-1] / c.iloc[-6] - 1) * 100
        if r5 >= 25:
            risks.append(f"ST-ASM trigger risk: +{r5:.0f}% in 5 sessions (criterion: ≥25%)")
    if len(c) >= 64:
        r3m = (c.iloc[-1] / c.iloc[-64] - 1) * 100
        if board == "SME" and abs(r3m) >= 90:
            risks.append(f"SME LT-ASM risk: {r3m:+.0f}% in 3 months (criterion: ≥±90%, indicative)")
        if board == "Mainboard" and mcap_cr and mcap_cr < 500 and r3m >= 75:
            risks.append(f"ESM risk: mcap ₹{mcap_cr:.0f}cr (<500cr pool) and +{r3m:.0f}% in 3 months")
        elif board == "Mainboard" and mcap_cr and mcap_cr < 500:
            risks.append(f"In ESM-eligible pool (mcap ₹{mcap_cr:.0f}cr < ₹500cr) — sharp rallies can trigger 100% margin + 2%/5% band")
    if len(c) >= 22:
        hi, lo = p["high"].tail(21).max(), p["low"].tail(21).min()
        if lo > 0 and (hi / lo - 1) * 100 >= 75:
            risks.append(f"1-month high-low variation {((hi/lo-1)*100):.0f}% (ST-ASM secondary criterion ≥75%)")
    return risks


def event_study(series_by_isin):
    """What happened historically AFTER a stock became band-locked?"""
    rows = []
    for isin, p in series_by_isin.items():
        if len(p) < 40:
            continue
        ret = p["close"].pct_change().abs() * 100
        lock2 = ((ret >= 1.7) & (ret <= 2.05)).rolling(8).sum() >= 5
        lock5 = ((ret >= 4.4) & (ret <= 5.05)).rolling(8).sum() >= 5
        locked = (lock2 | lock5)
        starts = locked & ~locked.shift(1, fill_value=False)
        for i in np.where(starts.values)[0]:
            if i < 10:
                continue
            e = {"isin": isin, "day": i}
            for h in (20, 60):
                if i + h < len(p):
                    e[f"fwd{h}"] = (p["close"].iloc[i + h] / p["close"].iloc[i] - 1) * 100
            vol_pre = p["volume"].iloc[max(0, i - 20):i].mean()
            vol_post = p["volume"].iloc[i:i + 20].mean()
            e["vol_change_pct"] = (vol_post / vol_pre - 1) * 100 if vol_pre else None
            rows.append(e)
    ev = pd.DataFrame(rows)
    stats = {}
    if len(ev):
        stats = {"n_episodes": int(len(ev)),
                 "n_stocks": int(ev["isin"].nunique()),
                 "fwd20_median": round(float(ev["fwd20"].dropna().median()), 1) if "fwd20" in ev else None,
                 "fwd20_win": round(float((ev["fwd20"].dropna() > 0).mean() * 100)) if "fwd20" in ev else None,
                 "fwd60_median": round(float(ev["fwd60"].dropna().median()), 1) if "fwd60" in ev else None,
                 "fwd60_win": round(float((ev["fwd60"].dropna() > 0).mean() * 100)) if "fwd60" in ev else None,
                 "vol_change_median_pct": round(float(ev["vol_change_pct"].dropna().median()), 1)}
    return ev, stats


STAGE_INFO = {
    # framework key-substring -> (implication, review cycle, min stay days, exit rule)
    "ESM Stage I": ("Trade-to-trade settlement, 100% margin, 5% daily band (2% if already there). No intraday.",
                    "Weekly stage review; exit reviewed after min 90 calendar days",
                    90, "Exit when price/volatility criteria normalise on review, or mcap sustainably exceeds the ₹500cr micro-cap pool"),
    "ESM Stage II": ("Trade-to-trade, 100% margin, 2% daily band — the tightest cage (Amanta situation). Liquidity typically dries hard.",
                     "Weekly review; Stage II→I possible after ~1 month of cooling",
                     30, "First step down to Stage I after ~1 month without triggers; full exit needs 90+ days and criteria normalisation"),
    "ASM Long-Term Stage I": ("100% margin on all positions. Trading otherwise normal.",
                              "Quarterly (stage-wise) review; min ~90 days stay",
                              90, "Exit when 3-month high-low / concentration criteria no longer met on quarterly review"),
    "ASM Long-Term Stage II": ("Trade-to-trade + 100% margin. No intraday netting.",
                               "Quarterly review; stages step DOWN one at a time",
                               90, "Stage-down when criteria cool; sequential exit via Stage I"),
    "ASM Long-Term Stage III": ("T2T + 100% margin + 5% band tightening.",
                                "Quarterly review", 90, "Sequential stage-down on cooling criteria"),
    "ASM Long-Term Stage IV": ("T2T + 100% margin + tightest band + possible periodic call auction.",
                               "Quarterly review", 90, "Sequential stage-down on cooling criteria"),
    "ASM Short-Term Stage I": ("50–100% additional margin for a SHORT window.",
                               "Auto review after 5/15 trading days (per trigger)",
                               7, "Auto-exit after the 5- or 15-day window unless re-triggered (e.g. another +25%/5-session burst)"),
    "ASM Short-Term Stage II": ("100% margin, short window.",
                                "Auto review after 5/15 trading days",
                                7, "Auto-exit after window unless re-triggered"),
    "GSM": ("Fundamentals-vs-price mismatch framework: T2T, 100% margin; higher stages add buyer-pays Additional Surveillance Deposit, trading once-a-week, up to near-freeze.",
            "Quarterly review",
            90, "Exit needs improved fundamentals relative to price (PE/book/net-worth tests) on quarterly review"),
}


def _stage_info(flag):
    if not flag:
        return None
    for k, v in sorted(STAGE_INFO.items(), key=lambda kv: -len(kv[0])):
        if k in flag:
            return v
    if "GSM" in flag:
        return STAGE_INFO["GSM"]
    return None


def _estimate_start(p, first_seen):
    """Estimate when restrictions began: start of the current band-locked run, else first-seen."""
    ret = p["close"].pct_change().abs() * 100
    lock = (((ret >= 1.7) & (ret <= 2.05)) | ((ret >= 4.4) & (ret <= 5.05))).rolling(8).sum() >= 5
    if lock.iloc[-1]:
        run_start = None
        for i in range(len(lock) - 1, 5, -1):
            if not lock.iloc[i]:
                run_start = i + 1
                break
        if run_start and run_start < len(p):
            return p["date"].iloc[max(5, run_start - 8)].date().isoformat() + " (est. from band-lock)"
    return first_seen


def run():
    master = json.load(open(os.path.join(DATA, "master_ipo.json")))
    panel = _series(pd.read_parquet(os.path.join(DATA, "prices_panel.parquet")))
    ff = json.load(open(os.path.join(DATA, "freefloat.json"))) if os.path.exists(
        os.path.join(DATA, "freefloat.json")) else {}
    official, official_raw = fetch_official()
    print(f"official surveillance flags fetched: {len(official)} listed securities (NSE)")

    hist_path = os.path.join(DATA, "surv_history.json")
    hist = json.load(open(hist_path)) if os.path.exists(hist_path) else {}
    today = dt.date.today().isoformat()

    series_by_isin = {i: g.reset_index(drop=True) for i, g in panel.groupby("isin")}
    out = {}
    for m in master:
        isin = m.get("isin")
        p = series_by_isin.get(isin)
        if p is None or not isin:
            continue
        mcap = (ff.get(isin) or {}).get("mcap_cr")
        offi = official.get(isin)
        entry = {"official": offi, "band_locked": band_lock_state(p),
                 "risks": risk_rules(p, m["board"], mcap),
                 "source": official_raw.get(isin)}
        if offi:
            h = hist.setdefault(isin, {})
            if h.get("flag") != offi:               # new flag or stage change
                h["flag"], h["first_seen"] = offi, today
            first_seen = h["first_seen"]
            info = _stage_info(offi)
            est_start = _estimate_start(p, first_seen)
            entry["since"] = est_start
            if info:
                imp, review, min_days, exit_rule = info
                entry["implication"] = imp
                entry["review"] = review
                entry["exit_rule"] = exit_rule
                try:
                    base_date = pd.Timestamp(est_start.split(" ")[0])
                    entry["earliest_exit"] = (base_date + pd.Timedelta(days=min_days)).date().isoformat()
                except Exception:
                    entry["earliest_exit"] = None
                # is it currently cooling? (exit-criteria check)
                checks = []
                if "ESM" in offi and mcap:
                    checks.append(f"mcap ₹{mcap:.0f}cr {'≥' if mcap >= 500 else 'still <'} ₹500cr pool boundary")
                if len(p) >= 64:
                    r3m = (p["close"].iloc[-1] / p["close"].iloc[-64] - 1) * 100
                    checks.append(f"3-month move now {r3m:+.0f}% ({'cooled' if abs(r3m) < 75 else 'still hot'})")
                if len(p) >= 6:
                    r5 = (p["close"].iloc[-1] / p["close"].iloc[-6] - 1) * 100
                    checks.append(f"5-session move {r5:+.0f}%")
                entry["exit_check"] = "; ".join(checks)
        if entry["official"] or entry["band_locked"] or entry["risks"]:
            out[isin] = entry
    json.dump(hist, open(hist_path, "w"))

    ev, stats = event_study(series_by_isin)
    ev.to_csv(os.path.join(DATA, "bandlock_events.csv"), index=False)
    result = {"as_of": dt.date.today().isoformat(), "flags": out, "bandlock_study": stats}
    json.dump(result, open(os.path.join(DATA, "surveillance.json"), "w"), indent=1)
    n_off = sum(1 for v in out.values() if v["official"])
    n_lock = sum(1 for v in out.values() if v["band_locked"])
    print(f"surveillance: {len(out)} flagged | official {n_off} | band-locked now {n_lock} | study: {stats}")
    return result


if __name__ == "__main__":
    run()
