# Liquidity census

Measures how many US stocks and ETFs clear a liquidity floor, so the momentum universe filter is set from data rather than habit. Run at the hub on 2026-09-04: about 2,700 names had at least $20,000,000 average daily dollar volume over 30 sessions, against about 1,950 with at least 1,000,000 shares a day. Mo chose the $20M dollar-volume floor on 2026-09-06.

Files: `/Users/mtalib/workspace_repos/personal_repo/agentic_trading/research/liquidity_census/liquidity_census.py` (the measurement) and `liquidity_census.csv` beside it (the 2026-09-04 result, one row per symbol with close, 30-session average volume and dollar volume). Re-run the script to refresh the count.
