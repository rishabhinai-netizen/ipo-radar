"""IPO Radar — signal engine.

States: TRIGGER / SETUP / RIDE / AVOID / NEUTRAL (see method tab for definitions).

Trade-plan math (nothing is random — every number has a rule):
  ENTRY  = the pivot = listing-day HIGH. The study showed the first close above it
           (within 25 sessions) is the highest-expectancy entry point.
  STOP   = the HIGHER of (a) the base low — the lowest low since listing, i.e. the
           level whose break proves the base failed — and (b) entry − 8%
           (O'Neil's hard maximum loss). Whichever risks LESS.
  TARGET = entry + 15%: the historical median 60-session gain of qualifying
           breakouts sat in the +9…+15% band, so +15% is where you take partial
           profit and switch to a trailing stop for the tail (winners' median
           run lasted ~60 sessions to peak).
  R:R    = (target − entry) / (entry − stop).
"""
import json
import math
import os

import numpy as np
import pandas as pd

import config

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _links(nse_symbol, bse_code):
    if isinstance(nse_symbol, str) and nse_symbol.strip():
        s = nse_symbol.strip()
        return (f"https://www.screener.in/company/{s}/",
                f"https://www.tradingview.com/chart/?symbol=NSE%3A{s}")
    if isinstance(bse_code, str) and bse_code.strip() and bse_code.strip() != "nan":
        c = bse_code.strip().split(".")[0]
        return (f"https://www.screener.in/company/{c}/",
                f"https://www.tradingview.com/chart/?symbol=BSE%3A{c}")
    return "", ""


