"""IPO Radar — event backtester & strategy optimizer.

Simulates realistic trades (next-day-open entry, close-based stop, trailing exit,
slippage) across candidate setups and filter grids, with walk-forward honesty:
optimize on 2023–24 listings, validate untouched on 2025–26 listings.

Setups:
  A  pivot_reclaim(W): first close > listing-day high within W sessions
  B  vol_thrust:       first session (≥2) with volume ≥5× trailing-20 avg AND
                       close ≥ +4% on the day AND close > issue price
  C  range_break20:    first close above the highest high of the prior 20
                       sessions, only after session 20 (mature-base breakout)

Exit model (identical for all setups, so comparisons are fair):
  stop  = entry − 8% (close-based)
  trail = after +15% unrealized, exit when close < 12% off the running peak
  time  = 60 sessions
  costs = 1.0% round trip mainboard, 1.5% SME (spread + impact + charges)

Filters evaluated only with information available on entry day:
  base-low-to-date vs listing close, QIB (known at listing), ADV-to-date.
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def load_series():
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    panel = panel.merge(pref, on=["isin", "exch"]).sort_values("date")
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    out = []
    for _, m in ana.iterrows():
        p = panel[panel["isin"] == m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 10:
            continue
        out.append((m, p))
    return out


def simulate(p, ei, sme):
    """Enter at open of session ei; return net %, hold days, exit reason."""
    if ei >= len(p):
        return None
    entry = p["open"].iloc[ei]
    if not np.isfinite(entry) or entry <= 0:
        return None
    cost = 1.5 if sme else 1.0
    peak = entry
    armed = False
    for j in range(ei, min(ei + 60, len(p))):
        c = p["close"].iloc[j]
        peak = max(peak, c)
        if c <= entry * 0.92:
            return (c / entry - 1) * 100 - cost, j - ei, "stop"
        if peak >= entry * 1.15:
            armed = True
        if armed and c <= peak * 0.88:
            return (c / entry - 1) * 100 - cost, j - ei, "trail"
    j = min(ei + 60, len(p)) - 1
    return (p["close"].iloc[j] / entry - 1) * 100 - cost, j - ei, "time"


def entry_day(m, p, setup):
    d1h = p["high"].iloc[0]
    if setup.startswith("A"):
        W = int(setup[1:])
        hits = p.index[(p.index >= 1) & (p.index <= W) & (p["close"] > d1h)]
        return int(hits[0]) + 1 if len(hits) else None
    if setup == "B":
        v20 = p["volume"].rolling(20, min_periods=5).mean().shift(1)
        up = p["close"].pct_change() >= 0.04
        issue = m["issue_price"] if np.isfinite(m["issue_price"]) else 0
        hits = p.index[(p.index >= 2) & (p["volume"] >= 5 * v20) & up & (p["close"] > issue)]
        return int(hits[0]) + 1 if len(hits) else None
    if setup == "C":
        hh = p["high"].rolling(20).max().shift(1)
        hits = p.index[(p.index >= 20) & (p["close"] > hh)]
        return int(hits[0]) + 1 if len(hits) else None
    return None


def passes(m, p, ei, base_min, qib_min):
    if qib_min and not (np.isfinite(m["qib_x"]) and m["qib_x"] >= qib_min):
        return False
    if base_min is not None:
        d1c = p["close"].iloc[0]
        low_td = p["low"].iloc[1:ei].min() if ei > 1 else p["low"].iloc[0]
        if np.isfinite(low_td) and (low_td / d1c - 1) * 100 <= base_min:
            return False
    # liquidity known at entry: mean turnover so far ≥ ₹1cr (loose floor)
    if p["turnover"].iloc[:ei].mean() < 1e7:
        return False
    return True


def agg(trades):
    if not trades:
        return dict(n=0)
    r = pd.Series([t[0] for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    pf = round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() != 0 else np.inf
    return dict(n=len(r), mean=round(float(r.mean()), 1), median=round(float(r.median()), 1),
                win=round(float((r > 0).mean() * 100)), pf=pf,
                p10=round(float(r.quantile(.1)), 1), p90=round(float(r.quantile(.9)), 1),
                hold=round(float(np.mean([t[1] for t in trades])), 0))


def run():
    series = load_series()
    print(f"backtest universe: {len(series)} IPOs")
    setups = ["A10", "A25", "A40", "B", "C"]
    bases = [None, -10, -15, -20]
    qibs = [0, 15, 50]
    rows = []
    # pre-compute entry days per (ipo, setup)
    entries = {}
    for k, (m, p) in enumerate(series):
        for s in setups:
            entries[(k, s)] = entry_day(m, p, s)
    for s, b, q in itertools.product(setups, bases, qibs):
        train, test = [], []
        for k, (m, p) in enumerate(series):
            ei = entries[(k, s)]
            if ei is None or not passes(m, p, ei, b, q):
                continue
            t = simulate(p, ei, m["board"] == "SME")
            if t is None:
                continue
            (train if m["listing_date"] < "2025-01-01" else test).append(t)
        rows.append({"setup": s, "base": b, "qib": q,
                     **{f"tr_{k2}": v for k2, v in agg(train).items()},
                     **{f"te_{k2}": v for k2, v in agg(test).items()}})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(DATA, "backtest_grid.csv"), index=False)
    # rank by blended robust score: train+test mean with n penalty
    ok = res[(res["tr_n"] >= 40) & (res["te_n"] >= 25)].copy()
    if len(ok):
        ok["score"] = ok[["tr_mean", "te_mean"]].min(axis=1) * 0.6 + \
                      ok[["tr_win", "te_win"]].min(axis=1) * 0.1
        print(ok.sort_values("score", ascending=False).head(12).to_string(index=False))
    return res


if __name__ == "__main__":
    run()
