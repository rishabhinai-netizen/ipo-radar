"""Missed-winners autopsy + late-bloomer entry test (the Ather question)."""
import json, os
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")

def sim_hybrid(p, ei, cost, trail=30, g_keep=30):
    entry = p["open"].iloc[ei]
    if not np.isfinite(entry) or entry <= 0: return None
    peak, armed = entry, False
    for j in range(ei, len(p)):
        c = p["close"].iloc[j]; peak = max(peak, c)
        if c <= entry * 0.92: return (c/entry-1)*100 - cost, j
        if peak >= entry * 1.15: armed = True
        if armed and c <= peak * (1 - trail/100): return (c/entry-1)*100 - cost, j
        if j - ei >= 120 and (c/entry-1)*100 < g_keep: return (c/entry-1)*100 - cost, j
    return (p["close"].iloc[-1]/entry-1)*100 - cost, len(p)-1

def run():
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    pref = panel.groupby(["isin","exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin","exch"]]
    panel = panel.merge(pref, on=["isin","exch"]).sort_values("date")
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    tlog = pd.read_csv(os.path.join(DATA, "trade_log.csv"))
    traded = set(tlog["isin"])

    # 1) AUTOPSY: big winners (peak ≥ +100% vs issue) with NO trade — why?
    win = ana[(ana["life_high_vs_issue_pct"] >= 100) & (ana["trading_days"] >= 60)]
    rows = []
    for _, m in win.iterrows():
        if m["isin"] in traded: continue
        p = panel[panel["isin"]==m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 10: continue
        pivot, d1c = p["high"].iloc[0], p["close"].iloc[0]
        above = p["close"] > pivot
        crosses = list(p.index[(above & ~above.shift(1, fill_value=False)) & (p.index > 0)])
        if not crosses: reason = "never closed above pivot (pure grinder)"
        elif crosses[0] > 25:
            low_td = p["low"].iloc[1:crosses[0]].min()
            reason = f"first cross too late (day {crosses[0]})"
        else:
            ci = crosses[0]
            low_td = p["low"].iloc[1:ci].min() if ci > 1 else p["low"].iloc[0]
            if (low_td/d1c-1)*100 <= -25: reason = "base broke -25% before cross"
            elif p["turnover"].iloc[:ci].mean() < 1e7: reason = "illiquid at signal (<₹1cr/day)"
            else: reason = "other"
        rows.append({"company": m["company"], "board": m["board"], "listing_date": m["listing_date"],
                     "peak_vs_issue_pct": m["life_high_vs_issue_pct"], "now_vs_issue_pct": m["cmp_vs_issue_pct"],
                     "reason_missed": reason})
    missed = pd.DataFrame(rows).sort_values("peak_vs_issue_pct", ascending=False)
    missed.to_csv(os.path.join(DATA, "missed_winners.csv"), index=False)
    print("missed big winners:", len(missed))
    print(missed["reason_missed"].str.replace(r"day \d+", "day >25", regex=True).value_counts().to_string())

    # 2) LATE-BLOOMER TEST: first cross day 26-120 — worth trading? with/without volume confirm
    res = {"late_all": [], "late_vol": []}
    for _, m in ana.iterrows():
        p = panel[panel["isin"]==m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 30: continue
        pivot, d1c = p["high"].iloc[0], p["close"].iloc[0]
        sme = m["board"] == "SME"; cost = 1.5 if sme else 1.0
        above = p["close"] > pivot
        crosses = list(p.index[(above & ~above.shift(1, fill_value=False)) & (p.index > 0)])
        if not crosses or crosses[0] <= 25 or crosses[0] > 120: continue
        ci = crosses[0]
        if p["turnover"].iloc[:ci].mean() < 1e7: continue
        ei = ci + 1
        if ei >= len(p): continue
        out = sim_hybrid(p, ei, cost)
        if out is None: continue
        res["late_all"].append(out[0])
        v20 = p["volume"].iloc[max(0,ci-20):ci].mean()
        if v20 and p["volume"].iloc[ci] >= 2.5 * v20:
            res["late_vol"].append(out[0])
    for k, v in res.items():
        if v:
            s = pd.Series(v); w=s[s>0]; l=s[s<=0]
            pf = round(float(w.sum()/abs(l.sum())),2) if len(l) and l.sum()!=0 else None
            print(f"{k}: n={len(s)} avg={s.mean():.1f} med={s.median():.1f} win={(s>0).mean()*100:.0f}% pf={pf}")
    return missed

if __name__ == "__main__":
    run()
