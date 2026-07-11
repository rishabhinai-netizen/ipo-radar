"""IPO Radar — the research layer, recomputed daily so nothing goes stale.

Produces:
  study_stats.json   — headline stats (breakout edge, QIB quartiles, lock-ins,
                       open-pop buckets, liquidity, winner traits, monthly regime,
                       year-cohort stability of the rule)
  rule_ladder.csv    — filter-by-filter expectancy of the Pivot Reclaim rule
  lm_scorecard.csv   — lead managers judged on what happens AFTER listing:
                       median now-vs-issue, max drawdown, % above issue, pivot
                       reclaim rate, post-breakout returns — not just listing pops
  winners.json       — Winners Lab: top performers with volume signatures,
                       consistency metrics and pattern classification
"""
import json
import os

import numpy as np
import pandas as pd

import config

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def _stats_block(g):
    r20 = g["ret_20d_after_breakout_pct"].dropna()
    r60 = g["ret_60d_after_breakout_pct"].dropna()
    return {"n": int(len(g)),
            "r20_med": round(float(r20.median()), 1) if len(r20) else None,
            "r20_win": round(float((r20 > 0).mean() * 100)) if len(r20) else None,
            "r60_med": round(float(r60.median()), 1) if len(r60) else None,
            "r60_win": round(float((r60 > 0).mean() * 100)) if len(r60) else None,
            "r60_mean": round(float(r60.mean()), 1) if len(r60) else None,
            "r60_p90": round(float(r60.quantile(.9)), 1) if len(r60) else None}


def rule_ladder(df):
    bo = df[df["d1high_breakout_day"].notna()]
    lad = []
    lad.append({"rule": "ALL pivot breakouts", **_stats_block(bo)})
    c1 = bo[bo["d1high_breakout_day"] <= config.BREAKOUT_WINDOW]
    lad.append({"rule": f"breakout ≤{config.BREAKOUT_WINDOW} sessions", **_stats_block(c1)})
    c2 = c1[c1["base30_low_vs_d1close_pct"] > config.BASE_MIN_PCT]
    lad.append({"rule": f"+ base low > {config.BASE_MIN_PCT}%", **_stats_block(c2)})
    c3 = c2[c2["qib_x"].fillna(0) >= config.QIB_MIN]
    lad.append({"rule": f"+ QIB ≥ {config.QIB_MIN}x", **_stats_block(c3)})
    lad.append({"rule": "composite — SME only", **_stats_block(c3[c3["board"] == "SME"])})
    lad.append({"rule": "composite — mainboard only", **_stats_block(c3[c3["board"] == "Mainboard"])})
    # stability by listing-year cohort
    for y, g in c3.groupby(pd.to_datetime(c3["listing_date"]).dt.year):
        lad.append({"rule": f"composite — {y} listings", **_stats_block(g)})
    return pd.DataFrame(lad), c3


def lm_scorecard(df, lm_map):
    rows = []
    df = df.copy()
    df["lm"] = df["chittorgarh_id"].astype(str).map(
        lambda c: (lm_map.get(c) or ["Unknown"])[0])
    for lm, g in df.groupby("lm"):
        if len(g) < 3 or lm == "Unknown":
            continue
        broke = g["d1high_breakout_day"].notna() & (g["d1high_breakout_day"] <= config.BREAKOUT_WINDOW)
        r60 = g.loc[broke, "ret_60d_after_breakout_pct"].dropna()
        rows.append({
            "lead_manager": lm, "issues": int(len(g)),
            "mainboard": int((g["board"] == "Mainboard").sum()),
            "sme": int((g["board"] == "SME").sum()),
            "median_listing_gain_pct": round(float(g["d1_close_vs_issue_pct"].median()), 1),
            "median_now_vs_issue_pct": round(float(g["cmp_vs_issue_pct"].median()), 1),
            "pct_above_issue_today": round(float((g["cmp_vs_issue_pct"] > 0).mean() * 100)),
            "median_max_dd_pct": round(float(g["max_dd_pct"].median()), 1),
            "median_peak_vs_issue_pct": round(float(g["life_high_vs_issue_pct"].median()), 1),
            "pivot_reclaim_rate_pct": round(float(broke.mean() * 100)),
            "median_r60_after_breakout_pct": round(float(r60.median()), 1) if len(r60) else None,
            "median_qib_x": round(float(g["qib_x"].median()), 1) if g["qib_x"].notna().any() else None,
            "median_adv_cr": round(float(g["avg_turnover_cr_20d"].median()), 2),
        })
    sc = pd.DataFrame(rows)
    if len(sc):
        # composite LM quality score: post-listing outcomes, not listing pops
        sc["lm_score"] = (
            sc["median_now_vs_issue_pct"].rank(pct=True) * 35 +
            sc["pct_above_issue_today"].rank(pct=True) * 25 +
            sc["pivot_reclaim_rate_pct"].rank(pct=True) * 20 +
            (-sc["median_max_dd_pct"]).rank(pct=True, ascending=False) * 20
        ).round(0)
        sc = sc.sort_values(["lm_score", "issues"], ascending=False)
    return sc