def compute_signals() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    lm_map = {str(k): v for k, v in json.load(open(os.path.join(DATA, "lm_map.json"))).items()}
    sc_path = os.path.join(DATA, "lm_scorecard.csv")
    scorecard = (pd.read_csv(sc_path).set_index("lead_manager")
                 if os.path.exists(sc_path) else pd.DataFrame())
    last_date = pd.Timestamp(panel["date"].max())

    out = []
    for _, r in df.iterrows():
        sig = {"state": "NEUTRAL", "reasons": [], "entry": None, "stop": None,
               "stop_basis": "", "target": None, "rr": None, "score": 0}
        board_sme = r["board"] == "SME"
        days = int(r["trading_days"])
        cmp_, pivot, issue = r["cmp_bhav"], r["d1_high"], r["issue_price"]
        adv, qib, sub = r["avg_turnover_cr_20d"], r["qib_x"], r["subscription_total_x"]
        base_low, bo_day, pop = r["base30_low_vs_d1close_pct"], r["d1high_breakout_day"], r["open_pop_pct"]
        lms = lm_map.get(str(int(r["chittorgarh_id"])), [])
        lm_name = lms[0] if lms else None

        qib_ok = (not math.isnan(qib) and qib >= config.QIB_MIN) or \
                 (math.isnan(qib) and not math.isnan(sub) and sub >= config.SUB_MIN)
        base_known = not (isinstance(base_low, float) and math.isnan(base_low))
        if not base_known and days >= 5 and not math.isnan(r["life_low"]) and not math.isnan(r["d1_close"]):
            base_low = round((r["life_low"] / r["d1_close"] - 1) * 100, 1)
            base_known = True
        base_ok = base_known and base_low > config.BASE_MIN_PCT
        liq_min = config.ADV_MIN_SME if board_sme else config.ADV_MIN_MAIN
        liq_ok = not math.isnan(adv) and adv >= liq_min
        pop_ok = not math.isnan(pop) and config.POP_MIN <= pop <= config.POP_MAX
        above_issue = not math.isnan(issue) and cmp_ > issue
        dist_pivot = (pivot / cmp_ - 1) * 100
        broke = not (isinstance(bo_day, float) and math.isnan(bo_day))

        expiry_soon = None
        for key, tag in (("anchor_lockin_30d", "30-day"), ("anchor_lockin_90d", "90-day")):
            v = r.get(key)
            if isinstance(v, str) and v:
                delta = (pd.Timestamp(v) - last_date).days
                if 0 <= delta <= 7:
                    expiry_soon = (tag, v, delta)
        gates = sum([qib_ok, base_ok, liq_ok, pop_ok])

        if broke and bo_day <= config.BREAKOUT_WINDOW:
            recent_bo = (days - 1) - int(bo_day) <= 3
            still_above = cmp_ > pivot
            if recent_bo and gates >= 3:
                sig["state"] = "TRIGGER"
            elif still_above and gates >= 3:
                sig["state"] = "RIDE"
            elif not still_above and days > 25 and cmp_ < pivot * 0.85:
                sig["state"] = "AVOID"
        elif not broke:
            if days > config.BREAKOUT_WINDOW:
                sig["state"] = "AVOID"
            elif gates >= 3 and dist_pivot <= 15 and days <= 40:
                sig["state"] = "SETUP"
        if base_known and base_low <= -25 and sig["state"] in ("NEUTRAL", "SETUP"):
            sig["state"] = "AVOID"
        if expiry_soon and sig["state"] in ("TRIGGER", "SETUP"):
            sig["state"] = "SETUP" if sig["state"] == "TRIGGER" else "NEUTRAL"

        # ----- reasons -----
        R = sig["reasons"]
        if not math.isnan(qib):
            if qib >= 50:
                R.append(f"Very strong institutional demand — QIB {qib:.0f}x (top-QIB quartile made the biggest lifetime gains in the study)")
            elif qib >= config.QIB_MIN:
                R.append(f"Strong institutional demand — QIB {qib:.0f}x (≥{config.QIB_MIN}x is the study's quality bar)")
            else:
                R.append(f"Weak institutional interest — QIB only {qib:.1f}x, below the {config.QIB_MIN}x bar")
        elif not math.isnan(sub):
            R.append(f"Total subscription {sub:.0f}x (QIB book not separately published)")
        if base_known:
            if base_low > -8:
                R.append(f"Tight post-listing base — never gave up more than {abs(base_low):.1f}% from listing close (winners' hallmark)")
            elif base_low > config.BASE_MIN_PCT:
                R.append(f"Acceptable base — low {base_low:.1f}% vs listing close, inside the {config.BASE_MIN_PCT}% cutoff")
            else:
                R.append(f"Deep/broken base — flushed {base_low:.1f}% below listing close; that flush marked distribution in the study")
        if sig["state"] == "TRIGGER":
            R.append(f"Fresh close above the ₹{pivot:,.1f} pivot on session {int(bo_day)} — early reclaims were the single best entry in the study")
        elif sig["state"] == "RIDE":
            R.append(f"Reclaimed the ₹{pivot:,.1f} pivot on session {int(bo_day)} and still holds above — manage with a trailing stop, don't add fresh risk here")
        elif sig["state"] == "SETUP":
            R.append(f"Basing {dist_pivot:.1f}% below the ₹{pivot:,.1f} pivot, {days} sessions old — the trigger is a daily close above it inside session {config.BREAKOUT_WINDOW}")
        elif not broke and days > config.BREAKOUT_WINDOW:
            R.append(f"Still below its listing-day high after {days} sessions — the never-reclaimed cohort sits deeply negative; late reclaims won rarely")
        elif broke and cmp_ < pivot:
            R.append(f"Broke out but lost the pivot — now {abs(dist_pivot):.1f}% back below it")
        if not math.isnan(adv):
            if adv >= config.ADV_MIN_MAIN:
                R.append(f"Real liquidity — ₹{adv:.1f}cr average daily turnover")
            elif adv >= liq_min:
                R.append(f"Adequate SME liquidity (₹{adv:.1f}cr/day) — size entries ≤5% of daily volume")
            else:
                R.append(f"Illiquid — ₹{adv:.2f}cr/day; the illiquid cohort bled badly. Exit is the real risk")
        if expiry_soon:
            R.append(f"⚠ Anchor {expiry_soon[0]} lock-in expires {expiry_soon[1]} ({expiry_soon[2]}d) — supply event, stand aside until absorbed")
        elif isinstance(r.get("anchor_lockin_90d"), str) and r["anchor_lockin_90d"] and pd.Timestamp(r["anchor_lockin_90d"]) > last_date:
            R.append(f"Next supply event: 90-day anchor lock-in {r['anchor_lockin_90d']} — plan to be trailing or trimmed by then")
        if lm_name and len(scorecard) and lm_name in scorecard.index:
            s = scorecard.loc[lm_name]
            R.append(f"Lead manager {lm_name}: {s['pct_above_issue_today']:.0f}% of its {int(s['issues'])} issues trade above issue price today (median {s['median_now_vs_issue_pct']:+.0f}%)")
        elif lm_name:
            R.append(f"Lead manager {lm_name} (fewer than 3 issues in window — no scorecard)")
        if len(R) < 6 and not math.isnan(pop):
            if 5 <= pop <= 50:
                R.append(f"Listed in the sweet spot (+{pop:.0f}% open) — the +5–50% band produced the best subsequent runs")
            elif pop < -5:
                R.append(f"Discount listing ({pop:.0f}%) — historically the worst cohort")
            elif pop > 50:
                R.append(f"Mega-pop (+{pop:.0f}%) — these faded hard after day 1")

        # ----- trade plan -----
        if sig["state"] in ("TRIGGER", "SETUP"):
            entry = pivot
            hard_stop_price = entry * (1 + config.HARD_STOP_PCT / 100)
            if base_known:
                base_stop_price = r["d1_close"] * (1 + base_low / 100)
                if base_stop_price >= hard_stop_price:
                    stop, basis = base_stop_price, f"base low ({base_low:.1f}% vs listing close)"
                else:
                    stop, basis = hard_stop_price, f"hard {config.HARD_STOP_PCT}% cap (base low is further)"
            else:
                stop, basis = hard_stop_price, f"hard {config.HARD_STOP_PCT}% cap (base still forming)"
            target = entry * (1 + config.TARGET1_PCT / 100)
            sig.update({"entry": round(entry, 2), "stop": round(stop, 2), "stop_basis": basis,
                        "target": round(target, 2),
                        "rr": round((target - entry) / (entry - stop), 1) if entry > stop else None})

        scr, tv = _links(r.get("nse_symbol"), str(r.get("bse_code")))
        sig["score"] = gates * 20 + (10 if above_issue else 0) + (10 if sig["state"] == "TRIGGER" else 0)
        out.append({
            "company": r["company"], "board": r["board"], "symbol": r["symbol"],
            "exchange": r["exchange"], "isin": r["isin"], "listing_date": r["listing_date"],
            "state": sig["state"], "score": sig["score"],
            "cmp": cmp_, "pivot": pivot, "dist_to_pivot_pct": round(dist_pivot, 1),
            "qib_x": qib, "sub_x": sub, "adv_cr": adv,
            "base_low_pct": base_low if base_known else np.nan,
            "days_listed": days, "breakout_day": bo_day,
            "cmp_vs_issue_pct": r["cmp_vs_issue_pct"],
            "entry": sig["entry"], "stop": sig["stop"], "stop_basis": sig["stop_basis"],
            "target": sig["target"], "rr": sig["rr"],
            "lead_manager": lm_name or "",
            "anchor_30d": r.get("anchor_lockin_30d"), "anchor_90d": r.get("anchor_lockin_90d"),
            "screener_url": scr, "tradingview_url": tv,
            "reasons": " • ".join(R[:6]),
        })

    res = pd.DataFrame(out)
    order = {"TRIGGER": 0, "SETUP": 1, "RIDE": 2, "NEUTRAL": 3, "AVOID": 4}
    res["state_rank"] = res["state"].map(order)
    res = res.sort_values(["state_rank", "score", "qib_x"],
                          ascending=[True, False, False]).drop(columns="state_rank")
    res.to_csv(os.path.join(DATA, "signals.csv"), index=False)
    return res


if __name__ == "__main__":
    s = compute_signals()
    