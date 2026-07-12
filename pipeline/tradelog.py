"""IPO Radar — transparent trade log.

Replays the EXACT live strategy over every IPO's full history and records every
trade the system would have taken — entry, stop, target, exit, P&L — so the user
can audit the strategy stock by stock (e.g. every Aditya Infotech trade).

Rules (identical to the validated walk-forward engine):
  ENTRY  — (a) first daily close above the listing-day high (pivot) within 25
           sessions of listing, or (b) LATE BLOOMER: first cross day 26–120
           with cross-day volume ≥2.5× its 20-day average (added after the
           missed-winners autopsy: 59 of 85 missed multibaggers — Ather class —
           crossed late; with stops these entries ran PF 3.05).
           Base low-to-date > −25%, mean turnover ≥ ₹1cr. Fill at next open.
  RE-ENTRY — after an exit, a fresh upward cross of the pivot re-arms the
           system (max 3 trades per stock, within the first 250 sessions).
  STOP   — entry −8% (close basis).
  TRAIL  — after +15% unrealized, exit when close falls 30% off the peak.
  TIME   — 120 sessions, but ONLY for unproven trades: if the trade is up ≥30%
           at day 120 it is never time-stopped — proven winners trail until
           they break (the CP Plus fix: no more selling a +229% run at +36%).
  COSTS  — 1.0% round trip mainboard, 1.5% SME.
Open trades (still running today) are marked OPEN with mark-to-market P&L.
"""
import json
import os

import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
MAX_TRADES = 3