def winners_lab(df, panel):
    """Deep-dive the big winners: what did they look like, and when could you know?"""
    seasoned = df[df["trading_days"] >= 60].copy()
    top = seasoned.nlargest(30, "cmp_vs_issue_pct")
    peak = seasoned.nlargest(30, "life_high_vs_issue_pct")
    ids = pd.concat([top, peak]).drop_duplicates("isin")

    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    panel = panel.merge(pref, on=["isin", "exch"]).sort_values("date")

    out = []
    for _, m in ids.iterrows():
        p = panel[panel["isin"] == m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 30:
            continue
        d1c = p["close"].iloc[0]
        # abnormal-volume signature: first day (after day 5) with volume ≥5x trailing 20d avg
        vol20 = p["volume"].rolling(20, min_periods=5).mean().shift(1)
        spikes = p.index[(p["volume"] >= 5 * vol20) & (p.index > 5)]
        first_spike = int(spikes[0]) if len(spikes) else None
        spike_ret60 = None
        if first_spike is not None and first_spike + 60 < len(p):
            spike_ret60 = round(float(p["close"].iloc[first_spike + 60] /
                                      p["close"].iloc[first_spike] - 1) * 100, 1)
        # consistency: % positive weeks
        wk = p.set_index("date")["close"].resample("W").last().pct_change().dropna()
        green_weeks = round(float((wk > 0).mean() * 100)) if len(wk) else None
        # pattern classification
        bo_day = m["d1high_breakout_day"]
        if pd.notna(bo_day) and bo_day <= 25 and (m.get("base30_low_vs_d1close_pct") or -99) > -15:
            pattern = "Pivot Reclaim (textbook)"
        elif pd.notna(bo_day) and bo_day <= 25:
            pattern = "Early breakout, deep base"
        elif pd.notna(bo_day):
            pattern = "Late-bloomer breakout"
        else:
            pattern = "Never above pivot (grind)"
        if green_weeks and green_weeks >= 55 and (m["max_dd_pct"] or -99) > -30:
            pattern += " · steady compounder"
        if first_spike is not None:
            pattern += " · volume-thrust"
        out.append({
            "company": m["company"], "board": m["board"], "symbol": m["symbol"],
            "isin": m["isin"], "listing_date": m["listing_date"],
            "issue_price": m["issue_price"], "cmp": m["cmp_bhav"],
            "now_vs_issue_pct": m["cmp_vs_issue_pct"],
            "peak_vs_issue_pct": m["life_high_vs_issue_pct"],
            "days_to_peak": int(m["days_to_high"]),
            "max_dd_pct": m["max_dd_pct"],
            "qib_x": m["qib_x"], "sub_x": m["subscription_total_x"],
            "d1_gain_pct": m["d1_close_vs_issue_pct"],
            "breakout_day": None if pd.isna(bo_day) else int(bo_day),
            "base30_low_pct": m.get("base30_low_vs_d1close_pct"),
            "first_vol_spike_day": first_spike,
            "ret60_after_vol_spike_pct": spike_ret60,
            "green_weeks_pct": green_weeks,
            "pattern": pattern,
        })
    res = pd.DataFrame(out).sort_values("now_vs_issue_pct", ascending=False)

    # aggregate lessons
    lessons = {}
    if len(res):
        lessons = {
            "n_winners": int(len(res)),
            "pct_reclaimed_pivot_within25": round(float(
                (res["breakout_day"].notna() & (res["breakout_day"] <= 25)).mean() * 100)),
            "median_days_to_peak": float(res["days_to_peak"].median()),
            "median_qib": float(res["qib_x"].median()) if res["qib_x"].notna().any() else None,
            "pct_with_volume_thrust": round(float(res["first_vol_spike_day"].notna().mean() * 100)),
            "median_ret60_after_spike": (float(res["ret60_after_vol_spike_pct"].dropna().median())
                                         if res["ret60_after_vol_spike_pct"].notna().any() else None),
            "median_green_weeks": float(res["green_weeks_pct"].median()),
            "median_max_dd": float(res["max_dd_pct"].median()),
        }
    return res, lessons


def run():
    df = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    lm_map = json.load(open(os.path.join(DATA, "lm_map.json")))

    S = {"universe_start": config.UNIVERSE_START, "n_ipos": int(len(df)),
         "n_mainboard": int((df["board"] == "Mainboard").sum()),
         "n_sme": int((df["board"] == "SME").sum()),
         "as_of": str(pd.to_datetime(panel["date"]).max().date())}

    ladder, _ = rule_ladder(df)
    ladder.to_csv(os.path.join(DATA, "rule_ladder.csv"), index=False)

    bo = df[df["d1high_breakout_day"].notna()]
    nb = df[df["d1high_breakout_day"].isna() & (df["trading_days"] > 25)]
    S["never_broke"] = {"n": int(len(nb)),
                        "cmp_vs_d1close_median": round(float(nb["cmp_vs_d1close_pct"].median()), 1)}

    q = df[df["qib_x"].notna() & (df["trading_days"] > 60)].copy()
    if len(q) > 20:
        q["qib_bucket"] = pd.qcut(q["qib_x"], 4, labels=["Q1_low", "Q2", "Q3", "Q4_high"])
        S["qib_quartiles"] = q.groupby("qib_bucket", observed=True)[
            ["d1_close_vs_issue_pct", "cmp_vs_d1close_pct", "life_high_vs_issue_pct"]
        ].median().round(1).to_dict()

    for tag in ("30", "90"):
        f = os.path.join(DATA, f"event_lockin{tag}.csv")
        if os.path.exists(f):
            e = pd.read_csv(f)
            if len(e):
                S[f"lockin{tag}"] = {
                    "n": int(len(e)),
                    "pre5_median": round(float(e["pre5_to_exp_pct"].median()), 2),
                    "post10_median": round(float(e["exp_to_post10_pct"].median()), 2),
                    "post10_win": round(float((e["exp_to_post10_pct"] > 0).mean() * 100), 1)}

    d = df[df["open_pop_pct"].notna() & (df["trading_days"] > 60)].copy()
    d["pop_bucket"] = pd.cut(d["open_pop_pct"], [-100, -5, 5, 25, 50, 1000],
                             labels=["disc<-5", "flat", "pop5-25", "pop25-50", "pop>50"])
    S["open_pop"] = d.groupby("pop_bucket", observed=True)[
        ["cmp_vs_d1close_pct", "max_dd_pct", "life_high_vs_issue_pct"]].median().round(1).to_dict()

    df["liquid"] = df["avg_turnover_cr_20d"] >= config.ADV_MIN_MAIN
    S["liquidity"] = {
        "n_liquid": int(df["liquid"].sum()),
        "liquid_cmp_vs_d1close": round(float(df[df["liquid"]]["cmp_vs_d1close_pct"].median()), 1),
        "illiquid_cmp_vs_d1close": round(float(df[~df["liquid"]]["cmp_vs_d1close_pct"].median()), 1)}

    w = df[df["trading_days"] >= 90]
    if len(w) > 40:
        thr = w["life_high_vs_issue_pct"].quantile(0.75)
        S["winner_threshold_pct"] = round(float(thr), 1)
        for name, g in (("winners", w[w["life_high_vs_issue_pct"] >= thr]),
                        ("rest", w[w["life_high_vs_issue_pct"] < thr])):
            S[f"traits_{name}"] = {
                "n": int(len(g)),
                "qib_median": round(float(g["qib_x"].median()), 1),
                "sub_total_median": round(float(g["subscription_total_x"].median()), 1),
                "d1close_vs_issue_median": round(float(g["d1_close_vs_issue_pct"].median()), 1),
                "days_to_high_median": float(g["days_to_high"].median()),
                "base30_low_median": round(float(g["base30_low_vs_d1close_pct"].median()), 1)}

    df["month"] = df["listing_date"].str[:7]
    S["monthly_d1"] = {k: round(float(v), 1) for k, v in
                       df.groupby("month")["d1_close_vs_issue_pct"].median().items()}

    sc = lm_scorecard(df, lm_map)
    sc.to_csv(os.path.join(DATA, "lm_scorecard.csv"), index=False)

    winners, lessons = winners_lab(df, panel)
    winners.to_csv(os.path.join(DATA, "winners.csv"), index=False)
    S["winner_lessons"] = lessons

    json.dump(S, open(os.path.join(DATA, "study_stats.json"), "w"), indent=1)
    print(f"study: ladder {len(ladder)} rows, LM scorecard {len(sc)}, winners {len(winners)}")
    return S


if __name__ == "__main__":
    run()
