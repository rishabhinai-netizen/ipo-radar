"""IPO Radar — exit-model re-study.

The complaint that triggered this: the engine trailed out of CP Plus (+280%
lifetime) with +10%. The stated playbook was always 'partial at +15%, trail the
REST' — but the trade engine exited the FULL position on a tight 12% trail with
a 60-session time stop. Winners take ~179 sessions to peak (our own study), so
the old exits systematically amputated the tails.

This grid keeps entries FIXED (the validated pivot-cross rules) and varies only
exits, walk-forward (entries <2025 = train, ≥2025 = test):
  A full-exit variants: trail width 12/20/25%, activation +15/+25%, time 60/120/250
  B runner model: sell 50% at +15%, runner trails X% off peak, NO time stop
Metrics: avg/median P&L, PF, win, hold, and 'tail capture' — P&L earned in the
top-20 lifetime winners (the CP Plus test).
"""
import itertools
import json
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def entries_for(p, d1c, pivot):
    above = p["close"] > pivot
    crosses = list(p.index[(above & ~above.shift(1, fill_value=False)) & (p.index > 0)])
    return crosses


def sim_full(p, ei, cost, trail, act, tstop):
    entry = p["open"].iloc[ei]
    if not np.isfinite(entry) or entry <= 0:
        return None
    peak, armed = entry, False
    end = min(ei + tstop, len(p))
    for j in range(ei, end):
        c = p["close"].iloc[j]
        peak = max(peak, c)
        if c <= entry * 0.92:
            return (c / entry - 1) * 100 - cost, j
        if peak >= entry * (1 + act / 100):
            armed = True
        if armed and c <= peak * (1 - trail / 100):
            return (c / entry - 1) * 100 - cost, j
    j = end - 1
    return (p["close"].iloc[j] / entry - 1) * 100 - cost, j


def sim_runner(p, ei, cost, trail):
    """50% booked at +15%; runner half trails `trail`% off peak, no time stop."""
    entry = p["open"].iloc[ei]
    if not np.isfinite(entry) or entry <= 0:
        return None
    peak, booked = entry, False
    for j in range(ei, len(p)):
        c = p["close"].iloc[j]
        peak = max(peak, c)
        if not booked and c <= entry * 0.92:
            return (c / entry - 1) * 100 - cost, j          # stopped before partial
        if not booked and peak >= entry * 1.15:
            booked = True                                    # half off at +15%
        if booked and c <= peak * (1 - trail / 100):
            runner = (c / entry - 1) * 100
            return 0.5 * 15 + 0.5 * runner - cost, j
    j = len(p) - 1
    c = p["close"].iloc[j]
    if booked:
        return 0.5 * 15 + 0.5 * ((c / entry - 1) * 100) - cost, j   # still running
    return (c / entry - 1) * 100 - cost, j


def run():
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    panel = panel.merge(pref, on=["isin", "exch"]).sort_values("date")
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))
    winners20 = set(ana[ana["trading_days"] >= 60].nlargest(20, "life_high_vs_issue_pct")["isin"])

    # collect fixed entry events once
    events = []
    for _, m in ana.iterrows():
        p = panel[panel["isin"] == m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 5:
            continue
        pivot, d1c = p["high"].iloc[0], p["close"].iloc[0]
        sme = m["board"] == "SME"
        crosses = entries_for(p, d1c, pivot)
        n, busy = 0, -1
        for ci in crosses:
            if n >= 3 or ci > 250 or ci <= busy:
                continue
            if n == 0 and ci > 25:
                continue
            low_td = p["low"].iloc[1:ci].min() if ci > 1 else p["low"].iloc[0]
            if np.isfinite(low_td) and (low_td / d1c - 1) * 100 <= -25:
                continue
            if p["turnover"].iloc[:ci].mean() < 1e7:
                continue
            ei = ci + 1
            if ei >= len(p):
                continue
            events.append((m["isin"], m["listing_date"], sme, p, ei))
            n += 1
            busy = ci + 40   # approximate spacing; exact busy depends on exit model
    print(f"entry events: {len(events)}")

    rows = []
    grids = [("full", t, a, ts) for t, a, ts in itertools.product([12, 20, 25], [15, 25], [60, 120, 250])]
    grids += [("runner", t, None, None) for t in [20, 25, 30]]
    for kind, trail, act, tstop in grids:
        res = {"train": [], "test": [], "tail": 0.0}
        for isin, ld, sme, p, ei in events:
            cost = 1.5 if sme else 1.0
            out = (sim_full(p, ei, cost, trail, act, tstop) if kind == "full"
                   else sim_runner(p, ei, cost, trail))
            if out is None:
                continue
            pnl, _ = out
            (res["train"] if ld < "2025-01-01" else res["test"]).append(pnl)
            if isin in winners20:
                res["tail"] += pnl
        def agg(v):
            if not v:
                return {}
            s = pd.Series(v)
            w = s[s > 0]; l = s[s <= 0]
            return {"n": len(s), "avg": round(s.mean(), 1), "med": round(s.median(), 1),
                    "win": round((s > 0).mean() * 100), 
                    "pf": round(float(w.sum() / abs(l.sum())), 2) if len(l) and l.sum() != 0 else None}
        rows.append({"exit": kind, "trail": trail, "act": act, "tstop": tstop,
                     **{f"tr_{k}": v for k, v in agg(res["train"]).items()},
                     **{f"te_{k}": v for k, v in agg(res["test"]).items()},
                     "tail_capture_pnl": round(res["tail"], 0)})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(DATA, "exit_grid.csv"), index=False)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    run()
