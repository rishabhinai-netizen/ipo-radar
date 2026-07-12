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
TRAIL_ARM_PCT = 15    # unrealized gain that ARMS the trailing stop
TRAIL_PCT = 30        # trail width off peak — widened after the CP Plus/3700 review: max tail capture
TIME_STOP = 120       # applies ONLY to unproven trades (gain < KEEP_GAIN_PCT at day 120)
KEEP_GAIN_PCT = 30    # a trade up ≥30% at day 120 is never time-stopped — it trails until it breaks
LATE_WINDOW = 120     # late-bloomer entries: first pivot cross day 26..120 (the Ather class)
LATE_VOL_X = 2.5      # ...but only with cross-day volume ≥2.5× avg (missed-winners study: PF 3.05)
