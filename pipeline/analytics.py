"""IPO Radar — per-IPO analytics from the price panel (bhavcopy)."""
import json
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def run():
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    master = json.load(open(os.path.join(DATA, "master_ipo.json")))

    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    panel = panel.merge(pref, on=["isin", "exch"]).sort_values("date")

    out, ev30, ev90 = [], [], []
    for m in master:
        df = panel[panel["isin"] == m.get("isin")].reset_index(drop=True)
        if df.empty or not m.get("listing_date"):
            continue
        df = df[df["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if df.empty:
            continue
        d1 = df.iloc[0]
        issue = m["issue_price"]
        r = dict(m)
        r.update({
            "exchange": d1["exch"], "symbol": d1["symbol"],
            "d1_open": d1["open"], "d1_high": d1["high"], "d1_low": d1["low"],
            "d1_close": d1["close"], "trading_days": len(df),
            "cmp_bhav": df["close"].iloc[-1],
            "life_high": df["high"].max(), "life_low": df["low"].min(),
            "life_high_date": df.loc[df["high"].idxmax(), "date"].date().isoformat(),
            "life_low_date": df.loc[df["low"].idxmin(), "date"].date().isoformat(),
            "days_to_high": int(df["high"].idxmax()),
            "avg_turnover_cr_20d": df["turnover"].tail(20).mean() / 1e7,
        })
        if issue:
            r["open_pop_pct"] = round((d1["open"] / issue - 1) * 100, 2)
            r["d1_close_vs_issue_pct"] = round((d1["close"] / issue - 1) * 100, 2)
            r["cmp_vs_issue_pct"] = round((df["close"].iloc[-1] / issue - 1) * 100, 2)
            r["life_high_vs_issue_pct"] = round((df["high"].max() / issue - 1) * 100, 2)
            r["life_low_vs_issue_pct"] = round((df["low"].min() / issue - 1) * 100, 2)
        r["cmp_vs_d1close_pct"] = round((df["close"].iloc[-1] / d1["close"] - 1) * 100, 2)
        r["dd_from_life_high_pct"] = round((df["close"].iloc[-1] / df["high"].max() - 1) * 100, 2)
        r["max_dd_pct"] = round(((df["close"] / df["close"].cummax()) - 1).min() * 100, 2)
        base = df.iloc[1:31]
        if len(base) >= 10:
            r["base30_low_vs_d1close_pct"] = round((base["low"].min() / d1["close"] - 1) * 100, 2)
            r["base30_range_pct"] = round((base["high"].max() - base["low"].min()) / d1["close"] * 100, 2)
        post = df.iloc[1:]
        bo = post[post["close"] > d1["high"]]
        if len(bo):
            bi = bo.index[0]
            r["d1high_breakout_day"] = int(bi)
            r["d1high_breakout_date"] = df.loc[bi, "date"].date().isoformat()
            bo_close = df.loc[bi, "close"]
            for h in (10, 20, 60):
                if bi + h < len(df):
                    r[f"ret_{h}d_after_breakout_pct"] = round((df.loc[bi + h, "close"] / bo_close - 1) * 100, 2)
            v10 = df.loc[max(0, bi - 10):bi - 1, "volume"].mean()
            r["breakout_vol_x"] = round(df.loc[bi, "volume"] / v10, 2) if v10 else None
        else:
            r["d1high_breakout_day"] = None
        for key, store in (("anchor_lockin_30d", ev30), ("anchor_lockin_90d", ev90)):
            v = m.get(key)
            if v:
                idx = df.index[df["date"] >= pd.Timestamp(v)]
                if len(idx) and idx[0] >= 5 and idx[0] + 10 < len(df):
                    i0 = idx[0]
                    store.append({"isin": m["isin"],
                                  "pre5_to_exp_pct": (df.loc[i0, "close"] / df.loc[i0 - 5, "close"] - 1) * 100,
                                  "exp_to_post10_pct": (df.loc[i0 + 10, "close"] / df.loc[i0, "close"] - 1) * 100})
        out.append(r)

    res = pd.DataFrame(out)
    res.to_csv(os.path.join(DATA, "ipo_analytics.csv"), index=False)
    pd.DataFrame(ev30).to_csv(os.path.join(DATA, "event_lockin30.csv"), index=False)
    pd.DataFrame(ev90).to_csv(os.path.join(DATA, "event_lockin90.csv"), index=False)
    print(f"analytics: {len(res)} IPOs")
    return res


if __name__ == "__main__":
    run()