def run():
    panel = pd.read_parquet(os.path.join(DATA, "prices_panel.parquet"))
    pref = panel.groupby(["isin", "exch"])["turnover"].median().reset_index()
    pref = pref.sort_values("turnover", ascending=False).drop_duplicates("isin")[["isin", "exch"]]
    panel = panel.merge(pref, on=["isin", "exch"]).sort_values("date")
    ana = pd.read_csv(os.path.join(DATA, "ipo_analytics.csv"))

    trades = []
    for _, m in ana.iterrows():
        p = panel[panel["isin"] == m["isin"]].reset_index(drop=True)
        p = p[p["date"] >= pd.Timestamp(m["listing_date"])].reset_index(drop=True)
        if len(p) < 5:
            continue
        pivot = p["high"].iloc[0]
        d1c = p["close"].iloc[0]
        sme = m["board"] == "SME"
        cost = 1.5 if sme else 1.0
        above = p["close"] > pivot
        crosses = list(p.index[(above & ~above.shift(1, fill_value=False)) & (p.index > 0)])
        n_done = 0
        busy_until = -1
        v20 = p["volume"].rolling(20, min_periods=5).mean().shift(1)
        for ci in crosses:
            if n_done >= MAX_TRADES or ci > 250 or ci <= busy_until:
                continue
            late = ci > 25 and n_done == 0
            if n_done == 0 and ci > 25:      # late FIRST entry: only with the volume thrust
                if ci > 120 or not (np.isfinite(v20.iloc[ci]) and
                                    p["volume"].iloc[ci] >= 2.5 * v20.iloc[ci]):
                    continue
            low_td = p["low"].iloc[1:ci].min() if ci > 1 else p["low"].iloc[0]
            if np.isfinite(low_td) and (low_td / d1c - 1) * 100 <= -25:
                continue                      # broken base — system stands aside
            if p["turnover"].iloc[:ci].mean() < 1e7:
                continue                      # illiquid at signal time
            ei = ci + 1
            if ei >= len(p):
                continue
            entry = p["open"].iloc[ei]
            if not np.isfinite(entry) or entry <= 0:
                continue
            stop_px, target_px = entry * 0.92, entry * 1.15
            peak, armed = entry, False
            exit_i, exit_px, reason = None, None, None
            for j in range(ei, len(p)):
                c = p["close"].iloc[j]
                peak = max(peak, c)
                if c <= stop_px:
                    exit_i, exit_px, reason = j, c, "stop -8%"
                    break
                if peak >= target_px:
                    armed = True
                if armed and c <= peak * 0.70:
                    exit_i, exit_px, reason = j, c, "trail (30% off peak after +15%)"
                    break
                if j - ei >= 120 and (c / entry - 1) * 100 < 30:
                    exit_i, exit_px, reason = j, c, "time (120 sessions, unproven)"
                    break
            if exit_i is None:
                j = len(p) - 1
                exit_i, exit_px, reason = j, p["close"].iloc[j], "OPEN"
            pnl = (exit_px / entry - 1) * 100 - (0 if reason == "OPEN" else cost)
            trades.append({
                "company": m["company"], "board": m["board"], "symbol": m["symbol"],
                "isin": m["isin"], "trade_no": n_done + 1,
                "entry_type": "late bloomer (vol-confirmed)" if late else "early pivot reclaim",
                "signal_date": p["date"].iloc[ci].date().isoformat(),
                "entry_date": p["date"].iloc[ei].date().isoformat(),
                "entry": round(entry, 2), "stop": round(stop_px, 2),
                "target1": round(target_px, 2),
                "exit_date": p["date"].iloc[exit_i].date().isoformat(),
                "exit_price": round(exit_px, 2), "exit_reason": reason,
                "hold_sessions": exit_i - ei,
                "pnl_pct": round(pnl, 2),
                "peak_gain_pct": round((peak / entry - 1) * 100, 1),
            })
            n_done += 1
            busy_until = exit_i

    log = pd.DataFrame(trades).sort_values("entry_date")
    log.to_csv(os.path.join(DATA, "trade_log.csv"), index=False)
    closed = log[log["exit_reason"] != "OPEN"]
    allt = log  # open trades carry mark-to-market P&L
    wins, losses = closed[closed["pnl_pct"] > 0], closed[closed["pnl_pct"] <= 0]
    eq = closed.sort_values("exit_date")["pnl_pct"].cumsum()
    stats = {
        "n_trades": int(len(log)), "n_closed": int(len(closed)), "n_open": int((log["exit_reason"] == "OPEN").sum()),
        "win_rate": round(float((closed["pnl_pct"] > 0).mean() * 100), 1) if len(closed) else None,
        "avg_pnl": round(float(closed["pnl_pct"].mean()), 2) if len(closed) else None,
        "median_pnl": round(float(closed["pnl_pct"].median()), 2) if len(closed) else None,
        "profit_factor": round(float(wins["pnl_pct"].sum() / abs(losses["pnl_pct"].sum())), 2) if len(losses) else None,
        "avg_win": round(float(wins["pnl_pct"].mean()), 1) if len(wins) else None,
        "avg_loss": round(float(losses["pnl_pct"].mean()), 1) if len(losses) else None,
        "best": {"company": closed.loc[closed["pnl_pct"].idxmax(), "company"],
                 "pnl": float(closed["pnl_pct"].max())} if len(closed) else None,
        "worst": {"company": closed.loc[closed["pnl_pct"].idxmin(), "company"],
                  "pnl": float(closed["pnl_pct"].min())} if len(closed) else None,
        "avg_hold": round(float(closed["hold_sessions"].mean()), 0) if len(closed) else None,
        "sum_pnl_pct": round(float(closed["pnl_pct"].sum()), 0),
        "avg_pnl_incl_open": round(float(allt["pnl_pct"].mean()), 2),
        "open_mtm_pnl_sum": round(float(log.loc[log["exit_reason"] == "OPEN", "pnl_pct"].sum()), 0),
        "by_year": {str(y): {"n": int(len(g)), "win": round(float((g["pnl_pct"] > 0).mean() * 100)),
                             "avg": round(float(g["pnl_pct"].mean()), 1),
                             "open": int((g["exit_reason"] == "OPEN").sum())}
                    for y, g in allt.groupby(allt["entry_date"].str[:4])},
    }
    json.dump(stats, open(os.path.join(DATA, "trade_stats.json"), "w"), indent=1)
    print(f"trade log: {stats['n_trades']} trades ({stats['n_open']} open) | "
          f"win {stats['win_rate']}% | avg {stats['avg_pnl']}% | PF {stats['profit_factor']}")
    return log, stats


if __name__ == "__main__":
    run()
