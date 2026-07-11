"""IPO Radar — signal engine.

States:
  TRIGGER — closed above listing-day high (the pivot) in the last 3 sessions, within
            25 sessions of listing, all quality gates passed. Actionable entry.
  SETUP   — quality gates passed, still basing below pivot, within 40 sessions,
            CMP within 15% of pivot. Watch for the breakout.
  RIDE    — broke out earlier and still holding above the pivot. Manage, don't chase.
  AVOID   — never reclaimed pivot after 25 sessions, or deep/broken base, or below issue.
  NEUTRAL — everything else (too early, gates not met, insufficient data).

Every stock gets 4-6 plain-language reasons explaining the classification,
plus Entry / Stop / Target / R:R for TRIGGER and SETUP.
"""
import json
import math
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")

# Composite-rule expectancy from the Stage-1 study (384 IPOs, Jul-25 → Jul-26)
STUDY = {
    "composite_r60_med": 8.8, "composite_win": 62,
    "sme_r60_med": 14.3, "sme_win": 75,
    "late_breakout_r60": -15.0, "late_breakout_win": 17,
    "never_broke_med": -38.4,
}


def _lm_league() -> dict:
    """lead manager -> (issues, %positive listings) pooled across years/boards."""
    import glob
    import re
    pool = {}
    for f in glob.glob(os.path.join(DATA, "rep19_*.json")):
        for r in json.load(open(f)):
            name = re.sub(r"<[^>]+>", "", str(r.get("Lead Manager", ""))).strip()
            n = r.get("Issues Managed") or 0
            pos = r.get("% of Positive listing")
            if not name or pos in ("", None):
                continue
            iss, wpos = pool.get(name, (0, 0.0))
            pool[name] = (iss + n, wpos + float(pos) * n)
    return {k: (n, round(w / n, 1)) for k, (n, w) in pool.items() if n}


