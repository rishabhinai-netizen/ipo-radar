"""IPO Radar — signal engine v3: 0–100 score, recommendation labels, analogs.

SCORE (0–100), weights set by what the walk-forward backtest actually rewarded:
  Structure 35 — fresh pivot reclaim ≤25 sessions is the entry with edge
  Base      20 — low-to-date vs listing close (−10% optimum from grid search)
  Liquidity 15 — you can't harvest edge you can't exit
  Institutional 15 — QIB (scoring input only; hard-gating it cut expectancy)
  Lock-in    5 — anchor expiry within 10 sessions = supply risk
  LM quality 5 — lead manager's post-listing scorecard
  Momentum   5 — above issue price and above 20-EMA

RECO labels:
  FRESH BUY  — pivot reclaimed in the last 3 sessions, score ≥ 65
  BUY-SETUP  — basing within 10% of pivot, ≤40 sessions, score ≥ 60
  RIDE       — above pivot with healthy trend, score ≥ 55
  EXIT       — was above the pivot but has lost it AND the 20-EMA
  WATCH      — young or middling — no action
  AVOID      — failed pivot >25 sessions / broken base / score < 35

ANALOGS: for each actionable stock, the 3 most similar historical IPOs
(z-scored distance on QIB, open pop, base depth, D1 gain, issue size, breakout
day; same-board preferred) with their real outcomes — pattern recognition,
not prophecy.
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


def _analog_table(df):
    """Reference set: seasoned IPOs with known outcomes."""
    ref = df[df["trading_days"] >= 120].copy()
    feats = ["qib_x", "open_pop_pct", "base30_low_vs_d1close_pct",
             "d1_close_vs_issue_pct", "issue_amount_cr", "d1high_breakout_day"]
    X = ref[feats].copy()
    X["qib_x"] = np.log1p(X["qib_x"])
    X["issue_amount_cr"] = np.log1p(X["issue_amount_cr"])
    X["d1high_breakout_day"] = X["d1high_breakout_day"].fillna(60)
    mu, sd = X.mean(), X.std().replace(0, 1)
    return ref.reset_index(drop=True), ((X - mu) / sd).fillna(0).values, feats, mu, sd


def _find_analogs(row, ref, Z, feats, mu, sd, self_isin):
    x = pd.Series({f: row.get(f) for f in feats}, dtype=float)
    x["qib_x"] = np.log1p(x["qib_x"])
    x["issue_amount_cr"] = np.log1p(x["issue_amount_cr"])
    if math.isnan(x["d1high_breakout_day"]):
        x["d1high_breakout_day"] = 60
    z = ((x - mu) / sd).fillna(0).values
    d = np.sqrt(((Z - z) ** 2).sum(axis=1))
    d = d + (ref["board"] != row["board"]).values * 0.7  # same-board preference
    d[ref["isin"] == self_isin] = 9e9
    idx = np.argsort(d)[:3]
    out = []
    for i in idx:
        a = ref.iloc[i]
        r60 = a.get("ret_60d_after_breakout_pct")
        tail = (f"{r60:+.0f}% in 60d after its breakout" if pd.notna(r60)
                else f"{a['cmp_vs_issue_pct']:+.0f}% vs issue to date")
        out.append(f"{a['company'].replace(' Ltd.','')} ({a['listing_date'][:7]}): "
                   f"peaked {a['life_high_vs_issue_pct']:+.0f}%, {tail}")
    return " | ".join(out)


def compute_signals() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    lm_map = {str(k): v for k, v in json.load(open(os.path.join(DATA, "lm_map.json"))).items()}
    sc_path = os.path.join(DATA, "lm_scorecard.csv")
    scorecard = (pd.read_csv(sc_path).set_index("lead_manager")
                 if os.path.exists(sc_path) else pd.DataFrame())
    ff_path = os.path.join(DATA, "freefloat.json")
    ff = json.load(open(ff_path)) if os.path.exists(ff_path) else {}
    sv_path = os.path.join(DATA, "surveillance.json")
    surv = (json.load(open(sv_path)).get("flags", {}) if os.path.exists(sv_path) else {})
    last_date = pd.Timestamp(panel["date"].max())
    ref, Z, feats, mu, sd = _analog_table(df)

    out = []
    for _, r in df.iterrows():
        board_sme = r["board"] == "SME"
        days = int(r["trading_days"])
        cmp_, pivot, issue = r["cmp_bhav"], r["d1_high"], r["issue_price"]
        adv, qib, sub = r["avg_turnover_cr_20d"], r["qib_x"], r["subscription_total_x"]
        base_low, bo_day, pop = r["base30_low_vs_d1close_pct"], r["d1high_breakout_day"], r["open_pop_pct"]
        lms = lm_map.get(str(int(r["chittorgarh_id"])), [])
        lm_name = lms[0] if lms else None
        above_ema20 = bool(r.get("above_ema20", False))
        base_known = not (isinstance(base_low, float) and math.isnan(base_low))
        if not base_known and days >= 5 and not math.isnan(r["life_low"]) and not math.isnan(r["d1_close"]):
            base_low = round((r["life_low"] / r["d1_close"] - 1) * 100, 1)
            base_known = True
        broke = not (isinstance(bo_day, float) and math.isnan(bo_day))
        early_break = broke and bo_day <= config.BREAKOUT_WINDOW
        fresh = early_break and (days - 1) - int(bo_day) <= 3
        # LATE BLOOMER live signal: fresh cross (≤3 sessions ago) on day 26-120 WITH a recent volume thrust
        dspc = r.get("days_since_pivot_cross")
        late_fresh = False
        if not fresh and pd.notna(dspc) and dspc <= 3 and bool(r.get("thrust_recent")):
            cross_day = (days - 1) - int(dspc)
            if 25 < cross_day <= config.LATE_WINDOW:
                late_fresh = True
                fresh = True
                early_break = True
        above_pivot = cmp_ > pivot
        dist_pivot = (pivot / cmp_ - 1) * 100
        in_setup_zone = (not broke) and 5 <= days <= 40 and 0 <= dist_pivot <= 10

        expiry_soon = None
        for key, tag in (("anchor_lockin_30d", "30-day"), ("anchor_lockin_90d", "90-day")):
            v = r.get(key)
            if isinstance(v, str) and v:
                delta = (pd.Timestamp(v) - last_date).days
                if 0 <= delta <= 10:
                    expiry_soon = (tag, v, delta)

        # ---------------- score ----------------
        s_struct = (35 if fresh else 28 if (early_break and above_pivot)
                    else 20 if in_setup_zone else 10 if (not broke and days <= 25)
                    else 8 if above_pivot else 0)
        s_base = (0 if not base_known else
                  20 if base_low > -10 else 14 if base_low > -15 else
                  6 if base_low > -25 else 0)
        s_liq = (15 if (not math.isnan(adv) and adv >= 5) else
                 10 if (not math.isnan(adv) and adv >= 2) else
                 6 if (not math.isnan(adv) and adv >= 1) else 0)
        s_inst = (15 if (not math.isnan(qib) and qib >= 50) else
                  11 if (not math.isnan(qib) and qib >= 15) else
                  6 if (not math.isnan(qib) and qib >= 5) else
                  8 if (math.isnan(qib) and not math.isnan(sub) and sub >= 20) else 2)
        s_lock = 0 if expiry_soon else 5
        lm_sc = None
        if lm_name and len(scorecard) and lm_name in scorecard.index:
            lm_sc = scorecard.loc[lm_name]
        s_lm = 5 if (lm_sc is not None and lm_sc["lm_score"] >= 70) else \
               3 if (lm_sc is not None and lm_sc["lm_score"] >= 40) else 1
        s_mom = 5 if (not math.isnan(issue) and cmp_ > issue and above_ema20) else \
                3 if ((not math.isnan(issue) and cmp_ > issue) or above_ema20) else 0
        sv = surv.get(str(r["isin"])) or {}
        sv_official, sv_band, sv_risks = sv.get("official"), sv.get("band_locked"), sv.get("risks") or []
        s_surv = -15 if sv_official else (-8 if sv_band else 0)
        score = max(0, s_struct + s_base + s_liq + s_inst + s_lock + s_lm + s_mom + s_surv)

        # ---------------- reco ----------------
        if (sv_official or sv_band) and fresh:
            fresh = False  # never issue a fresh entry into a surveillance cage
        if fresh and score >= 65:
            reco = "FRESH BUY"
        elif in_setup_zone and score >= 60:
            reco = "BUY-SETUP"
        elif early_break and above_pivot and score >= 55:
            reco = "RIDE"
        elif broke and not above_pivot and not above_ema20:
            reco = "EXIT"
        elif (not broke and days > config.BREAKOUT_WINDOW) or score < 35 or \
                (base_known and base_low <= -25):
            reco = "AVOID"
        else:
            reco = "WATCH"
        state = {"FRESH BUY": "TRIGGER", "BUY-SETUP": "SETUP", "RIDE": "RIDE",
                 "EXIT": "AVOID", "AVOID": "AVOID", "WATCH": "NEUTRAL"}[reco]

        # ---------------- reasons ----------------
        R = []
        R.append(f"Score {score}/100 — structure {s_struct}/35, base {s_base}/20, liquidity {s_liq}/15, institutions {s_inst}/15, lock-in {s_lock}/5, LM {s_lm}/5, momentum {s_mom}/5")
        if late_fresh:
            R.append(f"🌙 LATE BLOOMER entry: fresh cross of the ₹{pivot:,.1f} pivot with a volume thrust — the Ather-class signal (study PF 3.05; EXPERIMENTAL — live replay has not yet confirmed this edge)")
        elif fresh:
            R.append(f"Fresh close above the ₹{pivot:,.1f} pivot on session {int(bo_day)} — the walk-forward-validated entry")
        elif in_setup_zone:
            R.append(f"Basing {dist_pivot:.1f}% below the ₹{pivot:,.1f} pivot at {days} sessions — trigger is a daily close above it inside session {config.BREAKOUT_WINDOW}")
        elif early_break and above_pivot:
            R.append(f"Reclaimed the pivot on session {int(bo_day)} and holds above — trend intact; manage, don't add")
        elif reco == "EXIT":
            R.append(f"Lost both the pivot (₹{pivot:,.1f}) and the 20-EMA — the two levels that defined the up-move; edge is gone")
        elif not broke and days > config.BREAKOUT_WINDOW:
            R.append(f"Never reclaimed the listing-day high in {days} sessions — this cohort's median outcome is deeply negative")
        if base_known:
            if base_low > -10:
                R.append(f"Tight base — held within {abs(base_low):.1f}% of listing close (the −10% cutoff was the grid-search optimum)")
            elif base_low > -25:
                R.append(f"Base gave up {base_low:.1f}% vs listing close — looser than the −10% ideal; demands a smaller position")
            else:
                R.append(f"Broken base ({base_low:.1f}%) — distribution, not accumulation")
        if not math.isnan(qib):
            R.append(f"QIB {qib:.0f}x — {'heavy institutional sponsorship (biggest historical tails came from this group)' if qib >= 50 else 'decent institutional interest' if qib >= 15 else 'thin institutional book (score-penalised, not disqualifying: stops manage the risk)'}")
        fl = ff.get(str(r["isin"])) or {}
        ff_vol_pct = mcap_cr = promoter_pct = None
        if fl.get("float_shares") and not math.isnan(r.get("avg_volume_20d", float("nan"))):
            ff_vol_pct = round(r["avg_volume_20d"] / fl["float_shares"] * 100, 2)
            mcap_cr, promoter_pct = fl.get("mcap_cr"), fl.get("promoter_pct")
        if not math.isnan(adv):
            if ff_vol_pct is not None:
                R.append(f"₹{adv:.1f}cr/day turnover ≈ {ff_vol_pct:.1f}% of free float changing hands daily{' — crowded/manipulable, careful' if ff_vol_pct > 4 else ' — healthy churn' if ff_vol_pct > 0.8 else ' — sleepy float'}")
            elif adv < (config.ADV_MIN_SME if board_sme else config.ADV_MIN_MAIN):
                R.append(f"Illiquid — ₹{adv:.2f}cr/day; exits are the real risk")
        if bool(r.get("thrust_recent")):
            R.append(f"🔥 Volume thrust (≥5× avg) within the last 5 sessions ({r.get('last_thrust_date')}) — the institutional footprint that preceded most historical winners")
        if expiry_soon:
            R.append(f"⚠ Anchor {expiry_soon[0]} lock-in expires {expiry_soon[1]} ({expiry_soon[2]}d) — historical median drift −2.4% into expiry; no fresh entries")
        if sv_official:
            R.append(f"🚧 UNDER SURVEILLANCE: {sv_official} — price band capped, 100% margin, liquidity dries (historical band-lock episodes: −5.8% median over next 60 sessions, 41% win)")
        elif sv_band:
            R.append(f"🚧 Trading pinned to a {sv_band} daily band — behaves like a surveillance cage even if not yet listed; volume typically dries −20%")
        for x in sv_risks[:2]:
            R.append(f"⚠ {x}")
        if lm_sc is not None:
            R.append(f"Lead manager {lm_name}: {lm_sc['pct_above_issue_today']:.0f}% of {int(lm_sc['issues'])} issues above issue today, LM score {lm_sc['lm_score']:.0f}/100")
        if days <= 40 and not math.isnan(pop):  # day-1 context only while it's still relevant
            if 5 <= pop <= 50:
                R.append(f"Listed +{pop:.0f}% — the historical sweet-spot band")
            elif pop < -5:
                R.append(f"Discount listing ({pop:.0f}%) — historically the worst cohort")
            elif pop > 50:
                R.append(f"Mega-pop (+{pop:.0f}%) — day-1 buyers are extended; base needs extra proof")

        # ---------------- trade plan ----------------
        entry = stop = target = rr = None
        basis = ""
        if reco in ("FRESH BUY", "BUY-SETUP"):
            entry = pivot
            hard = entry * (1 + config.HARD_STOP_PCT / 100)
            if base_known:
                bstop = r["d1_close"] * (1 + base_low / 100)
                stop, basis = (bstop, f"base low ({base_low:.1f}% vs listing close)") if bstop >= hard \
                    else (hard, f"hard {config.HARD_STOP_PCT}% cap (base low further)")
            else:
                stop, basis = hard, f"hard {config.HARD_STOP_PCT}% cap (base forming)"
            target = entry * (1 + config.TRAIL_ARM_PCT / 100)  # +15% arms the 25% trail
            rr = round((target - entry) / (entry - stop), 1) if entry > stop else None
            entry, stop, target = round(entry, 2), round(stop, 2), round(target, 2)

        analogs = ""
        if reco in ("FRESH BUY", "BUY-SETUP", "RIDE"):
            analogs = _find_analogs(r, ref, Z, feats, mu, sd, r["isin"])

        scr, tv = _links(r.get("nse_symbol"), str(r.get("bse_code")))
        out.append({
            "company": r["company"], "board": r["board"], "symbol": r["symbol"],
            "exchange": r["exchange"], "isin": r["isin"], "listing_date": r["listing_date"],
            "reco": reco, "state": state, "score": score,
            "cmp": cmp_, "pivot": pivot, "dist_to_pivot_pct": round(dist_pivot, 1),
            "qib_x": qib, "sub_x": sub, "adv_cr": adv,
            "base_low_pct": base_low if base_known else np.nan,
            "days_listed": days, "breakout_day": bo_day,
            "cmp_vs_issue_pct": r["cmp_vs_issue_pct"],
            "entry": entry, "stop": stop, "stop_basis": basis, "target": target, "rr": rr,
            "lead_manager": lm_name or "",
            "anchor_30d": r.get("anchor_lockin_30d"), "anchor_90d": r.get("anchor_lockin_90d"),
            "screener_url": scr, "tradingview_url": tv,
            "ff_vol_pct": ff_vol_pct, "mcap_cr": mcap_cr, "promoter_pct": promoter_pct,
            "surv_official": sv_official or "", "surv_band": sv_band or "",
            "surv_risk": " | ".join(sv_risks),
            "surv_since": sv.get("since") or "", "surv_exit_eta": sv.get("earliest_exit") or "",
            "surv_source": sv.get("source") or "",
            "surv_implication": sv.get("implication") or "", "surv_exit_check": sv.get("exit_check") or "",
            "surv_exit_rule": sv.get("exit_rule") or "",
            "at_ath": bool(r["dd_from_life_high_pct"] >= -2 and days > 10),
            "first_thrust_date": r.get("first_thrust_date"),
            "last_pivot_cross_date": r.get("last_pivot_cross_date"),
            "days_since_pivot_cross": r.get("days_since_pivot_cross"),
            "last_thrust_date": r.get("last_thrust_date"),
            "thrust_count": r.get("thrust_count"),
            "thrust_recent": bool(r.get("thrust_recent")),
            "analogs": analogs,
            "reasons": " • ".join(R[:7]),
        })

    res = pd.DataFrame(out)
    order = {"FRESH BUY": 0, "BUY-SETUP": 1, "RIDE": 2, "WATCH": 3, "EXIT": 4, "AVOID": 5}
    res["rk"] = res["reco"].map(order)
    res = res.sort_values(["rk", "score"], ascending=[True, False]).drop(columns="rk")
    res.to_csv(os.path.join(DATA, "signals.csv"), index=False)
    return res


if __name__ == "__main__":
    s = compute_signals()
    print(s["reco"].value_counts().to_string())
    print(s[s["reco"].isin(["FRESH BUY", "BUY-SETUP"])][
        ["company", "board", "score", "cmp", "pivot", "qib_x", "adv_cr"]].to_string(index=False))
