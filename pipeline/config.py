"""IPO Radar — global configuration."""
UNIVERSE_START = "2023-07-01"   # track every IPO listed on/after this date
CHITT_STOP = "2023-05-01"       # stop paging Chittorgarh reports before this open date

# quality gates (Stage-1 study, 384 IPOs Jul-25→Jul-26; re-validated on 3y backfill)
QIB_MIN = 15          # scoring input only — NOT a hard gate (backtest-validated)
SUB_MIN = 20          # total subscription fallback when QIB absent (SME)
BASE_MIN_PCT = -10    # first-30-session low vs listing close (walk-forward optimum)
ADV_MIN_MAIN = 5.0    # ₹cr avg daily turnover, mainboard
ADV_MIN_SME = 2.0     # ₹cr, SME
POP_MIN, POP_MAX = 0, 50   # listing-day open premium band
BREAKOUT_WINDOW = 25  # sessions within which pivot must be reclaimed
HARD_STOP_PCT = -8    # O'Neil hard stop from entry
TARGET1_PCT = 15      # first target / trail activation
TIME_STOP = 60        # sessions
