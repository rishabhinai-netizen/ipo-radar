# 🎯 IPO Radar

Tracks **every NSE + BSE IPO (mainboard + SME) listed in the last 12 months** and signals
entries using the **Pivot Reclaim** strategy validated in the Stage-1 study of 384 IPOs
(Jul-2025 → Jul-2026).

## The strategy in one line
Buy the first daily close above the **listing-day high** within 25 sessions of listing, in
names with QIB ≥ 15x, a base that held above −15%, and real liquidity — stop at the base low
(max −8%), trail after +15%, out by 60 sessions or before the 90-day anchor lock-in.

Cohort study (returns 60d after breakout, no stops): +8.8% median / 62% win. The **tradable replay
with stops and costs** is different: PF ~1.5, ~23% win, −10% median trade — a tail system where a few
big runners pay for many small stops. Realized edge concentrated in SME. Treat as hypothesis.

## Architecture
- `pipeline/refresh.py` — daily job: Chittorgarh reports (new IPOs, subscription, anchor
  lock-ins) + lead-manager scrape + incremental NSE/BSE bhavcopy → rebuilds analytics & signals
- `pipeline/analytics.py` — per-IPO metrics (pivot, base depth, breakout day, drawdowns, ADV)
- `pipeline/signals.py` — TRIGGER / SETUP / RIDE / AVOID / NEUTRAL with plain-language reasons
  and Entry/Stop/Target/R:R
- `app.py` — Streamlit dashboard
- `.github/workflows/daily.yml` — cron 7:45 pm IST, commits refreshed `data/`

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py          # dashboard
python pipeline/refresh.py    # manual data refresh
```

## Deploy on Streamlit Cloud
1. share.streamlit.io → New app → select this repo, `app.py`
2. The app redeploys automatically whenever the daily Action commits fresh data.

## Data sources
NSE & BSE official bhavcopy archives (prices/volumes) · Chittorgarh cloud reports 125/21/156/19
(issue, subscription, anchor lock-ins, lead managers). Cross-verified: CMP 100% agreement,
listing close 99.5%.

Known gaps: live GMP (client-side rendered at source — planned via browser module),
shares outstanding / true market cap (planned via Screener.in).

*Research tool. Not investment advice.*