def compute_signals() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    lm_map = {int(k): v for k, v in json.load(open(os.path.join(DATA, "lm_map.json"))).items()}
    league = _lm_league()
    last_date = panel["date"].max()

    out = []
    for _, r in df.iterrows():
        sig = {"state": "NEUTRAL", "reasons": [], "entry": None, "stop": None,
               "target": None, "rr": None, "score": 0}
        board_sme = r["board"] == "SME"
        days = int(r["trading_days"])
        cmp_ = r["cmp_bhav"]
        pivot = r["d1_high"]
        issue = r["issue_price"]
        adv = r["avg_turnover_cr_20d"]
        qib = r["qib_x"]
        sub = r["subscription_total_x"]
        base_low = r["base30_low_vs_d1close_pct"]
        bo_day = r["d1high_breakout_day"]
        pop = r["open_pop_pct"]
        lms = lm_map.get(int(r["chittorgarh_id"]), [])
        lm_name = lms[0] if lms else None
        lm_stats = league.get(lm_name) if lm_name else None

        # ---------- quality gates ----------
        qib_ok = (not math.isnan(qib) and qib >= 15) or (math.isnan(qib) and not math.isnan(sub) and sub >= 20)
        base_known = not (isinstance(base_low, float) and math.isnan(base_low))
        base_ok = base_known and base_low > -15
        # for very young listings use running low
        if not base_known and days >= 5 and not math.isnan(r["life_low"]) and not math.isnan(r["d1_close"]):
            base_low = round((r["life_low"] / r["d1_close"] - 1) * 100, 1)
            base_ok = base_low > -15
            base_known = True
        liq_min = 2 if board_sme else 5
        liq_ok = not math.isnan(adv) and adv >= liq_min
        pop_ok = not math.isnan(pop) and 0 <= pop <= 50
        above_issue = not math.isnan(issue) and cmp_ > issue
        dist_pivot = (pivot / cmp_ - 1) * 100  # % CMP must rise to hit pivot
        broke = not (isinstance(bo_day, float) and math.isnan(bo_day))

        # anchor expiry proximity (calendar-day approximation)
        expiry_soon = None
        for key, tag in (("anchor_lockin_30d", "30-day"), ("anchor_lockin_90d", "90-day")):
            v = r.get(key)
            if isinstance(v, str) and v:
                delta = (pd.Timestamp(v) - last_date).days
                if 0 <= delta <= 7:
                    expiry_soon = (tag, v, delta)

        gates = sum([qib_ok, base_ok, liq_ok, pop_ok])

        # ---------- classify ----------
        if broke and bo_day <= 25:
            bo_idx = int(bo_day)
            recent_bo = (days - 1) - bo_idx <= 3
            still_above = cmp_ > pivot
            if recent_bo and gates >= 3:
                sig["state"] = "TRIGGER"
            elif still_above and gates >= 3:
                sig["state"] = "RIDE"
            elif not still_above and days > 25 and cmp_ < pivot * 0.85:
                sig["state"] = "AVOID"  # failed breakout
        elif not broke:
            if days > 25:
                sig["state"] = "AVOID"
            elif gates >= 3 and dist_pivot <= 15 and days <= 40:
                sig["state"] = "SETUP"
        if base_known and base_low <= -25 and sig["state"] in ("NEUTRAL", "SETUP"):
            sig["state"] = "AVOID"
        if expiry_soon and sig["state"] in ("TRIGGER", "SETUP"):
            sig["state"] = "SETUP" if sig["state"] == "TRIGGER" else "NEUTRAL"

        # ---------- reasons (4-6, plain language) ----------
        R = sig["reasons"]
        # 1 institutional demand
        if not math.isnan(qib):
            if qib >= 50:
                R.append(f"Very strong institutional demand — QIB book {qib:.0f}x (top-quartile QIB names went on to +74% median lifetime gains in our study)")
            elif qib >= 15:
                R.append(f"Strong institutional demand — QIB subscribed {qib:.0f}x (study threshold ≥15x lifts 60-day win rate to 62%)")
            else:
                R.append(f"Weak institutional interest — QIB only {qib:.1f}x, below the 15x quality bar")
        elif not math.isnan(sub):
            R.append(f"Total subscription {sub:.0f}x (no separate QIB book published)")
        # 2 base quality
        if base_known:
            if base_low > -8:
                R.append(f"Tight post-listing base — held within {abs(base_low):.1f}% of listing close (winners' median was only −6.8%)")
            elif base_low > -15:
                R.append(f"Acceptable base depth — low was {base_low:.1f}% vs listing close (inside the −15% study cutoff)")
            else:
                R.append(f"Deep/broken base — flushed {base_low:.1f}% below listing close; deep bases marked distribution, not accumulation")
        # 3 pivot status
        if sig["state"] == "TRIGGER":
            R.append(f"Just closed above the listing-day high ₹{pivot:,.1f} on day {int(bo_day)} — early pivot reclaims (≤25 sessions) returned +8.8% median / 62% win in 60 days; SME subset +14.3% / 75%")
        elif sig["state"] == "RIDE":
            R.append(f"Broke the ₹{pivot:,.1f} pivot on day {int(bo_day)} and still holds above it — trend intact, manage with a trailing stop rather than fresh risk")
        elif sig["state"] == "SETUP":
            R.append(f"Basing {dist_pivot:.1f}% below the ₹{pivot:,.1f} pivot with {days} sessions on the clock — a close above it inside 25 sessions is the trigger")
        elif not broke and days > 25:
            R.append(f"Still below its listing-day high after {days} sessions — IPOs that never reclaimed the pivot sit at −38% median; late reclaims won only 17% of the time")
        elif broke and cmp_ < pivot:
            R.append(f"Broke out but failed to hold the pivot — now {abs(dist_pivot):.1f}% back below it")
        # 4 liquidity
        if not math.isnan(adv):
            if adv >= 5:
                R.append(f"Tradeable liquidity — ₹{adv:.1f}cr average daily turnover (≥₹5cr cohort outperformed illiquid names by 25 points)")
            elif adv >= liq_min:
                R.append(f"Adequate SME liquidity at ₹{adv:.1f}cr daily turnover — size positions ≤5% of daily volume")
            else:
                R.append(f"Illiquid — only ₹{adv:.2f}cr daily turnover; the illiquid cohort bled −17% median. Position exit is the real risk here")
        # 5 lock-in timing
        if expiry_soon:
            R.append(f"⚠ Anchor {expiry_soon[0]} lock-in expires {expiry_soon[1]} ({expiry_soon[2]}d away) — median drift −2.4% into expiry; stand aside until supply clears")
        elif isinstance(r.get("anchor_lockin_90d"), str) and r["anchor_lockin_90d"] and pd.Timestamp(r["anchor_lockin_90d"]) > last_date:
            R.append(f"Next supply event: anchor 90-day lock-in on {r['anchor_lockin_90d']} — plan to be trimmed or trailing by then")
        # 6 lead manager
        if lm_name and lm_stats:
            n_iss, pos = lm_stats
            tag = "strong" if pos >= 70 else "average" if pos >= 50 else "weak"
            R.append(f"Lead manager {lm_name} — {tag} track record ({pos:.0f}% positive listings across {n_iss} issues this cycle)")
        # 7 pop context (only if room)
        if len(R) < 6 and not math.isnan(pop):
            if 5 <= pop <= 50:
                R.append(f"Listed in the sweet spot (+{pop:.0f}% open) — the +5–50% pop bucket produced the best lifetime run-ups")
            elif pop < -5:
                R.append(f"Discount listing ({pop:.0f}%) — the worst-performing cohort in the study")
            elif pop > 50:
                R.append(f"Mega-pop listing (+{pop:.0f}%) — these faded −19% median after day 1; the easy move already happened")

        # ---------- trade plan ----------
        if sig["state"] in ("TRIGGER", "SETUP"):
            entry = pivot
            base_stop = entry * (1 + max(base_low, -8) / 100) if base_known else entry * 0.92
            stop = max(base_stop, entry * 0.92)
            target = entry * 1.15
            sig.update({"entry": round(entry, 2), "stop": round(stop, 2),
                        "target": round(target, 2),
                        "rr": round((target - entry) / (entry - stop), 1) if entry > stop else None})

        sig["score"] = gates * 20 + (10 if above_issue else 0) + (10 if sig["state"] == "TRIGGER" else 0)
        out.append({
            "company": r["company"], "board": r["board"], "symbol": r["symbol"],
            "exchange": r["exchange"], "listing_date": r["listing_date"],
            "state": sig["state"], "score": sig["score"],
            "cmp": cmp_, "pivot": pivot, "dist_to_pivot_pct": round(dist_pivot, 1),
            "qib_x": qib, "sub_x": sub, "adv_cr": adv,
            "base_low_pct": base_low if base_known else np.nan,
            "days_listed": days, "breakout_day": bo_day,
            "cmp_vs_issue_pct": r["cmp_vs_issue_pct"],
            "entry": sig["entry"], "stop": sig["stop"], "target": sig["target"], "rr": sig["rr"],
            "lead_manager": lm_name or "",
            "anchor_30d": r.get("anchor_lockin_30d"), "anchor_90d": r.get("anchor_lockin_90d"),
            "reasons": " • ".join(R[:6]),
        })

    res = pd.DataFrame(out)
    order = {"TRIGGER": 0, "SETUP": 1, "RIDE": 2, "NEUTRAL": 3, "AVOID": 4}
    res["state_rank"] = res["state"].map(order)
    res = res.sort_values(["state_rank", "score", "qib_x"], ascending=[True, False, False]).drop(columns="state_rank")
    res.to_csv(os.path.join(DATA, "signals.csv"), index=False)
    return res


if __name__ == "__main__":
    s = compute_signals()
    print(s["state"].value_counts().to_string())
    print("\nTop signals:")
    cols = ["company", "board", "state", "cmp", "pivot", "qib_x", "adv_cr", "rr"]
    print(s[s["state"].isin(["TRIGGER", "SETUP"])][cols].head(12).to_string(index=False))
